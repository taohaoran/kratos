# 元数据透传（metadata-propagation）

> 本文是 `metadata` 域下的叶子子系统文档。域级总览见 `../metadata.md`，本文只展开 kratos 内部的
> key-value 透传载体 `Metadata` 及其在 context 上的挂摘机制；与 transport header 的互转在 middleware/transport 域。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| Metadata 载体 | `map[string][]string`，内部表示请求头级别的透传 KV | `metadata/metadata.go:13` |
| 构造 | `New(mds ...map[string][]string)` 合并多个 map | `metadata/metadata.go:16` |
| 增删查 | `Add/Get/Set/Range/Values/Clone`，key 统一 `strings.ToLower` | `metadata/metadata.go:29-76` |
| 服务端上下文挂载 | `NewServerContext(ctx, md)` / `FromServerContext(ctx)` | `metadata/metadata.go:81-89` |
| 客户端上下文挂载 | `NewClientContext(ctx, md)` / `FromClientContext(ctx)` | `metadata/metadata.go:94-102` |
| 追加式注入 | `AppendToClientContext(ctx, k, v, ...)` 追加 KV 到客户端 metadata | `metadata/metadata.go:106` |
| 合并式注入 | `MergeToClientContext(ctx, cmd)` 整体合并另一个 Metadata | `metadata/metadata.go:119` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Metadata` | `metadata/metadata.go:13` | `map[string][]string` 别名，提供大小写不敏感访问 |
| `serverMetadataKey{}` | `metadata/metadata.go:78` | 服务端 ctx key（不可导出类型，防碰撞） |
| `clientMetadataKey{}` | `metadata/metadata.go:91` | 客户端 ctx key |
| `Add/Get/Set` | `metadata/metadata.go:29/39/48` | 操作均自动小写化 key |
| `AppendToClientContext` | `metadata/metadata.go:106` | 成对 KV 追加，奇数参数 panic |
| `MergeToClientContext` | `metadata/metadata.go:119` | 合并整个 Metadata，同名 key 覆盖 |

## 3. 关键调用链

**调用链一：服务端接收请求时注入 metadata**
1. transport 层（grpc/http server）从入站 header 解析出 `Metadata`。
2. 调 `metadata.NewServerContext(ctx, md)`，用 `serverMetadataKey{}` 作 key `context.WithValue` 挂入 ctx（`metadata/metadata.go:81-83`）。
3. 业务处理函数从 ctx 调 `metadata.FromServerContext(ctx)` 取出 Metadata（`metadata/metadata.go:86-89`）。
4. 服务端与客户端用不同 key，避免同一条 ctx 上 server-side 与 client-side metadata 混淆。

**调用链二：客户端发请求时透传**
1. 业务代码 `metadata.AppendToClientContext(ctx, "x-trace-id", "abc")`（`metadata/metadata.go:106`）。
2. 内部先 `FromClientContext(ctx)` 取已有 md，`Clone()` 后逐对 `Set`，再 `NewClientContext` 挂回（`metadata/metadata.go:110-115`）。
3. `MergeToClientContext` 同理，整体 `md[k] = v` 覆盖（`metadata/metadata.go:119-125`）。
4. 出站拦截器从 ctx 取 client metadata，写回 transport header。

**调用链三：Metadata 内部访问**
1. `Get(key)` 把 key 小写后取 slice 第一个值（`metadata/metadata.go:39-45`）。
2. `Add(key, value)` 小写 key 后 append 到已有 slice（`metadata/metadata.go:34-35`）——同一 key 支持多值。
3. `Set(key, value)` 小写 key 后整体替换为单值 slice（`metadata/metadata.go:52`）。
4. `Clone()` 对每个 value slice 用 `slices.Clone` 深拷贝（`metadata/metadata.go:70-76`）。

## 4. 配置项

| 项 | 默认 / 行为 | 位置 |
|----|-------------|------|
| key 大小写 | 所有读写统一 `strings.ToLower`，调用方传任意大小写均可 | `metadata/metadata.go:34/40/52/66` |
| 空 key | `Add/Set` 遇到空 key 直接忽略 | `metadata/metadata.go:30/49` |
| `AppendToClientContext` 参数 | 必须成对（偶数个），奇数个 panic | `metadata/metadata.go:107-109` |
| `Set` 空 value | 空 value 也忽略 | `metadata/metadata.go:49` |

## 5. 错误与重试语义

- **panic 而非 error**：`AppendToClientContext` 参数不成对时 `panic`（`metadata/metadata.go:108`），属编程错误，启动/调用期暴露。
- **不存在时返回零值**：`FromServerContext/FromClientContext` 返回 `(Metadata, bool)`，不存在时 `ok=false`；`Get` 不存在返回空字符串。
- **无错误返回**：Metadata 操作不返回 error，失败通过零值/ok bool 表达。
- **无重试**：纯内存操作。

## 6. 并发细节

- **context 不可变**：`New*Context` 返回新 ctx，原 ctx 不变；`Append/Merge` 先 `Clone` 再改，不修改调用方的 md。
- **map 非并发安全**：`Metadata` 本身是普通 map，多 goroutine 同时写同一实例不安全——但 kratos 约定每次传递都走 Clone，跨 goroutine 共享的是不可变副本。
- **无 goroutine/锁**：纯值操作。
- **ctx key 类型不可导出**：`serverMetadataKey{}`/`clientMetadataKey{}` 是包内私有类型，外部包无法构造同类型 key，杜绝 ctx key 碰撞。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `metadata/metadata.go`（唯一文件）。

**Out-of-Scope（不在本仓库源码内）**
- transport header ↔ Metadata 互转：由 `middleware/metadata` 中间件与 grpc/http transport 实现。
- 具体 header 名（如 `x-md-*`）的约定：在中间件层定义，不在本包。
- 跨进程透传的二进制编码：由 transport 协议负责。

## 8. 与相邻子系统交互

- **middleware/metadata → 本叶子**：入站中间件把 header 解析成 Metadata 挂 server ctx；出站中间件从 client ctx 取 Metadata 写 header。
- **transport 域 ↔ 本叶子**：grpc/http server/client 调用 `NewServerContext/NewClientContext` 把请求级 metadata 注入调用链。
- **业务代码 → 本叶子**：业务用 `FromServerContext` 读下游透传、用 `AppendToClientContext` 向上游/下游透传。
- **log 域 ↔ 本叶子**：日志 extractor 可从 ctx metadata 抽字段进日志。

## 9. 语言专项适配口径

- **context 传值模式**：用 `context.WithValue` 挂请求级元数据，符合 Go context 传请求作用域数据的惯例；用不可导出 struct 类型作 key 防碰撞是标准做法。
- **不可变更新**：`Append/Merge` 都先 `Clone` 再 `context.WithValue`，返回新 ctx，避免共享可变 map——与 Go 不可变数据并发安全惯例一致。
- **大小写不敏感**：HTTP header 本身大小写不敏感，Metadata 用小写 key 统一，使 grpc（大小写敏感）与 http（不敏感）语义对齐。
- **无控制器模式**：纯工具包。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| metadata-propagation 架构图 | `metadata-propagation-architecture.html` | architecture | showcase |

本叶子不补时序图：挂摘机制是同步的 ctx 值操作，已在第 3 节文字化；与 transport header 的互转在 middleware 域展开。JSON IR 源文件位于 `json/` 目录。
