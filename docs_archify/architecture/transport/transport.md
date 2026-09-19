# 传输层（transport）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 域职责

transport 域是 kratos 框架的**通信层**，向上为 App 生命周期提供统一的 `Server`/`Endpointer`
抽象，向下屏蔽 gRPC 与 HTTP 两种协议差异。核心职责：

- **协议无关抽象**：`transport.Transporter`/`Header`/`Kind` 统一描述一次请求的传输侧视图，
  并通过 `context` 在 server/client 两端挂载与读取（见 `transport-abstraction`）。
- **服务端**：gRPC 与 HTTP 各自包装 `*grpc.Server`/`*http.Server`，提供生命周期、拦截器链、
  请求挂载与优雅停止。
- **客户端**：gRPC 与 HTTP 各自封装连接构造、调用、负载均衡选节点与服务发现 watch。
- **编解码与流式**：HTTP 层提供请求绑定、Content-Type 协商编解码、错误编码、SSE/WebSocket 流式。

域内共享机制：所有 server 实现 `transport.Server{Start,Stop}` 与 `transport.Endpointer.Endpoint()`；
所有 client/server 拦截器都用 `transport.NewServerContext`/`NewClientContext` 挂载 Transporter，
使中间件与协议解耦。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| transport-abstraction | [transport-abstraction.md](transport-abstraction/transport-abstraction.md) | [架构图](transport-abstraction/transport-abstraction-architecture.html) | — | 协议无关接口与 context 挂载契约 |
| grpc-server | [grpc-server.md](grpc-server/grpc-server.md) | [架构图](grpc-server/grpc-server-architecture.html) | [时序图](grpc-server/grpc-server-sequence.html) | gRPC 服务端包装与一元/流拦截器 |
| grpc-client | [grpc-client.md](grpc-client/grpc-client.md) | [架构图](grpc-client/grpc-client-architecture.html) | [数据流图](grpc-client/grpc-client-dataflow.html) | gRPC 客户端、balancer 与 resolver |
| http-server | [http-server.md](http-server/http-server.md) | [架构图](http-server/http-server-architecture.html) | [时序图](http-server/http-server-sequence.html) | HTTP 服务端、mux 路由与请求 filter |
| http-client | [http-client.md](http-client/http-client.md) | [架构图](http-client/http-client-architecture.html) | [时序图](http-client/http-client-sequence.html) | HTTP 客户端、CallOption 与 resolver |
| http-binding-codec | [http-binding-codec.md](http-binding-codec/http-binding-codec.md) | [架构图](http-binding-codec/http-binding-codec-architecture.html) | — | HTTP 绑定编解码、错误/状态码、流式 |

## 3. 域级机制细节

- **统一 Transporter 挂载**：gRPC 在 `interceptor.go`、HTTP 在 `server.go:filter()` 中构造 `Transport`
  并 `NewServerContext`；客户端在 `client.go` 中 `NewClientContext`。中间件经
  `FromServerContext`/`FromClientContext` 读取 `Kind()/Endpoint()/Operation()/RequestHeader()`。
- **生命周期对称**：gRPC 用 `GracefulStop` goroutine + ctx.Done 强制 Stop；HTTP 用 `Shutdown` +
  `Close` 兜底；两者都实现 `transport.Server`，被 App 用 errgroup 并行 Start。
- **服务发现对称**：gRPC resolver 与 HTTP resolver 都基于 `registry.Watcher` 长循环监听，
  出错退避 1s，经 subset 一致性哈希子集过滤后 Apply 节点表；选节点失败返回 NODE_NOT_FOUND。
- **编解码自注册**：transport 包 blank import form/json/proto/protojson/xml/yaml，
  经 `encoding.GetCodec(name)` 按 Content-Type 选择。

## 4. 域级图

本域未单独绘制域级架构图；各叶子架构图与时序/数据流图已覆盖组件与调用关系。
