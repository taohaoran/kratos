# 注册发现接口契约（registry-interface）

> 本文是 `discovery` 域下的叶子子系统文档。域级总览见 `../discovery.md`。
> 本文展开 `registry/registry.go` 的注册发现接口契约；具体 etcd/consul/k8s 等实现
> 在 `contrib/registry/`，不在本主仓库源码内。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 注册接口 | `Registrar{Register, Deregister}` | `registry/registry.go:10` |
| 发现接口 | `Discovery{GetService, Watch}` | `registry/registry.go:18` |
| 监听接口 | `Watcher{Next, Stop}` | `registry/registry.go:26` |
| 实例模型 | `ServiceInstance`：ID/Name/Version/Metadata/Endpoints | `registry/registry.go:37` |
| 实例判等 | `Equal`：排序 Endpoints 后逐项比较 | `registry/registry.go:58` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Registrar` interface | `registry.go:10` | 服务端注册/注销契约 |
| `Discovery` interface | `registry.go:18` | 客户端发现契约：一次性拉取 + 持续监听 |
| `Watcher` interface | `registry.go:26` | `Next()` 阻塞返回最新实例列表，`Stop()` 关闭 |
| `ServiceInstance` struct | `registry.go:37` | 服务实例数据模型，JSON tag 供序列化 |
| `ServiceInstance.Equal` | `registry.go:58` | 深比较（含排序 Endpoints、Metadata 逐项） |

## 3. 关键调用链

**链路一：服务端注册**（被 `app.Run` 调用）
- `App.buildInstance` 组装 `*ServiceInstance`（`app.go:192`）→ `Registrar.Register(ctx, instance)`（`app.go:123`，10s 超时）→ 停止时 `Deregister`（`app.go:166`）。

**链路二：客户端发现**（被 resolver 调用）
1. `Discovery.GetService(ctx, name)` 一次性拉取全量实例（`registry.go:20`）。
2. `Discovery.Watch(ctx, name)` 建 `Watcher`（`registry.go:22`）。
3. `Watcher.Next()` 阻塞，仅在"首次非空"或"实例列表变化"时返回（`registry.go:31` 注释约定）。
4. `Watcher.Stop()` 关闭监听（`registry.go:33`）。

**链路三：实例判等**（`registry.go:58`）
- `Equal` 先比 Endpoints 数量、排序后逐项比；再比 Metadata 长度与逐项；最后比 ID/Name/Version（`registry.go:72-94`）。供 resolver 判变更。

## 4. 配置项

本叶子为纯接口定义，无配置项。`ServiceInstance.Endpoints` 的 URL scheme 约定见注释：
`http://host:port?isSecure=false`、`grpc://host:port?isSecure=false`（`registry.go:47-50`）。

## 5. 错误与重试语义

- 接口本身不定义错误语义，由实现方约定。
- `Watcher.Next` 文档约定：无变更时阻塞直至 ctx 超时/取消（`registry.go:30`）。
- `Equal` 接收 nil  receiver/参数做了 nil 安全处理（`registry.go:59-65`）。
- 框架不重试注册/发现；重试与重连由 contrib 实现负责。

## 6. 并发细节

- 本包无锁、无 goroutine——纯接口与数据结构。
- `ServiceInstance.Equal` 会**原地排序入参的 Endpoints**（`registry.go:76-77`），调用方需注意这是有副作用的判等。
- 并发安全由实现方保证；契约上 `Watcher.Next` 通常在单 goroutine 中被消费。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `registry/registry.go`：四个接口 + `ServiceInstance` 数据模型。

**Out-of-Scope（不在本仓库源码内）**
- etcd/consul/k8s/nacos/eureka/zookeeper 等 `Registrar`/`Discovery`/`Watcher` 实现——`contrib/registry/`。
- 服务端注册触发（`App`，见 app-runtime 域）与客户端消费（resolver，见 selector/transport 域）。
- 不做：健康检查、权重计算、负载均衡算法。

## 8. 与相邻子系统交互

- 上游：`App`（服务端）实现 `Registrar` 调用方；`transport/grpc|http/resolver/discovery`（客户端）实现 `Discovery/Watcher` 调用方。
- 本叶子 → 下游：`ServiceInstance` 被 `selector.NewNode` 转换为 `selector.Node`（见 selector-framework 叶子）。
- 与 `selector-framework`：registry 产出实例，selector 从实例选节点，是上下游关系。

## 9. 语言专项适配口径

- **接口定义位置**：`Registrar` 由消费方（App）定义并持有；`Discovery`/`Watcher` 由客户端 resolver 持有；实现方在 contrib——典型依赖倒置，主仓库只定义契约。
- **Go 平台**：纯接口 + 值类型 struct，无并发原语；`Equal` 用作领域判等。
- **internal 边界**：`registry/` 是公开包（非 internal），是框架对生态暴露的扩展点契约。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 接口契约图 | `registry-interface-architecture.html` | architecture | standard |

JSON IR 位于 `json/`。降 standard 原因：垂直对齐组件间连线被渲染器误推断侧方向，移除低价值边后 standard 通过（如实披露）。本叶子不补 sequence：纯接口契约，无内部调用时序。
