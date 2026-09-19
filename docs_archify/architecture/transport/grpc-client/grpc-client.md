# gRPC 客户端（grpc-client）

> 本文是 `transport` 域下的叶子子系统文档。域级总览见 `../transport.md`。
> 本文只展开 gRPC **客户端**连接构造、客户端拦截器、负载均衡器与 resolver；gRPC 服务端见 `../grpc-server/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 连接构造 `NewClient` | functional options 组装 endpoint/超时/中间件/TLS/发现，返回 `*grpc.ClientConn` | `transport/grpc/client.go:140` |
| 一元客户端拦截器 | 挂载客户端 Transporter、注入超时、把 reqHeader 写出入站 metadata、串中间件 | `transport/grpc/client.go:200` |
| 流式客户端拦截器 | 包装 ClientStream，对每条 Send/Recv 串中间件 | `transport/grpc/client.go:282` |
| 全局选择器默认 | 无全局选择器时默认装 WRR 负载均衡 | `transport/grpc/client.go:26` |
| 自定义 balancer | 名为 `selector` 的 gRPC balancer，桥接 kratos selector | `transport/grpc/balancer.go:14` |
| 节点选择 Pick | 从 ctx 取 NodeFilter，调 selector.Select 选节点并回传 Done 回调 | `transport/grpc/balancer.go:64` |
| direct resolver | scheme `direct`，静态逗号分隔地址列表一次性解析 | `transport/grpc/resolver/direct/builder.go` |
| discovery resolver | scheme `discovery`，基于 registry.Watcher 长循环监听并推送地址 | `transport/grpc/resolver/discovery/resolver.go` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|------|------|------|
| `clientOptions` struct | `transport/grpc/client.go:123` | 聚合 endpoint/subsetSize/tls/timeout/discovery/middleware/拦截器/balancerName/filters |
| `unaryClientInterceptor` | `transport/grpc/client.go:200` | 返回一元客户端拦截器闭包 |
| `streamClientInterceptor` | `transport/grpc/client.go:282` | 返回流式客户端拦截器闭包 |
| `wrappedClientStream` | `transport/grpc/client.go:236` | 包装 `grpc.ClientStream`，重写 Context 与 Send/Recv |
| `balancerBuilder` / `balancerPicker` | `transport/grpc/balancer.go:33`/`:59` | 实现 gRPC `base.PickerBuilder` 与 `balancer.Picker` |
| `grpcNode` | `transport/grpc/balancer.go:102` | 包装 `selector.Node` + `balancer.SubConn` |
| `directBuilder` | `transport/grpc/resolver/direct/builder.go` | gRPC resolver.Builder，scheme `direct` |
| `discoveryResolver` | `transport/grpc/resolver/discovery/resolver.go` | 基于 `registry.Watcher` 的动态地址解析 |

**扩展点**：`WithNodeFilter(filters...)` 注入 `selector.NodeFilter`，在 Pick 时经 `Transport.NodeFilters()`
传入选择器（`client.go:107`、`balancer.go:66`），是客户端节点过滤的 seam。

## 3. 关键调用链

**调用链 A：客户端连接构造**
1. `NewClient(ctx, opts...)`（`client.go:140`）设默认：timeout=2000ms、balancerName=`"selector"`、
   subsetSize=25、healthCheckConfig 含 healthCheck；
2. 组装 grpcOpts：`grpc.WithDefaultServiceConfig` 注入 `loadBalancingConfig` 与 healthCheck，
   `WithChainUnaryInterceptor`/`WithChainStreamInterceptor` 链化拦截器（`client.go:167-172`）；
3. 若配置了 `discovery`，`grpc.WithResolvers(discovery.NewBuilder(...))`（`client.go:174-183`）；
4. 按 tlsConf 选择 insecure/TLS 凭证，`grpc.NewClient(options.endpoint, ...)` 后 `conn.Connect()`（`client.go:192-196`）。

**调用链 B：一元调用**
1. 拦截器构造 `Transport{endpoint:cc.Target(), operation:method, nodeFilters:filters}` 并
   `transport.NewClientContext(ctx, tr)`（`client.go:202`）；
2. `WithTimeout` 注入客户端超时（`client.go:210`）；
3. 内层 `h` 把 reqHeader 的键值 `AppendToOutgoingContext` 写出入站 metadata 后调 `invoker`（`client.go:213-223`）；
4. `middleware.Chain(ms...)(h)` 链化用户中间件，`selector.NewPeerContext` 注入 peer，`h(ctx,req)` 执行（`client.go:225-230`）。

**调用链 C：负载均衡选节点**
1. gRPC 运行时在 `balancerPicker.Pick`（`balancer.go:64`）从 `transport.FromClientContext(info.Ctx)`
   取 `*Transport` 与 `NodeFilters()`（`balancer.go:66-70`）；
2. `p.selector.Select(ctx, WithNodeFilter(filters...))` 选出节点与 done 回调（`balancer.go:72`）；
3. 返回 `SubConn` 与 `Done` 闭包——RPC 结束后回调 `done(ctx, selector.DoneInfo{...})` 反馈结果（`balancer.go:77-87`）。

**调用链 D：服务发现 watch**
1. `discoveryResolver.watch()`（`resolver.go`）循环 `r.w.Next()`；
2. 出错且非 `context.Canceled` 时 `log.Error` + `time.Sleep(1s)` 后重试（`resolver.go` watch 段）；
3. 成功则 `r.update(ins)`，用 `endpoint.ParseEndpoint` 解析 `grpc://` 端点，经 subset 过滤后 `cc.UpdateState`。

## 4. 配置项

