# App 生命周期管理器（app-lifecycle）

> 本文是 `app-runtime` 域下的叶子子系统文档。域级总览见 `../app-runtime.md`，
> 本文只展开应用根包 `kratos` 的生命周期编排职责，不展开 transport 各 Server 内部
> （见 `transport/` 相关叶子）与 registry 实现细节（见 `discovery/` 域）。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 应用实例句柄 | `App` 持有 options、ctx/cancel、instance，实现 `AppInfo`（ID/Name/Version/Metadata/Endpoint） | `app.go:30-36`、`app.go:21-27` |
| 构造与默认值 | `New` 注入默认 ctx/信号/注册超时/uuid，并应用 Option 模式 | `app.go:39-60` |
| 生命周期编排 | `Run`：buildInstance→beforeStart→并行 Start→注册→afterStart→信号监听→优雅停止→afterStop | `app.go:83-151` |
| 服务实例装配 | `buildInstance`：优先用显式 endpoints，否则从各 Server 的 `Endpointer.Endpoint()` 推导 | `app.go:176-199` |
| 优雅停止 | `Stop`：beforeStop→Deregister→cancel；停止用 `context.WithoutCancel` 剥离父 ctx 取消 | `app.go:154-174`、`app.go:105` |
| 钩子体系 | BeforeStart/AfterStart/BeforeStop/AfterStop 四类有序钩子 | `options.go:104-129` |
| context 注入 | `NewContext`/`FromContext` 把 AppInfo 挂进 ctx | `app.go:204-212` |
| 选项集 | ID/Name/Version/Metadata/Endpoint/Context/Logger/Server/Signal/Registrar 等函数式选项 | `options.go:42-99` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `App` struct | `app.go:30` | 生命周期管理器本体；`mu` 保护 instance 读写 |
| `AppInfo` interface | `app.go:21` | 应用元信息契约（ID/Name/Version/Metadata/Endpoint），App 自身实现 |
| `options` struct | `options.go:18` | 全部私有配置：servers/registrar/超时/信号/四组钩子 |
| `Option` func | `options.go:15` | 函数式选项，统一修改 `*options` |
| `transport.Server`（外部接口） | `transport/transport.go` | `Start(ctx) error` / `Stop(ctx) error`，本叶子只编排不实现 |
| `transport.Endpointer`（外部接口） | `transport/transport.go` | `Endpoint() (*url.URL, error)`，用于自动推导监听地址 |
| `registry.Registrar`（外部接口） | `registry/registry.go:10` | `Register/Deregister`，本叶子只调用 |

## 3. 关键调用链

**链路一：`Run` 启动主路径**（`app.go:83`）
1. `buildInstance()` 组装 `*registry.ServiceInstance`（`app.go:84`）；若无显式 endpoints，则对实现 `Endpointer` 的 Server 逐个调用 `Endpoint()` 收集监听地址（`app.go:181-191`）。
2. 执行 `beforeStart` 钩子（`app.go:95-99`）。
3. `eg, ctx := errgroup.WithContext(sctx)`（`app.go:92`）；对每个 Server 起**两个** goroutine：一个阻塞等待 `ctx.Done()` 后调用 `server.Stop`（`app.go:103-112`），另一个先 `wg.Done()` 再 `server.Start(octx)`（`app.go:114-117`）。
4. `wg.Wait()`（`app.go:119`）确保所有 Server 的 `Start` 已被发起（而非已就绪）后，才执行 `registrar.Register`（`app.go:120-126`，带 `registrarTimeout=10s`）。
5. 执行 `afterStart` 钩子（`app.go:127-131`）。
6. `signal.Notify(c, sigs...)` 监听信号（`app.go:133-134`），再起一个 goroutine 在收到信号或 ctx 取消时调 `a.Stop()`（`app.go:135-142`）。
7. `eg.Wait()` 阻塞至全部 goroutine 退出；`context.Canceled` 被视为正常退出而忽略（`app.go:143-145`）。
8. 执行 `afterStop` 钩子（`app.go:147-149`）。

**链路二：`Stop` 优雅停止**（`app.go:154`）
1. 执行 `beforeStop` 钩子（`app.go:156-158`）。
2. 加锁取 instance，`Deregister`（带 10s 超时）（`app.go:160-169`）。
3. `a.cancel()` 取消 errgroup 派生 ctx（`app.go:170-172`），从而触发链路一中各 Server 的 Stop 等待 goroutine。

**链路三：Server 停止的上下文剥离**（`app.go:105-111`）
- 停止阶段用 `context.WithoutCancel(octx)` 构造一个**不受父 ctx 取消影响**的新上下文，再叠加 `stopTimeout`；这样即便 errgroup ctx 已取消，`server.Stop` 仍能在独立截止时间内完成收尾。

## 4. 配置项

