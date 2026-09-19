# 中间件栈组装与匹配（middleware-stack）

> 本文是 `middleware` 域下的叶子子系统文档。域级总览见 `../middleware.md`。
> 本文只展开中间件**类型定义、Chain 组装与按 operation 匹配**；各内置中间件实现见
> `../builtin-resilience-middleware/`、`../builtin-observability-middleware/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 处理器类型 `Handler` | `func(ctx, req) (any, error)`，中间件包裹的核心 | `middleware/middleware.go:8` |
| 中间件类型 `Middleware` | `func(Handler) Handler`，transport 无关的装饰器 | `middleware/middleware.go:11` |
| 链组装 `Chain` | 把多个中间件反向包裹成一个 | `middleware/middleware.go:14` |
| 匹配器接口 `Matcher` | Use/Add/Match 按 operation 选中间件 | `internal/matcher/middleware.go:11` |
| 前缀匹配 | `/*` 选择器注册为前缀，最长前缀优先 | `internal/matcher/middleware.go:34` |
| 默认中间件 | `Use` 注册全局默认，Match 时总是前置 | `internal/matcher/middleware.go:30` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Handler` | `middleware/middleware.go:8` | 业务处理函数签名 |
| `Middleware` | `middleware/middleware.go:11` | 装饰器签名 |
| `Chain` | `middleware/middleware.go:14` | 反向包裹组装链 |
| `Matcher` interface | `internal/matcher/middleware.go:11` | 匹配器契约 |
| `matcher` struct | `internal/matcher/middleware.go:24` | prefix 列表 + defaults + matches 表 |

**扩展点**：`Matcher` 接口是 transport 与中间件之间的 seam——gRPC/HTTP server 各持有一个
`matcher.Matcher`，按 operation 选择中间件；`Add` 的 selector 支持三级粒度（`/*`、`/pkg.Svc/*`、`/pkg.Svc/Method`）。

## 3. 关键调用链

**调用链 A：Chain 组装**
1. `Chain(m...)`（`middleware.go:14`）返回一个 Middleware；
2. 对 `next` 从后向前包裹：`for i := len(m)-1; i>=0; i-- { next = m[i](next) }`（`middleware.go:16-18`）；
3. 执行时顺序为 `m[0] → m[1] → ... → 业务 handler`，与声明顺序一致。

**调用链 B：Add 注册**
1. `Add(selector, ms...)`（`matcher/middleware.go:34`）：若 selector 以 `*` 结尾，
   去掉 `*` 存入 `prefix`，并按字典序降序排序（最长前缀在前，`matcher/middleware.go:41-43`）；
2. 无论是否前缀，都写入 `matches[selector] = ms`。

**调用链 C：Match 选择**
1. `Match(operation)`（`matcher/middleware.go:48`）先把 `defaults` 放入结果；
2. 精确命中 `matches[operation]` 则直接返回（`matcher/middleware.go:53-55`）；
3. 否则遍历已排序的 `prefix`，首个 `strings.HasPrefix(operation, prefix)` 命中即返回（`matcher/middleware.go:56-59`）；
4. 都未命中则只返回 defaults。

## 4. 配置项

本叶子为纯组装/匹配逻辑，**无运行时配置项**。中间件集合由 `Use`/`Add` 在构造期注册。

## 5. 错误与重试语义

- 本叶子不产生错误、不重试；中间件链中任一中间件返回的 error 沿链向上传递。
- `Match` 未命中时返回空/defaults 列表，不报错。

## 6. 并发细节

- `matcher` 的 `prefix`/`defaults`/`matches` 在 `Add`/`Use` 注册期写入，运行期 `Match` 只读；
  若注册与服务并发进行需外部同步（框架在 NewServer 构造期完成注册）。
- `Chain` 是纯函数，无共享状态。
- 中间件链在每个请求的 goroutine 内执行，`ctx` 贯穿。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `middleware/middleware.go`：Handler/Middleware/Chain。
- `internal/matcher/middleware.go`：Matcher 实现。

**Out-of-Scope（不在本仓库源码内）**
- 各中间件具体实现（recovery/logging 等）——见本域其他叶子。
- transport 如何调用 Match——见 transport 域各 server 叶子。

## 8. 与相邻子系统交互

- **上游（transport server）**：gRPC/HTTP server 持有 `matcher.Matcher`，请求时 `Match(operation)` 取中间件。
- **下游（内置中间件）**：本叶子定义类型与组装，具体中间件由本域其他叶子提供。
- **横向（transport 抽象）**：中间件通过 `transport.FromServerContext/FromClientContext` 读 Transporter。

## 9. 语言专项适配口径（Go）

- **并发模型**：无 goroutine；注册期写、运行期读，依赖构造期完成注册的约定。
- **控制器模式**：不适用。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：`internal/matcher` 仅被 `transport` 包 import，未越界；
  `middleware` 包是对外公开类型定义。
- **可观测性边界**：本叶子无可观测逻辑。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 中间件链组装与匹配图 | `middleware-stack-architecture.html` | architecture | standard（showcase 标签间距校验多次不过，按规程降档） |

- JSON IR 源：`json/middleware-stack-architecture.json`。
- 本叶子**不补时序图**：Chain 是静态包裹、Match 是查表，用架构图表达组件关系即可。
