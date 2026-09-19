# gRPC 服务端（grpc-server）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文只展开 gRPC **服务端**的包装、生命周期与拦截器链；gRPC 客户端/负载均衡见 `../grpc-client/`；
> transport 抽象接口见 `../transport-abstraction/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 服务端包装 `Server` | 内嵌 `*grpc.Server`，实现 `transport.Server` 与 `transport.Endpointer` | `transport/grpc/server.go:124` |
| 选项构造 `NewServer` | functional options 组装网络/地址/超时/中间件/TLS/拦截器 | `transport/grpc/server.go:146` |
| 生命周期 Start | 监听端口、恢复健康检查、`Serve(lis)` 阻塞服务 | `transport/grpc/server.go:216` |
| 生命周期 Stop | 优雅停止（GracefulStop）+ 超时强制 Stop | `transport/grpc/server.go:227` |
| 端点暴露 `Endpoint` | 计算真实监听地址并生成 `grpc://` scheme 的 `*url.URL` | `transport/grpc/server.go:208` |
| 一元拦截器 | 挂载 Transporter、注入超时、串接中间件、回写应答头 | `transport/grpc/interceptor.go:17` |
| 流拦截器 | 包装 ServerStream，对每条消息（Send/Recv）串中间件 | `transport/grpc/interceptor.go:70` |
| 服务端中间件挂载 | `Use(selector, m...)` 按方法选择器注册中间件 | `transport/grpc/server.go:200` |
| 内置附属服务 | 健康检查、gRPC reflection、gRPC admin | `transport/grpc/server.go:183` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Server` struct | `transport/grpc/server.go:124` | 内嵌 `*grpc.Server`；持有 network/address/endpoint/timeout/两个 matcher/自定义拦截器 |
| `ServerOption` func | `transport/grpc/server.go:31` | functional option 类型 |
| `unaryServerInterceptor()` | `transport/grpc/interceptor.go:17` | 返回一元服务端拦截器闭包 |
| `streamServerInterceptor()` | `transport/grpc/interceptor.go:70` | 返回流式服务端拦截器闭包 |
| `wrappedStream` | `transport/grpc/interceptor.go:51` | 包装 `grpc.ServerStream`，重写 `Context()` 与 `SendMsg/RecvMsg` |
| `matcher.Matcher` | `internal/matcher/middleware.go` | 按 operation 选择器匹配中间件集合（见 middleware-stack 叶子） |
| `stream` | `transport/grpc/interceptor.go:105` | 私有 context key，承载原始 ServerStream |

**扩展点**：`Use(selector, m...)` 的 selector 支持 `/*`、`/pkg.Service/*`、`/pkg.Service/Method` 三级粒度
（`server.go:196` 注释），是服务端按方法挂载中间件的扩展 seam。

## 3. 关键调用链

**调用链 A：服务端启动**
1. App 调用 `Server.Start(ctx)`（`server.go:216`）；
2. `listenAndEndpoint()`（`server.go:249`）在 `s.lis == nil` 时 `net.Listen(s.network, s.address)`（默认 `tcp`+`:0`），
   再用 `host.Extract` 取真实地址、`endpoint.NewEndpoint(endpoint.Scheme("grpc", ...))` 生成 `grpc://` URL；
3. `s.baseCtx = ctx`，`s.health.Resume()` 恢复健康状态，`s.Serve(s.lis)`（`server.go:223`）阻塞接受连接。

**调用链 B：一元请求处理**
1. gRPC 运行时进入 `unaryServerInterceptor`（`interceptor.go:18`）；
2. `ic.Merge(ctx, s.baseCtx)`（`interceptor.go:19`）把请求 ctx 与 server 基 ctx 合并，`defer cancel()`；
3. 从入站 metadata 取请求头，构造 `Transport`，`transport.NewServerContext(ctx, tr)`（`interceptor.go:31`）挂载；
4. 若 `s.timeout > 0`（默认 1s），`context.WithTimeout` 加超时（`interceptor.go:33`）；
5. `s.middleware.Match(tr.Operation())` 取匹配中间件并 `middleware.Chain(next...)(h)`（`interceptor.go:39-40`）；
6. 执行 `h(ctx, req)` 到业务 handler，最后 `grpc.SetHeader(ctx, replyHeader)` 回写应答头（`interceptor.go:44`）。

**调用链 C：优雅停止**
1. `Stop(ctx)`（`server.go:227`）先 `adminClean()`、`health.Shutdown()`；
2. 启动 goroutine 调 `s.GracefulStop()`，完成后 `close(done)`（`server.go:233-238`）；
3. `select` 等待 `<-done` 或 `<-ctx.Done()`；超时则 `s.Server.Stop()` 强制停止并告警（`server.go:240-245`）。

## 4. 配置项

| option / 字段 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `Network(network)` | `tcp` | 监听网络 | `server.go:34` |
| `Address(addr)` | `:0` | 监听地址，`:0` 随机端口 | `server.go:41` |
| `Timeout(d)` | `1s` | 一元请求超时，>0 才生效 | `server.go:55` |
| `Middleware(m...)` | 空 | 一元中间件 | `server.go:62` |
| `StreamMiddleware(m...)` | 空 | 流式中间件 | `server.go:68` |
| `CustomHealth()` | 关 | 启用则不自动注册内置 health | `server.go:75` |
| `TLSConfig(c)` | 无 | 配置 TLS 凭证 | `server.go:82` |
| `Listener(lis)` | 无 | 外部传入 listener | `server.go:89` |
| `UnaryInterceptor/StreamInterceptor` | 空 | 追加 gRPC 原生拦截器 | `server.go:96` |
| `DisableReflection()` | 关 | 禁用 reflection | `server.go:110` |
| `Options(opts...)` | 空 | 透传 grpc.ServerOption | `server.go:117` |

## 5. 错误与重试语义

- `listenAndEndpoint()` 监听失败时把错误存入 `s.err` 并返回，`Start`/`Endpoint` 透传 `s.err`（`server.go:253`）；
  同一 server 重复 listen 不会重复报错（`s.lis != nil` 短路）。
- 本叶子**不做请求级重试**；超时由 `context.WithTimeout` 控制，业务 handler 收到 ctx 取消后返回错误，
  gRPC 运行时负责把错误转成 status。
- 停止时优雅停止无法在 ctx 超时内完成则降级为强制 `Stop()`（`server.go:244`），不重试。
- `wrappedStream.SendMsg/RecvMsg` 若 ctx 中无 Transporter，返回包装错误
  `transport value stored in ctx returns: ...`（`interceptor.go:121`）。

## 6. 并发细节

- **goroutine 启停边界**：`Stop` 中起一个 goroutine 跑 `GracefulStop()`（`server.go:234`），
  以 `done` channel 通知主 goroutine；主 goroutine 同时 `select` ctx.Done，超时即强制停止，无泄漏。
- **请求并发**：每个一元请求在 gRPC 运行时的 goroutine 中执行，`ic.Merge` 合并 ctx 后 `defer cancel()`，
  保证请求结束释放资源；`baseCtx` 在 `Start` 时固定，请求级 ctx 与之合并以传播服务端取消。
- **流式中间件**：`wrappedStream.SendMsg/RecvMsg` 对每条消息单独 `middleware.Chain` 并在请求 goroutine 内执行
  （`interceptor.go:114`/`132`），无跨请求共享状态。
- **临界区**：`Server` 字段在 `NewServer` 构造期一次性写定，运行期只读；`matcher.Matcher` 内部有自己的并发
  控制（见 middleware-stack 叶子），本层不加额外锁。
- **context 传递链**：请求 ctx → Merge(baseCtx) → NewServerContext → WithTimeout → 中间件链 → handler，
  超时/取消沿链传播。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `transport/grpc/server.go`：Server 包装、选项、Start/Stop/Endpoint、Use。
- `transport/grpc/interceptor.go`：一元/流拦截器与 wrappedStream。
- `transport/grpc/transport.go`：Transporter 实现（见 transport-abstraction 叶子）。

**Out-of-Scope（不在本仓库源码内）**
- gRPC 运行时（`google.golang.org/grpc`）：连接管理、帧编解码、`Serve`/`GracefulStop` 实际行为——第三方依赖。
- health/reflection/admin 子系统实现——第三方依赖。
- 中间件链的具体实现（recovery/logging 等）——middleware 域叶子。
- gRPC client/balancer/resolver——见 grpc-client 叶子。

## 8. 与相邻子系统交互

- **上游（App 生命周期）**：App 通过 `transport.Server` 接口 `Start(ctx)`/`Stop(ctx)` 调度本 server；
  App 不感知 gRPC。
- **下游（gRPC 运行时）**：`Server` 内嵌 `*grpc.Server`，业务通过 proto 生成代码注册 service。
- **横向（transport 抽象）**：拦截器用 `transport.NewServerContext` 挂载 Transporter（见 transport-abstraction）。
- **横向（中间件域）**：`s.middleware.Match(operation)` 选择并链化中间件（见 middleware-stack）。
- **横向（注册发现）**：`Endpoint()` 返回的 `*url.URL` 被 registry 域用于注册。

## 9. 语言专项适配口径（Go）

- **并发模型**：依赖 gRPC 运行时的 goroutine-per-RPC 模型；本层仅负责 ctx 合并、超时注入、中间件链组装。
  停止用 goroutine + done channel + ctx.Done select 的标准优雅停止范式。
- **控制器模式**：非 Reconciler 场景；服务端是请求驱动模型，差异于 K8s 的调谐循环。
- **多二进制与部署边界**：本叶子属主库运行时包，不对应 cmd/ 入口。
- **internal 边界与依赖方向**：`transport/grpc` 单向依赖 `internal/{endpoint,host,matcher,context}`、
  `middleware`、`transport`、`log`，依赖方向清晰；`internal/` 未被外部包越界 import。
- **可观测性边界**：`log.Info/Warn` 输出监听/停止日志；错误以 gRPC status 透传，otel 追踪/指标在 contrib 包。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| gRPC 服务端结构与拦截器链图 | `grpc-server-architecture.html` | architecture | standard（showcase 多次校验标签间距仍失败，按规程降档） |
| 一元请求处理时序图 | `grpc-server-sequence.html` | sequence | showcase |

- JSON IR 源：`json/grpc-server-architecture.json`、`json/grpc-server-sequence.json`。
- 本叶子**不补数据流图**：请求处理是"拦截器链调用"而非管道/血缘，用 sequence 表达时序更贴切。
