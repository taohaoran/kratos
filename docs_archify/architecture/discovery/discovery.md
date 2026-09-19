# discovery 域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 域职责

discovery 域负责**服务注册发现与客户端负载均衡**：`registry/` 定义注册发现接口契约与
实例数据模型；`selector/` 定义选择器框架接口、默认组合实现，以及 p2c/wrr/random 等具体
均衡算法与 direct/ewma 节点权重实现。本仓库只定义抽象与默认算法，注册中心实现（etcd 等）
在 `contrib/registry/`。客户端通过全局选择器（默认 wrr）从 watch 到的实例列表中选出一个节点发起 RPC。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| registry-interface | [registry-interface.md](registry-interface/registry-interface.md) | [架构图](registry-interface/registry-interface-architecture.html) | — | Registrar/Discovery/Watcher/ServiceInstance 接口契约 |
| selector-framework | [selector-framework.md](selector-framework/selector-framework.md) | [架构图](selector-framework/selector-framework-architecture.html) | — | Selector/Balancer/Node 抽象与 Default 组合实现 |
| selector-algorithms | [selector-algorithms.md](selector-algorithms/selector-algorithms.md) | [架构图](selector-algorithms/selector-algorithms-architecture.html) | — | p2c/wrr/random 算法 + direct/ewma 节点权重 + 版本过滤 |

## 3. 域级机制细节

- **契约与实现分离**：`registry` 与 `selector` 均为接口定义在消费方（依赖倒置），具体注册中心在 contrib、具体算法在本域子包。
- **实例→节点→选择管线**：registry 产出 `ServiceInstance` → `selector.NewNode` 包装为 `Node` → `WeightedNodeBuilder` 包成 `WeightedNode` → `Balancer.Pick` 选出 → RPC 完成回调更新节点统计。
- **热更新无锁**：`Default.nodes` 用 `atomic.Value` 整体替换；ewma 节点用全原子字段记录在途请求与延迟，高并发下无锁读权重。
- **默认装配**：HTTP/gRPC client 默认 `SetGlobalSelector(wrr.NewBuilder())`（wrr+direct）；p2c+ewma 为延迟感知可选。