| 选项 / 默认 | 行为 | 位置 |
|-------------|------|------|
| `ctx` 默认 `context.Background()` | 根上下文 | `app.go:41` |
| `sigs` 默认 `[SIGTERM, SIGQUIT, SIGINT]` | 触发优雅停止的信号集，可用 `Signal()` 覆盖 | `app.go:42`、`options.go:82` |
| `registrarTimeout` 默认 `10s` | Register/Deregister 超时 | `app.go:43`、`options.go:92` |
| `stopTimeout` 默认 `0`（不超时） | 各 Server.Stop 的截止时间；>0 时才包 WithTimeout | `options.go:97`、`app.go:106-109` |
| `id` 默认 uuid | 实例 ID | `app.go:45-47` |
| `logger` 非 nil 时 | `log.SetDefault(o.logger)` 切换默认日志 | `app.go:51-53` |

## 5. 错误与重试语义

- `buildInstance` 推导 Endpoint 失败直接 `return err`（`app.go:186`），`Run` 立即返回。
- `beforeStart` 任一钩子返回 error，`Run` 立即返回，此时 Server 尚未 Start（`app.go:96-98`）。
- `registrar.Register` 失败会从 `eg.Go` 外直接 `return err`（`app.go:123-125`）；注意此时已 Start 的 Server 仍在运行，调用方需自行处理进程退出。
- `eg.Wait()` 返回的错误若非 `context.Canceled` 则上抛（`app.go:143-145`），即某个 Server 的 Start/Stop 失败会终止 Wait。
- Deregister 失败直接 `return err`（`app.go:166-168`），不再执行后续 cancel。
- 框架本身**不做重试**：注册失败、Server 启动失败均一次性返回，重试由部署/外部编排负责。

## 6. 并发细节

- **errgroup 编排**：`eg, ctx := errgroup.WithContext(sctx)`（`app.go:92`）。任一子 goroutine 返回非 nil 错误即取消共享 ctx。
- **每 Server 两个 goroutine**：Stop 等待协程 `<-ctx.Done()` 后停止；Start 协程先 `wg.Done()` 再 Start。`wg.Wait()`（`app.go:119`）保证的是"Start 调用已发起"，而非"Server 已就绪"——这是先注册前的同步点。
- **信号 goroutine**：`signal.Notify` 的 channel 缓冲为 1（`app.go:133`），仅起一个 select 协程（`app.go:135-142`）。
- **锁**：`a.mu sync.Mutex` 仅保护 `a.instance` 字段（`Run` 写 `app.go:88-90`、`Stop` 读 `app.go:160-162`、`Endpoint()` 读 `app.go:76`），无长临界区。
- **取消传播链**：`New` 时 `context.WithCancel(o.ctx)`（`app.go:54`）；`Stop` 调 `a.cancel()` 触发 errgroup ctx 取消，级联到各 Server Stop 协程；而真正的 Server.Stop 又用 `WithoutCancel` 切断这条链以保证收尾。
- **goroutine 泄漏风险**：正常路径下 errgroup.Wait 回收全部协程；`signal.Notify` 未调用 `signal.Stop`，但进程退出即终止，可接受。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- 根包 `kratos`：`app.go`、`options.go`、`version.go` 的生命周期编排、钩子、context 注入。

**Out-of-Scope（不在本仓库源码内）**
- 各 transport Server（HTTP/gRPC）的 Start/Stop 内部实现——见 `transport/` 域。
- 注册中心 etcd/consul/k8s 等 Registrar 实现——`contrib/registry/`，不在主仓库。
- `golang.org/x/sync/errgroup`、`os/signal`、`google/uuid` 为第三方依赖。
- 不做：健康检查、leader 选举、进程 supervisor——由部署层（K8s systemd）负责。

## 8. 与相邻子系统交互

- 上游：用户 `main` → `kratos.New(...).Run()`；Server 集合来自 `Server()` 选项，Registrar 来自 `Registrar()` 选项。
- 本叶子 → 下游：`App` → 每个 `transport.Server`（Start/Stop）→ 具体 HTTP/gRPC 监听；`App` → `registry.Registrar`（Register/Deregister）→ 外部注册中心。
- 与 `discovery/registry-interface` 叶子：本叶子是 `Registrar` 接口的**消费方**（服务端注册侧）；`Discovery/Watcher` 接口的消费方在客户端 resolver（`transport/grpc/resolver/discovery`）。

## 9. 语言专项适配口径

- **并发模型**：Go 平台类，采用 errgroup 作为并行编排原语而非 K8s informer/Reconcile 模式——本叶子是"进程级生命周期管理器"，无 workqueue/informer；取消传播依赖 context 树 + `context.WithoutCancel` 双向控制（启动传播取消、停止切断取消）。
- **internal 边界**：本叶子位于根包，不属 `internal/`；它依赖 `transport`、`registry`、`log` 三个公开包，方向单向（根包→公开抽象），无环依赖。
- **多二进制**：本叶子是库代码，被所有业务进程 `main` 复用；`cmd/kratos` 等脚手架是独立 module，不依赖运行时 App。
- **接口定义位置**：`transport.Server`/`Endpointer`/`registry.Registrar` 均定义在消费方（本叶子与 transport）侧，实现方在 contrib——符合依赖倒置。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 架构图 | `app-lifecycle-architecture.html` | architecture | showcase |
| 启动→注册→停止时序 | `app-lifecycle-sequence.html` | sequence | showcase |

JSON IR 源文件位于 `json/` 目录。无降档。本叶子不再补 dataflow/lifecycle 图：生命周期阶段已由时序图完整表达，无独立状态机。
