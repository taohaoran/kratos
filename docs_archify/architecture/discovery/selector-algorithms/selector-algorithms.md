# 负载均衡算法（selector-algorithms）

> 本文是 `discovery` 域下的叶子子系统文档。域级总览见 `../discovery.md`。
> 本文展开 `selector/` 下的三套 Balancer 实现（p2c/wrr/random）、两类 WeightedNode 实现（direct/ewma）
> 与版本过滤器 filter.version。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| P2C 均衡器 | Pick of 2 choices：随机选两节点，按权重/负载选优 | `selector/p2c/p2c.go:54` |
| P2C 探活 | 3s 未被选的较弱节点强制选一次以更新统计 | `p2c/p2c.go:15,74` |
| WRR 均衡器 | nginx 平滑加权轮询 | `selector/wrr/wrr.go:59` |
| Random 均衡器 | 均匀随机选节点 | `selector/random/random.go:33` |
| 直连节点 | `direct.Node`：静态权重（默认 100），不记录延迟 | `selector/node/direct/direct.go:21` |
| EWMA 节点 | 指数加权移动平均延迟 + 成功率动态权重 | `selector/node/ewma/node.go:27` |
| 版本过滤 | `filter.Version(v)` 按节点 Version 过滤 | `selector/filter/version.go:10` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `p2c.Balancer` | `p2c.go:34` | 持互斥锁随机源 + `picked atomic.Bool` |
| `p2c.NewBuilder` | `p2c.go:83` | 组合 `DefaultBuilder{Balancer:&Builder{}, Node:&ewma.Builder{}}` |
| `wrr.Balancer` | `wrr.go:25` | `currentWeight map[string]float64` + 节点变更清理 |
| `wrr.NewBuilder` | `wrr.go:110` | 组合 direct 节点 |
| `random.Balancer` | `random.go:25` | 无状态随机 |
| `direct.Node` | `direct.go:21` | 内嵌 `selector.Node` + `lastPick atomic.Int64` |
| `ewma.Node` | `node.go:27` | `lag/success/inflight/inflights[200]` 原子统计 |
| `filter.Version` | `version.go:10` | 返回 `NodeFilter` 闭包 |

## 3. 关键调用链

**链路一：p2c.Pick**（`p2c.go:54`）
1. 空节点 `ErrNoAvailable`；单节点直接 `Pick()`（`p2c.go:55-61`）。
2. `prePick` 在锁内随机选两个不同下标（`p2c.go:41-51`）。
3. 按 `Weight()` 大者为 `pc`、小者 `upc`（`p2c.go:66-70`）。
4. 若 `upc.PickElapsed() > forcePick(3s)` 且 `picked` 为 false，则强制选 `upc` 一次（`p2c.go:74-77`）。
5. `pc.Pick()` 返回 done（`p2c.go:78`）。

**链路二：ewma 动态权重**（`node.go:168`）
1. `Weight()` 缓存 5ms，过期才重算（`node.go:171`）。
2. `load() = sqrt(lag+5ms) * inflight`，无数据时 `penalty * inflight`（`node.go:73-90`）。
3. `Weight = health*10µs / load`（`node.go:174`）。
4. `Pick` 回调里按 `w=exp(-td/tau)` 更新 lag 与 success 移动平均（`node.go:124-163`）。

**链路三：wrr.Pick**（`wrr.go:59`）
1. 节点列表变化时清理 `currentWeight` 中失效地址（`wrr.go:68-85`）。
2. 遍历：`currentWeight[addr] += Weight()`，选累计最大者；选中者 `currentWeight -= totalWeight`（`wrr.go:87-103`）。

## 4. 配置项

| 常量/选项 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `forcePick` | 3s | p2c 对久未选节点的强制探活间隔 | `p2c.go:15` |
| `direct.defaultWeight` | 100 | 未设 InitialWeight 时的静态权重 | `direct.go:12` |
| `ewma.tau` | 600ms | EWMA 半衰期时间常数 | `node.go:16` |
| `ewma.penalty` | 100µs | 无统计数据时的滞后惩罚 | `node.go:18` |
| `metadata.weight` | — | 初始权重（见 selector-framework） | `default_node.go:61` |

## 5. 错误与重试语义

- 空节点统一返回 `selector.ErrNoAvailable`。
- p2c/wrr/random 均不重试。
- ewma 错误分类：`deadlineExceeded/canceled/serviceUnavailable/gatewayTimeout` 或 net.Error 记为失败（success=0）（`node.go:155-159`）；可经 `Builder.ErrHandler` 自定义。
- wrr 节点列表变更时**主动清理**失效权重 map，避免内存膨胀（`wrr.go:80-84`）。

## 6. 并发细节

- **p2c**：`sync.Mutex` 保护 `*rand.Rand` 取随机数（`p2c.go:42-45`）；`picked atomic.Bool` 做强制选的一次性开关（`p2c.go:74`）。
- **wrr**：`sync.Mutex` 保护 `currentWeight` map（`wrr.go:64`）。
- **ewma**：全部字段 `atomic`（`lag/success/inflight/stamp/reqs/lastPick`）+ `[200]atomic.Int64` 在途请求槽（`node.go:31-40`）；`cachedWeight atomic.Value` 缓存权重 5ms。`Pick` 回调的 inflight 槽用 CAS 标记（`node.go:122-127`）。
- **random**：无状态，用 `math/rand/v2` 全局源。
- **goroutine**：均不创建 goroutine。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `selector/p2c`、`selector/wrr`、`selector/random`、`selector/node/direct`、`selector/node/ewma`、`selector/filter/version`。

**Out-of-Scope（不在本仓库源码内）**
- `math/rand/v2`、`net` 标准库。
- 算法如何被 client 注册为全局选择器（`transport/http|grpc/client`）。
- 不做：一致性哈希会话粘滞（在 internal/subset）、连接熔断（在 internal/circuitbreaker）。

## 8. 与相邻子系统交互

- 上游：各 `NewBuilder` 返回 `selector.Builder`，由 client 经 `SetGlobalSelector` 注册（默认 `wrr`，`transport/grpc/client.go:28`）。
- 本叶子 → 下游：`Balancer.Pick` 消费 `[]WeightedNode`；`WeightedNode.Pick()` 返回的 done 回调在 RPC 完成时被调用以更新统计。
- 与 `selector-framework`：本叶子是其 `Balancer`/`WeightedNodeBuilder` 接口的具体实现。

## 9. 语言专项适配口径

- **并发模型**：Go 平台类，全原子（ewma 尤其重——`[200]atomic.Int64` 槽位记录在途请求起点以预测慢请求）。无 channel。
- **算法来源**：p2c（Power of Two Choices）、wrr（nginx 平滑轮询）、ewma（Google 2014 论文）为经典负载均衡算法。
- **internal 边界**：这些子包是公开包，供生态替换算法。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `selector-algorithms-architecture.html` | architecture | standard |

JSON IR 位于 `json/`。降 standard 原因：跨列连线横穿 wrr 组件，移除低价值边后 standard 通过（如实披露）。本叶子不补 sequence/dataflow：算法为同步选择逻辑，ewma 的统计更新已在第 3 节文字化。
