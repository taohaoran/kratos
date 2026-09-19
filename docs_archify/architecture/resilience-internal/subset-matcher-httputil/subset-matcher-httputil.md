# subset / matcher / httputil / context 工具集（subset-matcher-httputil）

> 本文是 `resilience-internal` 域下的叶子子系统文档。域级总览见 `../resilience-internal.md`。
> 本文展开 `internal/subset`、`internal/matcher`、`internal/httputil`、`internal/context` 四个工具包。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 一致性哈希子集 | `Subset[M](selectKey, inss, num)` 为 key 选确定性节点子集 | `internal/subset/subset.go:17` |
| 虚拟节点环 | 每成员 160 个虚拟节点，FNV-1a 哈希 | `internal/subset/subset.go:54-56,118` |
| 中间件匹配 | `Matcher`：按 operation 精确/前缀匹配挂中间件 | `internal/matcher/middleware.go:11` |
| content-type 构造 | `ContentType(subtype)` 拼 `application/<subtype>` | `internal/httputil/http.go:12` |
| content-type 解析 | `ContentSubtype(ct)` 取子类型 | `internal/httputil/http.go:21` |
| 双 ctx 合并 | `Merge(p1,p2)` 返回合并 ctx 与 cancel | `internal/context/context.go:23` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `consistent[M]` | `subset.go:31` | 一致性哈希环：`circle map[uint32]M`、`sortedHashes` |
| `Matcher` interface | `matcher/middleware.go:11` | `Use/Add/Match` 中间件匹配契约 |
| `matcher` struct | `matcher/middleware.go:24` | `defaults` + 前缀表 + 精确表 |
| `mergeCtx` | `context/context.go:10` | 双父 ctx 合并实现：`done`/`cancelCh`/`sync.Once` |

## 3. 关键调用链

**链路一：`subset.Subset` 选子集**（`subset.go:17`）
1. `num<=0` 或 `len(inss)<=num` 直接返回全集（`subset.go:18-20`）。
2. 建 `consistent` 环，`set(inss)` 去重并每成员加 160 个虚拟节点（`subset.go:44-59`）。
3. `getN(key,num)`：`search(hashKey(key))` 二分定位起点（`subset.go:88-96`），沿环顺时针取 n 个不同成员（`subset.go:61-86`）。
4. 异常（空环）回退返回全集（`subset.go:25-27`）。

**链路二：`matcher.Match` 中间件匹配**（`middleware.go:48`）
1. 先追加 `defaults`（`Use` 注册的全局中间件）（`middleware.go:50-52`）。
2. 精确命中 `matches[operation]` 直接返回（`middleware.go:53-55`）。
3. 否则按**已降序排列**的前缀表逐个 `HasPrefix` 匹配（`middleware.go:56-60`）——长前缀优先。

**链路三：`context.Merge` 双父合并**（`context.go:23`）
1. 若任一父 ctx 已 Done，立即 `finish`（`context.go:30-34`）。
2. 否则 `go mc.wait()` 阻塞等待任一父 Done 或 `cancelCh`（`context.go:36,50-61`）。
3. `Value` 先查 parent1 再查 parent2（`context.go:110-115`）；`Deadline` 取较早者（`context.go:94-107`）。

## 4. 配置项

本叶子无运行时配置项。
- `subset`：虚拟节点数硬编码 160（`subset.go:54`）。
- `matcher`：`Add` 时以 `*` 结尾的 selector 自动转前缀匹配（`middleware.go:35-44`）。

## 5. 错误与重试语义

- `subset`：空环返回 `errEmptyCircle`，但 `Subset` 顶层捕获后回退全集（`subset.go:62-63,25-27`），对调用方透明。
- `matcher`：无匹配返回仅 defaults（可能为空），不报错。
- `httputil`：`ContentSubtype` 无 `/` 或格式异常返回空串（`http.go:23-32`）。
- `context.Merge`：不重试；任一父取消即传播。
- 无退避。

## 6. 并发细节

- **subset**：纯函数，每次调用新建环，无共享状态，并发安全。
- **matcher**：`Add` 在初始化期写、`Match` 在运行期读；无锁——要求"先 Add 完再 Match"，否则需外部同步。
- **context.Merge**：`doneOnce`/`cancelOnce sync.Once` 保证 `close(done)`/`close(cancelCh)` 只执行一次（`context.go:41-48,63-67`）；`doneMark atomic.Bool` 无锁读（`context.go:14,76`）。`wait` goroutine 由 `Merge` 启动，父 ctx 取消或 `cancel()` 后即退出，无泄漏。
- **goroutine**：仅 `context.Merge` 在未立即 Done 时起一个 `wait` goroutine。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `internal/subset`、`internal/matcher`、`internal/httputil`、`internal/context`。

**Out-of-Scope（不在本仓库源码内）**
- `hash/fnv`、标准库 `context`。
- 消费方：`transport/grpc/resolver/discovery`、`transport/http/resolver` 用 `subset.Subset`；`transport/http|grpc/server` 用 `matcher`；`transport/grpc/interceptor` 用 `context.Merge`。
- 不做：子集变更的 watch 通知、matcher 的热更新。

## 8. 与相邻子系统交互

- 上游：客户端 resolver 用 `subset.Subset(selectorKey, instances, subsetSize)` 从全量实例切出客户端专属子集（`transport/grpc/resolver/discovery/resolver.go:72`）；server 用 `matcher` 按 operation 选中间件链。
- 本叶子 → 下游：无外部网络依赖。

## 9. 语言专项适配口径

- **并发模型**：Go 泛型 `Subset[M member]`（`subset.go:17`）；`context.Merge` 是标准库 `context.Context` 接口的自定义实现，用 `sync.Once`+`atomic.Bool` 保证并发安全的取消传播。
- **internal 边界**：四包均 `internal/`，仅框架内部 transport 使用。
- **依赖方向**：subset 依赖 registry 实例的 `String()` 表示；matcher 依赖 `middleware.Middleware` 类型，方向单向。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `subset-matcher-httputil-architecture.html` | architecture | standard |

JSON IR 位于 `json/`。降 standard 原因：四分支组件图在 showcase 严格布局下连线穿组件，调整 http 位置后 standard 通过（如实披露）。本叶子不补 sequence/dataflow：均为同步工具函数；`context.Merge` 的取消传播已在第 6 节文字化。
