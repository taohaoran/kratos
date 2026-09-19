# 传输层抽象（transport-abstraction）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文只展开 transport 包的**接口抽象与 context 挂载机制**；gRPC/HTTP 的具体服务端、客户端实现
> 分别见 `../grpc-server/`、`../grpc-client/`、`../http-server/`、`../http-client/` 等叶子。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 传输服务接口 `Server` | 抽象任意传输后端的生命周期（启动/停止），供 App 生命周期统一调度 | `transport/transport.go:17` |
| 注册端点接口 `Endpointer` | 返回服务对外暴露的 `*url.URL`，供服务注册发现使用 | `transport/transport.go:23` |
| 报文头接口 `Header` | 键值型报文头的统一抽象（Get/Set/Add/Keys/Values） | `transport/transport.go:28` |
| 传输上下文接口 `Transporter` | 一次请求的传输侧视图：协议种类、端点、操作名、请求/应答头 | `transport/transport.go:37` |
| 协议种类枚举 `Kind` | `KindGRPC="grpc"` / `KindHTTP="http"` | `transport/transport.go:61` |
| 服务端 context 挂载 | `NewServerContext` / `FromServerContext` 把 `Transporter` 存入 context | `transport/transport.go:77` |
| 客户端 context 挂载 | `NewClientContext` / `FromClientContext` 把客户端 `Transporter` 存入 context | `transport/transport.go:88` |
| 编码层自注册 | blank import 形式引入 form/json/proto/protojson/xml/yaml 编码器 | `transport/transport.go:8` |

