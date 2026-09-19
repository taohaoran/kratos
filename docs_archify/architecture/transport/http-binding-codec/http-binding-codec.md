# HTTP 绑定编解码与流式（http-binding-codec）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文展开 HTTP 层的**请求绑定、编解码、错误编码、过滤器、重定向、状态码转换、pprof 与流式**；
> HTTP 服务端骨架见 `../http-server/`，客户端骨架见 `../http-client/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 查询/表单绑定 | bindQuery/bindForm 用 form codec 解码 url.Values | `transport/http/binding.go:12` |
| 请求变量解码 | DefaultRequestVars/Query/Body | `transport/http/codec.go:53/63/68` |
| 响应编码 | DefaultResponseEncoder（含 HttpBody/Redirector 分支） | `transport/http/codec.go:101` |
| 错误编码 | DefaultErrorEncoder（redirect 分支 + errors 序列化） | `transport/http/codec.go:133` |
| Codec 选择 | CodecForRequest 按 Content-Type/Accept 选 codec | `transport/http/codec.go:153` |
| proto 解码适配 | decodeWithCodec 处理 proto.Message 指针空值 | `transport/http/codec.go:180` |
| 过滤器链 | FilterFunc/FilterChain 反向包裹 | `transport/http/filter.go:6` |
| 重定向错误 | redirect 实现 Redirector error，NewRedirect 构造 | `transport/http/redirect.go:3` |
| 状态码转换 | HTTP code ↔ gRPC code 双向 Converter | `transport/http/status/status.go:17` |
| pprof 挂载 | NewHandler 暴露 /debug/pprof/* | `transport/http/pprof/pprof.go:9` |
| SSE/WebSocket 流 | 服务端与客户端 ServerStream/ClientStream | `transport/http/stream.go:45/57` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `DecodeRequestFunc`/`EncodeResponseFunc`/`EncodeErrorFunc` | `transport/http/codec.go:44-50` | 编解码函数类型 |
| `Redirector` interface | `transport/http/codec.go:29` | error + Redirect()(url,code) |
| `redirect` struct | `transport/http/redirect.go:3` | 重定向错误实现 |
| `FilterFunc`/`FilterChain` | `transport/http/filter.go:6/9` | 标准 HTTP 过滤器函数 |
| `status.Converter` | `transport/http/status/status.go:17` | ToGRPCCode/FromGRPCCode 双向转换 |
| `ServerStream`/`ClientStream` | `transport/http/stream.go:45/57` | 流式读写接口 |
| `serverStream` | `transport/http/stream.go:64` | 服务端流实现（SSE/WebSocket 双模式） |
| `streamMode` | `transport/http/stream.go:37` | SSE/WebSocket 模式枚举 |

**扩展点**：编解码函数类型可由 ServerOption 替换（见 http-server 叶子）；流式通过
`WithStreamBodyField` 等 option 配置。

## 3. 关键调用链

**调用链 A：请求体解码**
1. 业务 `ctx.Bind(v)` 调 `srv.decBody`（即 DefaultRequestDecoder，`codec.go:68`）；
2. 若 v 是 `*httpbody.HttpBody`，直接读 body 填入（`codec.go:69-78`）；
3. 否则 `CodecForRequest(r, "Content-Type")` 选 codec（`codec.go:79`），读全量 body 并 reset；
4. `decodeWithCodec`（`codec.go:180`）对 proto/protojson 处理空指针后 Unmarshal，
   失败包成 `errors.BadRequest("CODEC", ...)`（`codec.go:95`）。

**调用链 B：响应/错误编码**
1. 正常响应走 DefaultResponseEncoder（`codec.go:101`）：HttpBody 分支直写，Redirector 分支 302，
   否则按 Accept 选 codec Marshal 并写 Content-Type；
2. 业务返回 error 走 DefaultErrorEncoder（`codec.go:133`）：`errors.As(err, &rd)` 命中重定向则 302，
   否则 `errors.FromError(err)` 序列化、`w.WriteHeader(int(se.Code))`（`codec.go:148`）。

**调用链 C：过滤器链组装**
1. `FilterChain(filters...)`（`filter.go:9`）从后向前包裹：`next = filters[i](next)`；
2. http-server 把 `FilterChain(srv.filters...)(srv.router)` 作为 `http.Server.Handler`。

**调用链 D：流式**
1. 服务端 `NewServerSentEventServerStream`/`NewWebSocketServerStream`（`stream.go:94/107`）构造 serverStream；
2. 客户端 `Client.ServerSentEvent`/`Client.WebSocket`（`stream.go:606/669`）返回 ClientStream；
3. Send/Recv 经 marshalStreamMessage/unmarshalStreamMessage + codec 编解码。

## 4. 配置项

| 项 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `httpBodyContentType` | `application/octet-stream` | HttpBody 缺省 Content-Type | `codec.go:23` |
| `StatusConverter` | DefaultConverter | HTTP↔gRPC 码转换表 | `status/status.go:28` |
| `ClientClosed` | 499 | 非标准码（nginx）映射 gRPC Canceled | `status/status.go:13` |
| `WithStreamBodyField` | 无 | 指定流消息 body 字段 | `stream.go:87` |

本叶子无独立运行时配置；编解码选择由请求 Content-Type/Accept 头驱动。

## 5. 错误与重试语义

- 解码失败统一转 `errors.BadRequest("CODEC", ...)`（`codec.go:95`）。
- `DefaultErrorEncoder` 序列化失败时返回 500 且不写错误体（`codec.go:144`）。
- 重定向错误通过 `errors.As(err, &rd)` 识别，优先级高于普通错误序列化（`codec.go:135`）。
- 本叶子**不做重试**；流式 Send/Recv 错误直接返回，由调用方处理。

## 6. 并发细节

- 编解码函数为无状态纯函数，请求间独立，无共享状态。
- 流式：SSE/WebSocket 在长连接 goroutine 中读写；`SetReadDeadline`/`SetWriteDeadline`
  （`stream.go:151/169`）控制读写超时；`detachStreamContext`（`stream.go:141`）把流 ctx 与请求 ctx
  解耦，避免请求结束误取消流。
- 过滤器链构造期组装，运行期只读。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- binding.go、codec.go、filter.go、redirect.go、stream.go、status/、pprof/。

**Out-of-Scope（不在本仓库源码内）**
- 标准库 net/http、gorilla/mux、golang.org/x/net/websocket、google.golang.org/genproto HttpBody——第三方依赖。
- encoding 各 codec 实现——见 encoding 包。
- errors 包错误结构——见 errors 包。

## 8. 与相邻子系统交互

- **上游（http-server）**：Server 持有 decoder/encoder/errorEncoder 字段，调用本叶子函数。
- **上游（http-client）**：Client 的 DefaultRequestEncoder/Decoder/ErrorDecoder 复用本叶子。
- **横向（encoding 包）**：CodecForRequest/GetCodec 经 encoding 全局注册表取 codec。
- **横向（errors 包）**：DefaultErrorEncoder 用 errors.FromError。

## 9. 语言专项适配口径（Go）

- **并发模型**：编解码无状态；流式用 detachStreamContext 解耦请求 ctx 与长连接生命周期。
- **控制器模式**：不适用。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：`transport/http` 依赖 `internal/httputil`、`encoding`、`errors`；
  `status` 子包独立，仅依赖 gRPC codes。
- **可观测性边界**：pprof 暴露性能剖析端点（生产应谨慎）；错误统一为 `*errors.Error`。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| HTTP 编解码与绑定架构图 | `http-binding-codec-architecture.html` | architecture | standard（showcase 组件间距与标签校验多次不过，按规程降档） |

- JSON IR 源：`json/http-binding-codec-architecture.json`。
- 本叶子**不补时序/数据流图**：编解码是"选 codec→Unmarshal/Marshal"的分支逻辑，
  用架构图表达组件关系即可；流式长连接时序与 http-server 对称，不重复画。
