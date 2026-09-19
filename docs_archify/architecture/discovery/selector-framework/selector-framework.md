# 选择器框架（selector-framework）

> 本文是 `discovery` 域下的叶子子系统文档。域级总览见 `../discovery.md`。
> 本文展开 `selector/` 包的接口抽象与默认组合实现；具体负载均衡算法见 `selector-algorithms` 叶子。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 选择器接口 | `Selector{Rebalancer, Select}` | `selector/selector.go:13` |
| 重平衡接口 | `Rebalancer.Apply(nodes)` | `selector/selector.go:22` |
| 节点接口 | `Node{Scheme/Address/ServiceName/...}` | `selector/selector.go:33` |
| 负载均衡接口 | `Balancer.Pick(nodes)` / `WeightedNode` | `selector/balancer.go:9,19` |
| 默认组合选择器 | `Default = WeightedNodeBuilder + Balancer` | `selector/default_selector.go:14` |
| 默认节点 | `DefaultNode` + `NewNode(scheme,addr,ins)` | `selector/default_node.go:12,52` |
| 全局选择器 | `GlobalSelector`/`SetGlobalSelector`（wrapSelector） | `selector/global.go:3` |
| 节点过滤 | `NodeFilter` 函数类型 + `WithNodeFilter` | `selector/filter.go:6`、`options.go:12` |
| Peer 上下文 | `Peer` 挂进 ctx 传递选中节点 | `selector/peer.go:11` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Selector` interface | `selector.go:13` | 选节点契约；内嵌 `Rebalancer` |
| `Balancer`/`WeightedNode` | `balancer.go:9,19` | 真正的加权选择算法抽象 |
| `Default` struct | `default_selector.go:14` | 组合选择器，`nodes atomic.Value` 存 `[]WeightedNode` |
| `DefaultBuilder` | `default_selector.go:75` | 注入 NodeBuilder 与 BalancerBuilder 构造 Selector |
| `DefaultNode` | `default_node.go:12` | 从 `registry.ServiceInstance` 构建节点，解析 metadata.weight |
| `wrapSelector` | `global.go:8` | 全局 Builder 的可替换包装 |
| `DoneFunc`/`DoneInfo` | `selector.go:74,56` | RPC 完成回调与元信息 |

## 3. 关键调用链

**链路一：`Default.Select` 选节点**（`default_selector.go:22`）
1. `d.nodes.Load().([]WeightedNode)` 取当前节点切片（`default_selector.go:27`），空则 `ErrNoAvailable`。
2. 应用 `SelectOption`（`default_selector.go:31-33`）；若有 `NodeFilters`，逐个过滤并转回 `[]WeightedNode`（`default_selector.go:34-48`）。
3. 候选为空则 `ErrNoAvailable`（`default_selector.go:50-52`）。
4. `d.Balancer.Pick(ctx, candidates)` 选出 `WeightedNode` 与 `done`（`default_selector.go:53`）。
5. 若 ctx 中有 `Peer`，回填 `p.Node = wn.Raw()`（`default_selector.go:57-60`）；返回 `wn.Raw(), done, nil`。

**链路二：`Default.Apply` 节点刷新**（`default_selector.go:65`）
- 把新节点列表逐个 `NodeBuilder.Build(n)` 成 `WeightedNode`，整体 `d.nodes.Store` 替换（`default_selector.go:66-71`）。TODO 注释承认"未保留未变节点"。

**链路三：`NewNode` 从实例建节点**（`default_node.go:52`）
- 从 `ins.Name/Version/Metadata` 填充；metadata 中 `weight` 可解析为初始权重（`default_node.go:61-64`）。

## 4. 配置项

| 选项 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `GlobalSelector` | nil | 未 Set 时 `GlobalSelector()` 返回 nil | `global.go:11-16` |
| `NodeFilters` | 无 | 经 `WithNodeFilter` 注入，Select 时过滤候选 | `options.go:12` |
| `metadata["weight"]` | nil | 节点初始权重，未设由具体 WeightedNode 给默认 | `default_node.go:61` |

## 5. 错误与重试语义

- 无可用节点返回 `ErrNoAvailable = errors.ServiceUnavailable("no_available_node","")`（`selector.go:10`）。
- `Balancer.Pick` 错误直接透传（`default_selector.go:54-56`）。
- 选择器本身不重试；重试在 RPC 客户端层。
- `Default.Apply` 不区分新旧节点，整体替换——短暂窗口可能在途请求拿到旧 done。

## 6. 并发细节

- **节点存储**：`d.nodes atomic.Value`（`default_selector.go:18`），`Apply` 整体 Store、`Select` Load，无锁读。读多写少，无 RW 锁。
- **全局选择器**：`globalSelector` 包级变量，`SetGlobalSelector` 写入无锁（`global.go:19-21`）——约定初始化期设置。
- **Peer 上下文**：`peerKey{}` 经 `context.WithValue` 传递（`peer.go:17`）。
- **goroutine**：本包不创建 goroutine。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `selector/`：接口抽象、默认组合选择器、默认节点、全局注册、Peer 上下文、NodeFilter。

**Out-of-Scope（不在本仓库源码内）**
- 具体算法实现：p2c/wrr/random/direct/ewma/filter.version（见 `selector-algorithms` 叶子）。
- 客户端 resolver 如何 watch 实例并调 `Apply`——见 transport 域。
- 不做：实例来源（registry）、连接池、RPC 重试。

## 8. 与相邻子系统交互

- 上游：`transport/grpc|http/client` 启动时 `selector.SetGlobalSelector(wrr.NewBuilder())`（`transport/grpc/client.go:28`）；resolver 收到实例变更调 `Apply`。
- 本叶子 → 下游：`Balancer.Pick` 由具体算法实现（p2c/ewma、wrr/direct、random/direct）；`NodeBuilder.Build` 由 direct/ewma 实现。
- 与 `registry-interface`：`NewNode` 消费 `registry.ServiceInstance`。

## 9. 语言专项适配口径

- **并发模型**：Go 平台类，组合模式 + `atomic.Value` 无锁热替换节点表。非 K8s 控制器模式——无 informer，节点列表由外部 resolver 推入。
- **依赖倒置**：`Selector`/`Balancer`/`WeightedNodeBuilder` 均为接口，默认实现 `Default` 组合二者；具体算法通过 `DefaultBuilder` 注入。
- **internal 边界**：`selector/` 是公开包，是客户端负载均衡的扩展点；算法子包（p2c 等）也是公开包。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `selector-framework-architecture.html` | architecture | standard |

JSON IR 位于 `json/`。降 standard 原因：垂直对齐组件连线被误推断侧方向，移除低价值边并缩短标签后 standard 通过（如实披露）。本叶子不补 sequence：`Select` 为同步调用链，已在第 3 节文字化。
