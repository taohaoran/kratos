# 可观测性生态适配（contrib-observability）

> 本文是 `contrib` 域下的叶子子系统文档。域级总览见 `../contrib.md`，本文只展开
> `contrib/otel/*`、`contrib/errortracker/sentry`、`contrib/opensergo` 对可观测性后端的适配。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| OTel 日志桥 | `otel/log.NewHandler` 用 `otelslog` 把 slog 记录转发到 OTel，自动带 trace 关联 | `contrib/otel/log/log.go:46` |
| OTel 链路追踪中间件 | `otel/tracing` 注入 tracer provider/propagator，做 span 生命周期 | `contrib/otel/tracing/tracing.go` |
| OTel 指标中间件 | `otel/metrics` 上报请求指标 | `contrib/otel/metrics/metrics.go` |
| Sentry 错误上报 | `errortracker/sentry` recovery 中间件把 panic/错误上报 Sentry | `contrib/errortracker/sentry/sentry.go` |
| OpenSergo 对接 | `opensergo` 作为 App Option，对接 OpenSergo 配置中心 metadata | `contrib/opensergo/opensergo.go` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `otel/log.NewHandler(name, opts...)` | `otel/log/log.go:46` | 返回 `slog.Handler`，可直接喂给 `log.NewLogger` |
| `otel/log` Options | `otel/log/log.go:13-43` | WithLoggerProvider/WithSchemaURL/WithSource/WithVersion |
| `otel/tracing` Options | `otel/tracing/tracing.go:17-30` | WithTracerProvider/WithPropagator/WithTracerName |
| `sentry.Options` | `errortracker/sentry/sentry.go:17-22` | Repanic/WaitForDelivery/timeout/tags |
| `opensergo.OpenSergo` | `opensergo/opensergo.go:39` | 持有 `MetadataServiceClient`，实现 kratos 选项 |

## 3. 关键调用链

**调用链一：OTel 日志接入**
1. 应用 `handler := otellog.NewHandler("my-app", otellog.WithLoggerProvider(provider))`（`otel/log/log.go:46`）。
2. `logger := log.NewLogger(handler)`，注册为 `log.SetDefault(logger)`。
3. 业务 `log.Info(...)` 经 kratos 装饰器链 → OTel slog bridge → OTLP 后端（`otel/log/log.go:50`）。
4. bridge 自动从 ctx 取 trace span 关联到日志记录。

**调用链二：OTel tracing 中间件**
1. 应用 `grpc.Middleware(tracing.ServerInterceptor(tracerProvider, propagator))`（`otel/tracing/tracing.go`）。
2. 每个请求开始建 span、注入/提取 propagator metadata、结束时记录。

**调用链三：Sentry recovery**
1. `sentry.Server(opts...)` 是 transport 中间件，panic 时 recover 并上报 Sentry（`errortracker/sentry/sentry.go`）。
2. `WithRepanic(true)` 决定上报后是否继续 panic。

## 4. 配置项

| option | 默认 / 行为 | 位置 |
|--------|-------------|------|
| otel/log `WithLoggerProvider` | 必填，OTel LoggerProvider | `otel/log/log.go:13` |
| otel/log `WithSource` | 是否上报源码位置 | `otel/log/log.go:31` |
| sentry `WithRepanic` | true | `sentry.go` |
| sentry `WithWaitForDelivery` | 是否阻塞等待上报完成 | `sentry.go` |
| opensergo `WithEndpoint` | OpenSergo 服务地址 | `opensergo.go:26` |

## 5. 错误与重试语义

- **上报失败**：OTel/Sentry 上报失败不影响业务，best-effort。
- **sentry WaitForDelivery**：为 true 时请求处理阻塞等上报完成，避免进程退出丢错误。
- **无业务重试**：可观测性是旁路。

## 6. 并发细节

- **slog.Handler 装饰**：otel/log 返回的 handler 可拼到 kratos 装饰器链，并发安全由 OTel bridge 保证。
- **中间件**：tracing/metrics/sentry 都是无状态中间件，并发安全。
- **无 goroutine 泄漏**：otel provider 生命周期由应用管理。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `contrib/otel/{log,metrics,tracing}`、`contrib/errortracker/sentry`、`contrib/opensergo`。

**Out-of-Scope（不在本仓库源码内）**
- OpenTelemetry SDK/Collector、Sentry 服务端、OpenSergo 服务端：外部系统。
- `go.opentelemetry.io/*`、`github.com/getsentry/sentry-go`、`github.com/opensergo/opensergo-go`：第三方库。

## 8. 与相邻子系统交互

- **log 域 ↔ otel/log**：otel/log 产出 `slog.Handler`，接入 v3 日志装饰器。
- **middleware 域 ↔ otel/tracing/metrics/sentry**：这些 contrib 实现 `middleware.Middleware`。
- **App ↔ opensergo**：opensergo 作为 `kratos.Option` 注入 App。

## 9. 语言专项适配口径

- **复用 slog**：otel/log 直接产出标准 `slog.Handler`，与 v3 基于 slog 的日志体系无缝衔接，无需自研桥。
- **独立 go.mod**：`contrib/otel/` 自带 go.mod，不把 OTel 依赖强加给不需要它的用户。
- **中间件适配**：tracing/metrics/sentry 都实现 `middleware.Middleware` 签名，与 recovery/logging 等内置中间件同构。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| contrib-observability 架构图 | `contrib-observability-architecture.html` | architecture | showcase |

JSON IR 源文件位于 `json/` 目录。
