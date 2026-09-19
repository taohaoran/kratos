# 内置可观测性中间件（builtin-observability-middleware）

> 本文是 `middleware` 域下的叶子子系统文档。域级总览见 `../middleware.md`。
> 本文展开 logging（日志）、metadata（元数据透传）、selector（按条件选中间件）、validate（请求校验）
> 四个中间件；中间件栈组装见 `../middleware-stack/`，韧性中间件见 `../builtin-resilience-middleware/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 服务端日志 `logging.Server` | 记录 kind/operation/args/code/reason/latency | `middleware/logging/logging.go:23` |
| 客户端日志 `logging.Client` | 同上，client 侧 | `middleware/logging/logging.go:72` |
| 参数脱敏 `Redacter` | req 实现 Redact() 则脱敏打印 | `middleware/logging/logging.go:18` |
| 服务端元数据 `metadata.Server` | 按前缀把请求头收进 ctx metadata | `middleware/metadata/metadata.go:45` |
| 客户端元数据 `metadata.Client` | 把常量/ctx metadata 写出入站请求头 | `middleware/metadata/metadata.go:75` |
| 条件选中间件 `selector.Server/Client` | 按 prefix/regex/path/match 决定是否套中间件 | `middleware/selector/selector.go:42` |
| 请求校验 `validate.Validator` | req 自校验 + 自定义 ValidatorFunc | `middleware/validate/validate.go:43` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `logging.Server`/`Client` | `middleware/logging/logging.go:23/72` | 日志中间件工厂 |
| `Redacter` | `middleware/logging/logging.go:18` | 脱敏接口 |
| `metadata.Server`/`Client` | `middleware/metadata/metadata.go:45/75` | 元数据透传中间件 |
| `selector.Builder` | `middleware/selector/selector.go:29` | 条件选择器建造器 |
| `MatchFunc` | `middleware/selector/selector.go:14` | 自定义匹配函数 |
| `validate.Validator` | `middleware/validate/validate.go:43` | 校验中间件 |
| `validator` interface | `middleware/validate/validate.go:14` | 自校验接口（`Validate() error`） |

**扩展点**：`Redacter`/`validator` 接口由业务请求类型实现；`selector.Match` 允许自定义匹配；
`validate.Validator` 可注入 protovalidate 等外部校验器。

## 3. 关键调用链

**调用链 A：logging 记录请求**
1. `Server(logger)`（`logging.go:23`）默认 slog.Default；
2. `transport.FromServerContext(ctx)` 取 kind/operation（`logging.go:40-43`），记 startTime；
3. 执行 handler；`errors.FromError(err)` 取 code/reason（`logging.go:45-48`）；
4. `extractArgs`（Redact→Stringer→%+v）与 `extractError`（err→LevelError+栈）组装 attrs，
   `logger.LogAttrs` 输出（`logging.go:50-65`）。

**调用链 B：metadata 透传**
1. `Server`（`metadata.go:45`）默认收 `x-md-` 前缀头：从 `tr.RequestHeader()` 遍历，
   命中前缀的键值 `md.Add`，最后 `metadata.NewServerContext(ctx, md)`（`metadata.go:61-68`）；
2. `Client`（`metadata.go:75`）默认发 `x-md-global-`：先加常量 md，再加客户端 ctx md，
   再加服务端 ctx md 中命中前缀的，全部写入请求头（`metadata.go:91-112`）。

**调用链 C：selector 条件包裹**
1. `Build()`（`selector.go:76`）编译 regex，返回 `selector(...)` 中间件；
2. 调用时 `matches(ctx, transporter)`（`selector.go:93`）：取 operation，依次试 prefix/regex/path/自定义 match；
3. 不匹配则直接 `handler(ctx, req)`；匹配则 `middleware.Chain(ms...)(handler)(ctx, req)`（`selector.go:129-132`）。

**调用链 D：validate 校验**
1. `Validator(validators...)`（`validate.go:43`）：req 实现 `validator` 接口则先 `req.Validate()`；
2. 再跑注入的 `validators`；任一失败返回 `errors.BadRequest("VALIDATOR", ...).WithCause(err)`（`validate.go:48/53`）。

## 4. 配置项

| option | 默认 | 行为 | 位置 |
|------|------|------|------|
| logging `logger` | slog.Default() | 日志器 | `logging.go:24` |
| metadata `WithConstants` | 空 | 常量元数据 | `metadata.go:31` |
| metadata `WithPropagatedPrefix` | server `x-md-` / client `x-md-global-` | 透传前缀 | `metadata.go:38` |
| selector `Prefix/Regex/Path/Match` | 空 | 匹配条件 | `selector.go:52-73` |
| validate `validators...` | 空 | 自定义校验函数 | `validate.go:43` |

## 5. 错误与重试语义

- logging 不改变错误，只记录；`extractError` 决定日志级别。
- metadata 不产生错误。
- selector 不匹配时透传，匹配时套中间件；中间件内部错误按其语义。
- validate 校验失败返回 `BadRequest("VALIDATOR")`，不重试。

## 6. 并发细节

- 各中间件无共享可变状态；Builder 在 Build 期编译 regex，运行期只读。
- logging/metadata 在请求 goroutine 内执行，ctx 贯穿。
- metadata 操作 `md.Clone()` 避免污染原始 metadata（`metadata.go:59`）。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- middleware/logging、middleware/metadata、middleware/selector、middleware/validate。

**Out-of-Scope（不在本仓库源码内）**
- slog 后端实现——第三方依赖。
- protovalidate/fieldbehavior 等外部校验器——在用户代码或 contrib。
- otel 日志/指标/追踪——在 contrib/otel。

## 8. 与相邻子系统交互

- **上游（transport server/client）**：经 middleware.Chain 包裹。
- **横向（transport 抽象）**：logging/metadata/selector 用 `FromServerContext/FromClientContext` 读 Transporter。
- **横向（metadata 包）**：metadata 中间件用 `metadata.NewServerContext/FromClientContext` 透传键值。
- **横向（errors 包）**：logging 用 `errors.FromError`，validate 用 `errors.BadRequest`。

## 9. 语言专项适配口径（Go）

- **并发模型**：无 goroutine；Builder 构造期编译 regex，运行期只读。
- **控制器模式**：不适用。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：四个中间件包依赖 `metadata`、`errors`、`transport`、`middleware`，单向清晰。
- **可观测性边界**：logging 基于标准库 slog；更丰富的 metrics/tracing 在 contrib/otel。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 可观测性中间件结构图 | `builtin-observability-middleware-architecture.html` | architecture | showcase |

- JSON IR 源：`json/builtin-observability-middleware-architecture.json`。
- 本叶子**不补时序图**：四个中间件逻辑扁平，用架构图表达组件关系即可。