**对外暴露点**：本包是整个框架 transport 域的"契约层"——所有 gRPC/HTTP 的 server 与 client
实现都必须满足此处定义的接口；中间件（logging/metadata/selector 等）也通过此处的
`FromServerContext`/`FromClientContext` 读取传输信息。

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Server` interface | `transport/transport.go:17` | `Start(ctx) error` / `Stop(ctx) error`，传输后端生命周期契约 |
| `Endpointer` interface | `transport/transport.go:23` | `Endpoint() (*url.URL, error)`，注册发现所需地址 |
| `Header` interface | `transport/transport.go:28` | 键值报文头抽象，屏蔽 `http.Header` 与 gRPC `metadata.MD` 差异 |
| `Transporter` interface | `transport/transport.go:37` | `Kind()`/`Endpoint()`/`Operation()`/`RequestHeader()`/`ReplyHeader()`，请求级传输视图 |
| `Kind`（string） | `transport/transport.go:61` | 协议种类，String() 返回原串 |
| `serverTransportKey{}` / `clientTransportKey{}` | `transport/transport.go:72` | 不导出的 context key，避免与外部 key 冲突 |
| `grpc.Transport` | `transport/grpc/transport.go:13` | gRPC 侧 `Transporter` 实现，`headerCarrier` 包裹 `metadata.MD` |
| `http.Transport` | `transport/http/transport.go:30` | HTTP 侧 `Transporter` 实现，额外暴露 `Request()`/`Response()`/`PathTemplate()` |

**扩展点（非显而易见）**：
- `Header` 接口是"适配器 seam"——gRPC 用 `headerCarrier metadata.MD`（`transport/grpc/transport.go:51`），
  HTTP 用 `headerCarrier http.Header`（`transport/http/transport.go:110`），两者各自把底层报文头
  适配成同一接口，使中间件无需感知协议。
- HTTP 包额外定义了 `Transporter`（内嵌 `transport.Transporter`，增加 `Request()`/`PathTemplate()`，
  `transport/http/transport.go:15`）与 `ResponseTransporter`（再增 `Response()`，
  `transport/http/transport.go:24`）两个更宽接口，用于文件下载、流式响应等场景。

## 3. 关键调用链

**调用链 A：服务端把 Transporter 挂入 context（gRPC 入口拦截器）**
1. gRPC server 一元/流拦截器在处理请求前构造 `grpc.Transport` 实例；
2. `transport/grpc/interceptor.go:31` 执行 `ctx = transport.NewServerContext(ctx, tr)`，
   把 Transporter 写入 `serverTransportKey{}`；
3. 后续中间件（如 `middleware/logging/logging.go:40`）用 `transport.FromServerContext(ctx)`
   取出 Transporter，读取 `Operation()`/`Endpoint()` 记录日志。

**调用链 B：HTTP 服务端挂载**
1. HTTP router 为每个请求构造 `http.Transport`；
2. `transport/http/server.go:298` 执行 `tr.request = req.WithContext(transport.NewServerContext(ctx, tr))`；
3. `transport/http/context.go:94` 的 `wrapper.Middleware` 用 `transport.FromServerContext(c.req.Context())`
   取 Transporter，按 `tr.Operation()` 做中间件匹配（`middleware.Match`）。

**调用链 C：客户端发起请求时挂载**
1. gRPC client 一元调用前，`transport/grpc/client.go:202` 执行
   `ctx = transport.NewClientContext(ctx, &Transport{...})`；
2. 负载均衡器 `transport/grpc/balancer.go:66` 用 `transport.FromClientContext(info.Ctx)`
   取出 Transporter，读取 `NodeFilters()` 做节点过滤；
3. HTTP client 在 `transport/http/client.go:249` 同样挂载客户端 Transporter。

> 与图对应：下图给出"接口定义 → 两种协议实现 → context 读写消费方"的结构；上述调用链给出
> 挂载（写）与读取（读）的时序与文件位置。

## 4. 配置项

本叶子为纯接口/契约层，**无运行时配置项、无 flag、无配置文件项**。
其行为由各后端（gRPC/HTTP server/client）的 option 决定，详见对应叶子。

## 5. 错误与重试语义

- `FromServerContext`/`FromClientContext` 用类型断言 `.(Transporter)` 取值（`transport/transport.go:83`、`:94`），
  若 ctx 中未挂载或类型不符，返回 `(nil, false)`，**不返回错误**——消费方以 `ok` 布尔判断降级。
- `Endpointer.Endpoint()` 可返回错误（`transport/transport.go:24`），由注册发现方负责处理，
  本接口层不定义重试策略。
- 本叶子不做任何重试、退避；重试语义由具体传输后端与中间件（熔断/限流）承担。

## 6. 并发细节

- context key 采用**未导出的空结构体指针** `serverTransportKey{}`（`transport/transport.go:72`），
  是 Go 官方推荐的无碰撞 context key 模式，无需加锁。
- `context.WithValue` 不可变、线程安全；每个请求独立持有自己的 Transporter 实例，
  无共享可变状态，因此**无 mutex/atomic 临界区**。
- goroutine 生命周期由各后端 server 决定（见 grpc-server/http-server 叶子）；
  本叶子只提供 context 存取原语，不创建/管理 goroutine。
- `context.Context` 传递链贯穿：挂载点（server 拦截器 / client 调用前）→ 中间件 → 业务 handler，
  超时与取消随请求 ctx 自然传播。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `transport/transport.go`：`Server`/`Endpointer`/`Header`/`Transporter`/`Kind` 接口与枚举、
  4 个 context 存取函数。
- `transport/grpc/transport.go`：gRPC 侧 Transporter 实现与 headerCarrier。
- `transport/http/transport.go`：HTTP 侧 Transporter/ResponseTransporter 实现与辅助函数。

**Out-of-Scope（不在本仓库源码内）**
- 底层 gRPC 运行时（`google.golang.org/grpc`）与 `metadata.MD` 实现——第三方依赖。
- 底层 HTTP 运行时（标准库 `net/http`）与 `http.Header` 实现——第三方依赖。
- 各接口的**具体实现行为**（server 怎么 Start、client 怎么 Dial）分别属于 grpc-server、
  grpc-client、http-server、http-client 叶子，本文不展开。
- 中间件如何消费 Transporter（logging/metadata/selector）属于 middleware 域叶子。

## 8. 与相邻子系统交互

- **上游（App 生命周期）**：根包 `app.go` 持有一组 `Server`（本叶子 `Server` 接口），
  用 errgroup 并行 `Start`/`Stop`；App 不关心是 gRPC 还是 HTTP。
- **下游（具体传输后端）**：本叶子定义接口，`transport/grpc`、`transport/http` 各包实现。
- **横向（中间件域）**：中间件通过 `FromServerContext`/`FromClientContext` 读取 Transporter，
  实现与协议无关的日志、元数据透传、节点选择。
- **横向（注册发现）**：`Endpointer` 接口的 `Endpoint()` 被 registry 域调用以注册实例。

## 9. 语言专项适配口径（Go）

- **并发模型**：本叶子无 goroutine、无 channel、无锁；并发安全完全依赖 Go `context.Context`
  的不可变值语义。context key 用未导出空结构体避免碰撞。
- **控制器模式**：非 K8s Reconciler 场景，不适用。
- **多二进制与部署边界**：本叶子属于主库 `github.com/go-kratos/kratos/v3` 运行时包，
  不对应任何 `cmd/` 二进制入口；三个 cmd 脚手架另有独立 go.mod。
- **internal 边界与依赖方向**：本包为对外公开 API，依赖方向为"下游实现本接口、横向消费本接口"，
  不反向依赖业务；`transport/grpc`、`transport/http` import `transport`，依赖方向单向清晰，无环。
- **接口定义位置（依赖倒置）**：接口定义在消费方附近的抽象包，实现方（grpc/http）与
  消费方（middleware）均依赖抽象而非具体，符合依赖倒置。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 传输抽象分层与 context 挂载图 | `transport-abstraction-architecture.html` | architecture | showcase |

- JSON IR 源文件：`json/transport-abstraction-architecture.json`。
- 本叶子**不补时序图**：context 挂载/读取的时序已在第 3 节文字化（调用链 A/B/C），
  且本质是接口读写而非多参与者消息交互，补时序图增益有限。
