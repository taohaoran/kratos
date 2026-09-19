# HTTP 客户端（http-client）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文只展开 HTTP **客户端**调用、CallOption 与 resolver；HTTP 服务端见 `../http-server/`，
> 编解码见 `../http-binding-codec/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 客户端构造 `NewClient` | options 组装超时/编解码/transport/发现/中间件 | `transport/http/client.go:162` |
| 调用 `Invoke` | 编码请求体、建请求、挂 Transporter、走中间件与节点选择 | `transport/http/client.go:212` |
| 原生 `Do` | 直接发送 `*http.Request` 并解码 | `transport/http/client.go:288` |
| 节点选择 `do` | 有 resolver 时选节点、改写 URL.Host，调用后反馈 done | `transport/http/client.go:299` |
| 调用选项 `CallOption` | before/after 两阶段配置（ContentType/Accept/Operation/Header） | `transport/http/calloption.go:16` |
| 服务发现 resolver | 基于 `registry.Watcher` 长监听，经 subset 过滤后 Apply 节点表 | `transport/http/resolver.go:45` |
| 目标解析 `parseTarget` | 解析 endpoint 为 Target（scheme/authority） | `transport/http/resolver.go:26` |
| 默认编解码 | 请求编码/响应解码/错误解码/CodecForResponse | `transport/http/client.go:346` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `Client` struct | `transport/http/client.go:152` | 持有 opts、target、resolver、`*http.Client`、selector |
| `clientOptions` | `transport/http/client.go:42` | 聚合全部客户端配置 |
| `EncodeRequestFunc`/`DecodeResponseFunc`/`DecodeErrorFunc` | `transport/http/client.go:33-36` | 请求/响应/错误编解码函数类型 |
| `CallOption` interface | `transport/http/calloption.go:16` | before/after 两阶段调用配置 |
| `callInfo` / `csAttempt` | `transport/http/calloption.go:26`/`:43` | 单次调用信息与单次响应快照 |
| `Target` | `transport/http/resolver.go:20` | scheme/authority/endpoint |
| `resolver` | `transport/http/resolver.go:45` | watcher + rebalancer + subset |

**扩展点**：`WithRequestEncoder`/`WithResponseDecoder`/`WithErrorDecoder` 可替换默认编解码；
`CallOption` 接口允许自定义 before/after 钩子（如提取响应头、设置 operation）。

## 3. 关键调用链

**调用链 A：客户端构造**
1. `NewClient(ctx, opts...)`（`client.go:162`）设默认：timeout=2000ms、`http.DefaultTransport`、
   subsetSize=25、三个默认编解码；
2. 有 tlsConf 时 clone `http.Transport` 并注入 TLSClientConfig（`client.go:175-180`）；
3. `parseTarget` 解析 endpoint（`resolver.go:26`）；`selector.GlobalSelector().Build()` 建选择器；
4. 若配置 `discovery` 且 scheme 为 `discovery://`，`newResolver`（`resolver.go:56`）；否则校验 host:port。

**调用链 B：Invoke 调用**
1. `Invoke(ctx, method, path, args, reply, opts...)`（`client.go:212`）：`defaultCallInfo(path)`，
   各 `CallOption.before(&c)` 生效（`client.go:217-222`）；
2. `client.opts.encoder` 编码 args 为 body，`http.NewRequest` 构造请求，设置 Content-Type/Accept/User-Agent；
3. `transport.NewClientContext(ctx, &Transport{...})`（`client.go:249`）挂载客户端 Transporter；
4. `invoke`（`client.go:259`）：`selector.NewPeerContext` 注入 peer，`middleware.Chain` 链化中间件，`h(ctx,args)`；
5. 内层 `h` 调 `client.do`，成功后各 `CallOption.after` 执行，`decoder` 解响应体（`client.go:260-276`）。

**调用链 C：do 选节点发送**
1. 若有 resolver，`client.selector.Select(ctx, WithNodeFilter(...))` 选节点；失败返回
   `errors.ServiceUnavailable("NODE_NOT_FOUND")`（`client.go:306-307`）；
2. 按 insecure 设 scheme，`req.URL.Host = node.Address()`、`req.Host = node.Address()`（`client.go:309-315`）；
3. `client.cc.Do(req)` 发送；成功后把 `resp.Header` 写回 `Transport.replyHeader`，
   `errorDecoder` 判定非 2xx 转错误（`client.go:317-327`）；
4. `done(ctx, DoneInfo{Err})` 回调选择器反馈结果（`client.go:328-329`）。

**调用链 D：发现 watch**
1. `newResolver` 先 `discovery.Watch`；`block=true` 时用 done channel 等首次 `update` 成功
   （`resolver.go:72-104`）；
2. watch goroutine 循环 `watcher.Next()`；非 `context.Canceled` 错误时 `log.Error`+`sleep 1s` 重试
   （`resolver.go:105-118`）；
3. `update`（`resolver.go:122`）解析 http 端点、subset 过滤、建节点，空节点拒绝写入，
   否则 `rebalancer.Apply(nodes)`。