| option | 默认 | 行为 | 位置 |
|------|------|------|------|
| `WithEndpoint(endpoint)` | 空 | 目标地址 | `client.go:36` |
| `WithSubset(size)` | 25 | 发现客户端一致性哈希子集大小，0 禁用 | `client.go:44` |
| `WithTimeout(d)` | 2000ms | 一元调用超时，>0 生效 | `client.go:51` |
| `WithMiddleware(m...)` | 空 | 一元客户端中间件 | `client.go:58` |
| `WithStreamMiddleware(m...)` | 空 | 流式客户端中间件 | `client.go:65` |
| `WithDiscovery(d)` | 空 | 接入 registry.Discovery，启用 discovery resolver | `client.go:72` |
| `WithTLSConfig(c)` | 无（insecure） | 配置 TLS 凭证 | `client.go:79` |
| `WithUnaryInterceptor/StreamInterceptor` | 空 | 追加 gRPC 原生拦截器 | `client.go:86` |
| `WithNodeFilter(filters...)` | 空 | 节点过滤 | `client.go:107` |
| `WithHealthCheck(bool)` | 开 | 关闭则移除 healthCheckConfig | `client.go:114` |
| discovery builder `timeout` | 10s | 创建 watcher 超时 | `discovery/builder.go` |

## 5. 错误与重试语义

- `NewClient` 开始先 `ctx.Err()` 校验，ctx 已取消则直接返回错误（`client.go:150`）。
- `grpc.NewClient` 失败返回错误；本叶子**不做调用级重试**，重试/熔断由客户端中间件
  （circuitbreaker，见 middleware 域）承担。
- discovery watch 出错时**不退出**：记录错误后 sleep 1s 继续 `Next()`，仅 `context.Canceled` 才退出循环
  （`resolver.go` watch 段）——这是带退避的 watch 重试。
- balancer 在 `ReadySCs` 为空时返回 `base.NewErrPicker(ErrNoSubConnAvailable)`（`balancer.go:41`），
  gRPC 运行时会阻塞 RPC 直到新 picker 通过 `UpdateState()` 到来。
- `wrappedClientStream.SendMsg/RecvMsg` 无 Transporter 时返回包装错误（`client.go:253`）。

## 6. 并发细节

- **goroutine 启停边界**：`discoveryResolver.watch()` 在其 goroutine 中阻塞 `w.Next()`；
  用 `r.ctx.Done()` 退出，Close 时 cancel ctx，无泄漏。
- **RPC 并发**：每个一元调用在其 goroutine 内构造独立 `Transport`、注入 peer，无共享可变状态；
  `selector.Select` 内部有自己的并发控制（见 selector 域叶子）。
- **balancer Picker**：gRPC 运行时在 RPC 并发时调用 `Pick`；`p.selector` 节点表在 `Build` 时
  `Apply(nodes)` 一次性建立，运行期只读。
- **channel 通信**：`w.Next()` 是 registry.Watcher 的阻塞接口，watch goroutine 与主流程解耦。
- **context 传递链**：调用 ctx → NewClientContext → WithTimeout → 中间件链 → invoker，
  超时/取消沿链传播并传递给 gRPC 运行时。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `transport/grpc/client.go`：NewClient、一元/流客户端拦截器、wrappedClientStream。
- `transport/grpc/balancer.go`：selector balancer 与 picker。
- `transport/grpc/resolver/direct/`、`transport/grpc/resolver/discovery/`：两套 resolver。

**Out-of-Scope（不在本仓库源码内）**
- gRPC 运行时（`google.golang.org/grpc`）：连接、RPC 调度、服务端配置解析——第三方依赖。
- `registry.Discovery` 的具体实现（etcd/consul/k8s 等）——在 contrib 包，不在本仓库主源码。
- selector 算法（WRR/P2C/EWMA）——见 selector 域叶子。
- 节点过滤中间件实现——见 middleware 域 selector 叶子。

## 8. 与相邻子系统交互

- **上游（业务/生成代码）**：proto 生成的 client stub 调用 `NewClient` 得到的 `*grpc.ClientConn`。
- **下游（gRPC 运行时）**：`grpc.NewClient`、balancer、resolver 均对接 gRPC 官方扩展点。
- **横向（registry 域）**：`WithDiscovery` 接收 `registry.Discovery`，discovery resolver 用其 Watch。
- **横向（selector 域）**：balancer 桥接 kratos `selector.Selector` 选择节点。
- **横向（中间件域）**：客户端拦截器链化用户中间件（logging/circuitbreaker 等）。

## 9. 语言专项适配口径（Go）

- **并发模型**：watch goroutine 用 ctx.Done 退出、错误退避 1s 重试；RPC 无共享状态。
- **控制器模式**：discovery watch 是"watch → update → picker"的事件驱动模型，
  类似 informer 的 watch→缓存→通知，但无 workqueue/Reconcile，差异在于地址更新直接推给 gRPC。
- **多二进制与部署边界**：本叶子属主库运行时包。
- **internal 边界与依赖方向**：`transport/grpc` 依赖 `internal/{endpoint,subset,matcher,log}`、
  `registry`、`selector`、`transport`，单向清晰；resolver 通过 `resolver.Register`/`balancer.Register`
  自注册到 gRPC。
- **可观测性边界**：watch 失败用 `log.Error`；调用级错误透传，otel 在 contrib。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| gRPC 客户端构造与选节点架构图 | `grpc-client-architecture.html` | architecture | showcase |
| 服务发现 watch 数据流图 | `grpc-client-dataflow.html` | dataflow | showcase |

- JSON IR 源：`json/grpc-client-architecture.json`、`json/grpc-client-dataflow.json`。
- 本叶子补 **dataflow** 而非 sequence：discovery watch 是"w.Next → update → subset → cc.UpdateState"
  的地址管道，用 dataflow 表达更贴切；一元调用时序与服务端对称，不重复画。
