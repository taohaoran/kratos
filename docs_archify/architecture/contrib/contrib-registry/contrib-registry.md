# 注册中心生态适配（contrib-registry）

> 本文是 `contrib` 域下的叶子子系统文档。域级总览见 `../contrib.md`，本文只展开 `contrib/registry/*`
> 对核心 `registry.Registrar/Discovery` 接口的各注册中心适配。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 注册抽象 | 核心 `Registrar{Register,Deregister}` + `Discovery{GetService,Watch}` + `Watcher{Next,Stop}` + `ServiceInstance` | `registry/registry.go` |
| etcd 适配 | 基于 `clientv3`，带租约心跳、namespace、maxRetry | `contrib/registry/etcd/registry.go` |
| etcd watcher | `clientv3.Watch` 前缀监听，首次拉全量 | `contrib/registry/etcd/watcher.go` |
| consul 适配 | 对接 consul agent HTTP API | `contrib/registry/consul/` |
| kubernetes 适配 | 对接 K8s Endpoints/Service | `contrib/registry/kubernetes/` |
| nacos 适配 | 对接 nacos naming client | `contrib/registry/nacos/` |
| eureka/zookeeper/servicecomb/polaris/discovery | 其余注册中心实现 | `contrib/registry/{eureka,zookeeper,servicecomb,polaris,discovery}/` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Registrar` 接口 | `registry/registry.go:11` | 注册/注销实例 |
| `Discovery` 接口 | `registry/registry.go:20` | 拉取/监听实例列表 |
| `Watcher` 接口 | `registry/registry.go:30` | 增量实例推送 |
| `ServiceInstance` | `registry/registry.go:38` | 实例描述（ID/Name/Version/Metadata/Endpoints） |
| `etcd.Registry` | `contrib/registry/etcd/registry.go:43` | 持有 `clientv3.Client`、kv、lease、ctxMap |
| `etcd.watcher` | `contrib/registry/etcd/watcher.go:12` | 包装 `clientv3.WatchChan` |
| `New(client, opts...)` | `contrib/registry/etcd/registry.go` | 构造 etcd 注册器 |

## 3. 关键调用链

**调用链一：注册实例（以 etcd 为例）**
1. 应用 `reg, _ := etcd.New(client, etcd.RegisterTTL(15*time.Second))`（`etcd/registry.go`）。
2. `var _ registry.Registrar = (*Registry)(nil)` 编译期断言接口满足（`etcd/registry.go:14`）。
3. `Register(ctx, inst)` 把实例 JSON 写入 etcd key，租约 TTL 续约，起 goroutine 心跳；cancel 存入 `ctxMap`（`etcd/registry.go:51-56`）。
4. `Deregister` 从 `ctxMap` 取 cancel 停心跳，删 key。

**调用链二：发现与 watch**
1. `Watch(ctx, serviceName)` 调 `newWatcher`，内部 `clientv3.NewWatcher` + `Watch(key, WithPrefix())`（`etcd/watcher.go:24-38`）。
2. `Next()` 首次先 `getInstance()` 拉全量，之后从 `watchChan` 等变更（`etcd/watcher.go:40-50`）。
3. 变更后解析实例列表返回 `[]*registry.ServiceInstance`。
4. `Stop()` cancel ctx 关闭 watcher。

**调用链三：接入 App**
1. 应用 `app := kratos.New(kratos.Registrar(reg))`，App 启动时注册、停止时注销（见系统级 App 生命周期）。

## 4. 配置项

| option | 默认 / 行为 | 位置 |
|--------|-------------|------|
| etcd `RegisterTTL` | 15s | `etcd/registry.go` options |
| etcd `Namespace` | `/microservices` | 同上 |
| etcd `MaxRetry` | 5 | 同上 |
| etcd `Context` | context.Background | 同上 |

## 5. 错误与重试语义

- **注册失败**：etcd 注册器 `MaxRetry` 控制重试次数，心跳失败按 TTL 过期摘除。
- **watcher 错误**：`Next()` 透传 `watchChan` 错误，由上层调用方处理。
- **无统一重试**：各实现重试策略各异，本图以 etcd 为代表。
- **编译期断言**：每个实现文件首行 `var _ registry.X = (*Y)(nil)`，接口漂移编译期暴露。

## 6. 并发细节

- **心跳 goroutine**：每个注册实例一个 ctxMap 条目，Deregister 时 cancel 停止。
- **watchChan**：etcd 客户端自有 goroutine 分发事件，本实现只读 channel。
- **无共享锁**：各实现用底层 client 的并发安全原语。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `registry/registry.go` 接口 + `contrib/registry/*` 各适配。

**Out-of-Scope（不在本仓库源码内）**
- etcd/consul/k8s/nacos/eureka/zookeeper/servicecomb/polaris 服务端本身：外部系统。
- `go.etcd.io/etcd/client/v3` 等客户端库：第三方依赖。
- 客户端负载均衡算法：见 `selector/` 域。

## 8. 与相邻子系统交互

- **App → 本叶子**：App 通过 `kratos.Registrar(reg)` 注入。
- **本叶子 → selector 域**：Discovery 产出的 `ServiceInstance` 列表供 selector 做负载均衡。
- **transport 域 ↔ 本叶子**：client 端 resolver 用 Discovery 解析服务名。

## 9. 语言专项适配口径

- **接口在消费方**：`registry.Registrar/Discovery` 定义在 `registry/`（框架核心），实现放在 `contrib/registry/*`（生态），依赖倒置——核心不依赖任何具体注册中心。
- **独立 go.mod**：每个 contrib 子包有自己的 `go.mod`（如 etcd 自带），应用按需引入，不把所有注册中心依赖拉进主模块。
- **编译期接口断言**：`var _ registry.Registrar = (*Registry)(nil)` 是 Go 惯用法。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| contrib-registry 架构图 | `contrib-registry-architecture.html` | architecture | standard（多组件+region 约束多轮微调后降 standard，如实披露） |

JSON IR 源文件位于 `json/` 目录。