## 4. 配置项

| option | 默认 | 行为 | 位置 |
|------|------|------|------|
| `WithEndpoint` | 空 | 目标地址 | `client.go:96` |
| `WithTimeout` | 2000ms | 请求超时（`http.Client.Timeout`） | `client.go:75` |
| `WithTransport` | `http.DefaultTransport` | 自定义 RoundTripper | `client.go:68` |
| `WithUserAgent` | 空 | User-Agent 头 | `client.go:82` |
| `WithMiddleware` | 空 | 客户端中间件 | `client.go:89` |
| `WithRequestEncoder/ResponseDecoder/ErrorDecoder` | Default* | 三类编解码 | `client.go:103/110/117` |
| `WithDiscovery` | 空 | 接入 registry.Discovery | `client.go:124` |
| `WithNodeFilter` | 空 | 节点过滤 | `client.go:131` |
| `WithBlock` | 关 | 阻塞等首次发现结果 | `client.go:138` |
| `WithSubset` | 25 | 子集大小，0 禁用 | `client.go:61` |
| `WithTLSConfig` | 无（insecure） | TLS 配置 | `client.go:145` |

## 5. 错误与重试语义

- 选节点失败返回 `errors.ServiceUnavailable("NODE_NOT_FOUND", ...)`（`client.go:307`）。
- `errorDecoder` 对非 2xx 响应读 body 解码为 `*errors.Error`，StatusCode 写入 `e.Code`；
  解码失败则包成 `errors.Newf(...).WithCause(err)`（`client.go:378-391`）。
- **不做调用级重试**；重试/熔断由客户端中间件承担。
- watch 出错退避 1s 重试，仅 `context.Canceled` 退出；`block` 模式下 ctx 超时则停 watcher 并返回 ctx 错误。
- `update` 解析端点失败单条跳过；空节点表**拒绝写入**（保留旧表），避免无节点可用。

## 6. 并发细节

- **goroutine 启停边界**：`newResolver` 起 watch goroutine 阻塞 `watcher.Next()`；
  `block` 模式另起 goroutine 等首次结果，用 done channel + ctx.Done select；`Close` 停 watcher。
- **请求并发**：每次 Invoke 独立构造 Transport、注入 peer，中间件链在调用 goroutine 内执行。
- **selector 并发**：`rebalancer.Apply(nodes)` 在 watch goroutine 更新节点表；
  RPC 并发 `Select` 读取，由 selector 内部保证安全。
- **临界区**：`Client` 字段构造期写定；`callInfo` 为单次调用局部变量。
- **context 传递链**：调用 ctx → NewClientContext → NewPeerContext → WithTimeout（http.Client.Timeout）→ 中间件 → do。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `transport/http/client.go`：Client、Invoke/Do、默认编解码。
- `transport/http/calloption.go`：CallOption 与 callInfo。
- `transport/http/resolver.go`：resolver/watch/update。
- `transport/http/stream.go`：流式客户端（本叶子简述，详见 binding-codec 叶子）。

**Out-of-Scope（不在本仓库源码内）**
- 标准库 `net/http` Client/Transport 行为——第三方依赖。
- `registry.Discovery` 具体实现——在 contrib 包。
- selector 算法与 Rebalancer——见 selector 域叶子。

## 8. 与相邻子系统交互

- **上游（业务/生成代码）**：proto 生成的 http client stub 调 `Invoke`/`Do`。
- **下游（标准库 HTTP）**：`*http.Client` 实际发请求。
- **横向（registry/selector）**：resolver 用 Discovery Watch，do 用 selector.Select 选节点。
- **横向（中间件域）**：invoke 链化客户端中间件。
- **横向（encoding 包）**：DefaultRequestEncoder 经 `encoding.GetCodec(name)` 取编解码器。

## 9. 语言专项适配口径（Go）

- **并发模型**：watch goroutine 错误退避重试；block 模式 done channel 同步首次发现；
  RPC 无共享状态。
- **控制器模式**：discovery watch 是 watch→update→rebalancer 的事件驱动模型，
  与 grpc-client resolver 同构，非 Reconciler。
- **多二进制与部署边界**：属主库运行时包。
- **internal 边界与依赖方向**：`transport/http` 依赖 `internal/{endpoint,subset,host,httputil}`、
  `registry`、`selector`、`encoding`、`errors`，单向清晰。
- **可观测性边界**：watch/解析失败用 `log.Error/Warn`；错误统一为 `*errors.Error`，otel 在 contrib。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| HTTP 客户端调用与选节点架构图 | `http-client-architecture.html` | architecture | showcase |
| Invoke 调用时序图 | `http-client-sequence.html` | sequence | showcase |

- JSON IR 源：`json/http-client-architecture.json`、`json/http-client-sequence.json`。
- 本叶子补 **sequence** 表达 Invoke 调用链；发现 watch 数据流与 grpc-client 同构，不重复画 dataflow。
