# HTTP 服务端（http-server）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文只展开 HTTP **服务端**包装、mux 路由与请求 filter；HTTP 客户端见 `../http-client/`，
> 绑定编解码见 `../http-binding-codec/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 服务端包装 `Server` | 内嵌 `*http.Server`，实现 `transport.Server`/`Endpointer`/`http.Handler` | `transport/http/server.go:151` |
| 选项构造 `NewServer` | functional options 组装网络/地址/超时/编解码/过滤器/路由 | `transport/http/server.go:172` |
| 请求 filter | mux 中间件：注入超时、构造 Transport 并挂入 ctx | `transport/http/server.go:267` |
| 路由注册 | `Route/Handle/HandleFunc/HandlePrefix/HandleHeader` | `transport/http/server.go:238` |
| 路由组 `Router.Group` | 嵌套前缀与过滤器链 | `transport/http/router.go:37` |
| 方法快捷注册 | GET/POST/PUT/PATCH/DELETE 等 | `transport/http/router.go:62` |
| 路由遍历 | `WalkRoute/WalkHandle` 遍历路由树 | `transport/http/server.go:210` |
| 路径构造 `BuildPath` | 按路径模板 + 消息生成 URL 与查询参数 | `transport/http/path.go:38` |
| 生命周期 Start/Stop | 监听、Serve/ServeTLS、优雅 Shutdown | `transport/http/server.go:317` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Server` struct | `transport/http/server.go:151` | 内嵌 `*http.Server`；持有 router、两个 Decoder/Encoder/ErrorEncoder、filters、middleware matcher |
| `ServerOption` func | `transport/http/server.go:29` | functional option |
| `Router` struct | `transport/http/router.go:21` | 前缀 + srv 引用 + 继承的 filters |
| `HandlerFunc` | `transport/http/router.go:18` | `func(Context) error`，业务 handler 签名 |
| `wrapper`（见 context.go） | `transport/http/context.go:61` | 实现 `Context` 接口，桥接业务 handler 与 mux |
| `DecodeRequestFunc`/`EncodeResponseFunc`/`EncodeErrorFunc` | 由 binding/codec 定义 | 请求解码/响应编码/错误编码函数类型 |
| `BuildPath` | `transport/http/path.go:38` | 客户端按模板拼路径 |

**扩展点**：`RequestDecoder`/`ResponseEncoder`/`ErrorEncoder`（`server.go:88`/`95`/`102`）允许替换
默认编解码；`Filter(filters...)` 注入标准 `FilterFunc` 中间件；`Use(selector, m...)` 按操作选择器
挂业务中间件。

## 3. 关键调用链

**调用链 A：服务端启动**
1. App 调 `Start(ctx)`（`server.go:317`）；
2. `listenAndEndpoint()`（`server.go:350`）在 `s.lis == nil` 时 `net.Listen(s.network, s.address)`（默认 tcp+:0），
   用 `host.Extract` 取地址、`endpoint.NewEndpoint(endpoint.Scheme("http", ...))` 生成 `http(s)://` URL；
3. `s.BaseContext = func(net.Listener) context.Context { return ctx }`（`server.go:321`）使每个连接继承 App ctx；
4. 有 tlsConf 则 `ServeTLS` 否则 `Serve`；`http.ErrServerClosed` 视为正常退出（`server.go:331`）。

**调用链 B：请求经 filter 进入路由**
1. 标准库把请求交给 `FilterChain(filters...)(srv.router)` 包装的 handler；
2. `Server.filter()`（`server.go:267`）：`s.timeout > 0` 时 `context.WithTimeout`，否则 `WithCancel`（`server.go:274-278`）；
3. 用 `mux.CurrentRoute(req)` 取 pathTemplate（把 `/path/123` 归一为 `/path/{id}`，`server.go:282`）；
4. 构造 `Transport{operation:pathTemplate, reqHeader, replyHeader, request, response}`，
   `tr.request = req.WithContext(transport.NewServerContext(ctx, tr))`（`server.go:298`）；
5. `next.ServeHTTP(w, tr.request)` 进入 mux 路由匹配到具体 handler。

**调用链 C：路由 handler 执行**
1. `Router.Handle`（`router.go:45`）包装：构造 `wrapper{router:r}`、`ctx.Reset(res, req)`；
2. 调业务 `h(ctx)`；若返回 error，`r.srv.ene(res, req, err)` 走错误编码器（`router.go:49-50`）；
3. 业务内通过 `ctx.Middleware(...)`（`context.go:93`）按 operation 匹配中间件链。

## 4. 配置项

