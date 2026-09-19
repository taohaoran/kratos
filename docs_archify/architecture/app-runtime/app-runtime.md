# app-runtime 域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 域职责

app-runtime 域负责**应用进程级生命周期管理**：在根包 `kratos`（`app.go`/`options.go`）中
编排各 transport Server 的并行启动、服务注册、操作系统信号监听与优雅停止。它是整个框架
的"入口控制器"——业务 `main` 调用 `kratos.New(...).Run()` 即进入本域编排。本域不实现具体
Server、注册中心或负载均衡，只通过 `transport.Server`、`registry.Registrar` 接口把下游
组装成一条启动→运行→停止的生命周期管线。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| app-lifecycle | [app-lifecycle.md](app-lifecycle/app-lifecycle.md) | [架构图](app-lifecycle/app-lifecycle-architecture.html) | [时序图](app-lifecycle/app-lifecycle-sequence.html) | errgroup 并行 Start + 信号驱动优雅停止的应用生命周期管理器 |

## 3. 域级机制细节

- **启动同步点**：`wg.Wait()` 保证每个 Server 的 `Start` 调用已发起（非就绪）后才 `Register`，避免注册到一个尚未监听的实例。
- **取消双向控制**：启动阶段 errgroup ctx 传播取消；停止阶段用 `context.WithoutCancel` 切断父取消，使 `server.Stop` 在独立截止时间内收尾。
- **注册超时**：Register/Deregister 均带默认 10s `registrarTimeout`；Server 停止用可选 `stopTimeout`。
- **钩子四段式**：beforeStart / afterStart / beforeStop / afterStop，按注册顺序执行，框架装配（如 config 加载、日志切换）挂载于此。
