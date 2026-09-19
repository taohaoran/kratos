# 内置韧性中间件（builtin-resilience-middleware）

> 本文是 `middleware` 域下的叶子子系统文档。域级总览见 `../middleware.md`。
> 本文展开 recovery（panic 恢复）、ratelimit（限流）、circuitbreaker（熔断）三个韧性中间件；
> 中间件栈组装见 `../middleware-stack/`，可观测性中间件见 `../builtin-observability-middleware/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| panic 恢复 `Recovery` | recover panic、打栈、记录日志、转成错误 | `middleware/recovery/recovery.go:46` |
| 恢复处理器 `WithHandler` | 自定义 panic 后的错误转换 | `middleware/recovery/recovery.go:31` |
| 服务端限流 `ratelimit.Server` | Allow 准入，拒绝返回 429 | `middleware/ratelimit/ratelimit.go:39` |
| 限流器注入 `WithLimiter` | 替换默认 bbr 限流器 | `middleware/ratelimit/ratelimit.go:28` |
| 客户端熔断 `circuitbreaker.Client` | 按 operation 取 breaker，触发即拒 | `middleware/circuitbreaker/circuitbreaker.go:38` |
| 熔断工厂 `WithBreakerFactory` | 每 operation 懒建一个 breaker | `middleware/circuitbreaker/circuitbreaker.go:23` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Recovery` | `middleware/recovery/recovery.go:46` | 返回恢复中间件 |
| `HandlerFunc` | `middleware/recovery/recovery.go:20` | panic 后错误转换函数 |
| `Latency{}` | `middleware/recovery/recovery.go:14` | panic 延迟 context key |
| `ratelimit.Server` | `middleware/ratelimit/ratelimit.go:39` | 限流中间件 |
| `Limiter`/`DoneFunc`/`DoneInfo` | `middleware/ratelimit/ratelimit.go:15-21` | 别名 internalratelimit 类型 |
| `circuitbreaker.Client` | `middleware/circuitbreaker/circuitbreaker.go:38` | 熔断中间件 |
| `CircuitBreaker` | `middleware/circuitbreaker/circuitbreaker.go:17` | 别名 internalbreaker 类型 |

**扩展点**：`WithLimiter` 注入自定义 Limiter（默认 bbr）；`WithBreakerFactory` 注入自定义熔断算法
（默认 SRE breaker）。

## 3. 关键调用链

**调用链 A：Recovery 恢复 panic**
1. `Recovery(opts)`（`recovery.go:46`）返回中间件；默认 handler 返回 `ErrUnknownRequest`，
   默认 logger 为 `slog.Default()`；
2. 包裹的 handler 先记 `startTime`，`defer` 中 `recover()`（`recovery.go:62-75`）；
3. 若 panic：`runtime.Stack` 取栈，`logger.ErrorContext` 记录，
   `ctx = context.WithValue(ctx, Latency{}, latency)`，`err = op.handler(ctx, req, rerr)`。

**调用链 B：ratelimit 服务端限流**
1. `Server(opts)`（`ratelimit.go:39`）默认 `internalratelimit.NewLimiter()`（bbr）；
2. `options.limiter.Allow()`（`ratelimit.go:48`）：返回非 nil 错误则直接返回 `ErrLimitExceed`（429）；
3. 否则执行 `handler(ctx, req)`，无论成功失败都 `done(DoneInfo{Err: err})`（`ratelimit.go:54-55`）。

**调用链 C：circuitbreaker 客户端熔断**
1. `Client(opts)`（`circuitbreaker.go:38`）默认 `group.NewGroup(NewBreaker)`；
2. `transport.FromClientContext(ctx)` 取 operation，`opt.group.Get(operation)` 取/建 breaker（`circuitbreaker.go:49-50`）；
3. `breaker.Allow()` 失败：`breaker.MarkFailed()` 并返回 `ErrNotAllowed`（503）（`circuitbreaker.go:51-56`）；
4. 允许则执行 handler；错误是 InternalServer/ServiceUnavailable/GatewayTimeout 时 `MarkFailed`，否则 `MarkSuccess`（`circuitbreaker.go:59-64`）。

## 4. 配置项

| option | 默认 | 行为 | 位置 |
|------|------|------|------|
| recovery `WithHandler` | 返回 ErrUnknownRequest | panic 错误转换 | `recovery.go:31` |
| recovery `WithLogger` | slog.Default() | 恢复日志器 | `recovery.go:39` |
| ratelimit `WithLimiter` | bbr limiter | 替换限流器 | `ratelimit.go:28` |
| circuitbreaker `WithBreakerFactory` | SRE NewBreaker | 每 operation 熔断工厂 | `circuitbreaker.go:23` |

## 5. 错误与重试语义

- recovery 把 panic 转成 `op.handler` 返回的错误（默认 `ErrUnknownRequest`），不重试。
- ratelimit 拒绝返回 `ErrLimitExceed`（429），不重试；`done` 回调反馈结果给限流器。
- circuitbreaker 触发返回 `ErrNotAllowed`（503），**本地拒绝仍 MarkFailed** 以抬高丢弃率
  （`circuitbreaker.go:53-55` 注释）；业务错误按类型判定成功/失败。
- 熔断/限流的具体退避与半开逻辑在 `internal/circuitbreaker`（SRE）与 `internal/ratelimit`（bbr）。

## 6. 并发细节

- recovery 的 `recover()` 在请求 goroutine 内，无共享状态。
- ratelimit 的 Limiter 是并发安全的（bbr 内部用 atomic/mutex），`Allow`/`done` 可并发调用。
- circuitbreaker 用 `group.Group[CircuitBreaker]` 按 operation 懒建并缓存 breaker，
  `group.Get` 内部同步；breaker 自身并发安全。
- context 传递链：调用 ctx → 中间件 → handler；recovery 用 `context.WithValue` 挂 Latency。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- middleware/recovery、middleware/ratelimit、middleware/circuitbreaker。
- internal/ratelimit（bbr）、internal/circuitbreaker（SRE）、internal/group（见 internal 包）。

**Out-of-Scope（不在本仓库源码内）**
- bbr/SRE 算法的具体数学——在 internal 包，本叶子仅引用。
- 中间件如何被 server 选中——见 middleware-stack 叶子。

## 8. 与相邻子系统交互

- **上游（transport server/client）**：经 middleware.Chain 包裹业务 handler。
- **横向（transport 抽象）**：circuitbreaker 用 `transport.FromClientContext` 取 operation。
- **横向（errors 包）**：错误码判定用 `errors.IsInternalServer` 等。
- **横向（log）**：recovery 用 slog 记录 panic。

## 9. 语言专项适配口径（Go）

- **并发模型**：recover 是 Go 特有的 panic 恢复原语；限流器/熔断器用 atomic+mutex 保证并发安全。
- **控制器模式**：不适用。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：三个中间件包单向依赖 `internal/{ratelimit,circuitbreaker,group}`、
  `errors`、`transport`、`middleware`，未越界。
- **可观测性边界**：recovery 记录 panic 日志；熔断/限流指标在 contrib otel。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 韧性中间件结构图 | `builtin-resilience-middleware-architecture.html` | architecture | showcase |

- JSON IR 源：`json/builtin-resilience-middleware-architecture.json`。
- 本叶子**不补时序图**：三个中间件逻辑扁平，用架构图表达组件与内部依赖即可。