| option / 字段 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `Network` | `tcp` | 监听网络 | `server.go:32` |
| `Address` | `:0` | 监听地址 | `server.go:39` |
| `Timeout(d)` | `1s` | 请求超时，>0 生效；否则 WithCancel | `server.go:53` |
| `Middleware(m...)` | 空 | 业务中间件（matcher） | `server.go:60` |
| `Filter(f...)` | 空 | HTTP FilterFunc | `server.go:67` |
| `RequestVars/Query/BodyDecoder` | Default* | 三类请求解码器 | `server.go:74/81/88` |
| `ResponseEncoder`/`ErrorEncoder` | Default* | 响应/错误编码器 | `server.go:95/102` |
| `TLSConfig` | 无 | TLS 配置 | `server.go:109` |
| `StrictSlash` | `true` | mux 严格斜杠重定向 | `server.go:118` |
| `PathPrefix(p)` | 无 | 替换为子路由 | `server.go:132` |
| `NotFoundHandler`/`MethodNotAllowedHandler` | `http.DefaultServeMux` | 兜底处理 | `server.go:138/144` |

## 5. 错误与重试语义

- `listenAndEndpoint` 监听失败存 `s.err` 并返回；重复调用短路不重报。
- **不做请求级重试**；超时由 `context.WithTimeout` 控制，业务 ctx 取消后中断。
- 业务 `h(ctx)` 返回 error 时由 `ene`（ErrorEncoder）转成 HTTP 响应，本层不重试。
- `Stop` 用 `s.Shutdown(ctx)` 优雅停止；若 `ctx.Err() != nil`（超时）则 `s.Close()` 强制关闭并告警
  （`server.go:340-346`）。
- `Serve` 返回 `http.ErrServerClosed` 视为正常关闭（`server.go:331`），其余错误上抛 App。

## 6. 并发细节

- **goroutine 模型**：标准库 `http.Server` 每连接/请求一个 goroutine；`BaseContext` 把 App ctx 注入连接基 ctx。
- **超时传播**：每个请求在 `filter()` 中独立 `WithTimeout`/`WithCancel`，`defer cancel()` 释放，
  无跨请求共享。
- **wrapper 复用**：`ctx.Reset(res, req)`（`context.go:154`）允许 wrapper 对象在请求间重置复用，
  避免每请求分配。
- **路由并发**：mux 路由树在 `NewServer` 构造期一次性注册，运行期只读；注册与服务不并发。
- **context 传递链**：req ctx → WithTimeout → NewServerContext → 中间件 → 业务 wrapper → handler。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `transport/http/server.go`：Server 包装、filter、Start/Stop/Endpoint、路由注册。
- `transport/http/router.go`：Router/Group/方法注册。
- `transport/http/path.go`：BuildPath 路径模板构造。
- `transport/http/context.go`：Context wrapper（见 binding-codec 叶子详述）。

**Out-of-Scope（不在本仓库源码内）**
- 标准库 `net/http` 与 gorilla/mux 路由实现——第三方依赖。
- 请求解码/响应编码具体算法——见 http-binding-codec 叶子。
- 中间件链具体实现——middleware 域。

## 8. 与相邻子系统交互

- **上游（App 生命周期）**：App 经 `transport.Server` 接口 Start/Stop 调度。
- **下游（标准库 HTTP + mux）**：`*http.Server` 与 `*mux.Router` 承接实际服务。
- **横向（transport 抽象）**：filter 用 `transport.NewServerContext` 挂 Transporter。
- **横向（中间件域）**：`wrapper.Middleware` 用 `middleware.Match(operation)` 选择中间件。
- **横向（注册发现）**：`Endpoint()` 供 registry 注册。

## 9. 语言专项适配口径（Go）

- **并发模型**：复用标准库每请求 goroutine；`BaseContext` 注入 App ctx 实现优雅停止传播；
  wrapper `Reset` 复用对象。
- **控制器模式**：请求驱动，非 Reconciler。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：`transport/http` 单向依赖 `internal/{endpoint,host,matcher}`、
  `middleware`、`transport`、`log`；依赖 gorilla/mux 作为路由库。
- **可观测性边界**：`log.Info/Warn` 记录监听/停止；错误经 ErrorEncoder 输出，otel 在 contrib。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| HTTP 服务端结构与请求链图 | `http-server-architecture.html` | architecture | showcase |
| 请求经 filter 到 handler 时序图 | `http-server-sequence.html` | sequence | showcase |

- JSON IR 源：`json/http-server-architecture.json`、`json/http-server-sequence.json`。
- 本叶子**不补数据流图**：请求经 filter→路由→handler 是调用链而非管道血缘，用 sequence 表达。
