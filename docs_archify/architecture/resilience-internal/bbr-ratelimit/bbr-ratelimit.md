# BBR 自适应限流器（bbr-ratelimit）

> 本文是 `resilience-internal` 域下的叶子子系统文档。域级总览见 `../resilience-internal.md`。
> 本文只展开 `internal/ratelimit/bbr.go` 的 BBR 自适应限流算法；其服务端封装中间件
> 见 `middleware/ratelimit`（不属本叶子展开）。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| Limiter 接口 | `Limiter{Allow() (DoneFunc, error)}` | `internal/ratelimit/ratelimit.go:17` |
| BBR 限流器 | 基于 CPU 负载 + RT + 最大通过量的自适应阈值 | `internal/ratelimit/bbr.go:142` |
| CPU 采样 | 包级 `init` 起 `cpuproc` goroutine，500ms 采样并 EMA 平滑到 `gCPU` | `bbr.go:24-42` |
| CPU 采样器 | `runtime/metrics` 读 `/cpu/classes/total|idle:cpu-seconds` 差分 | `bbr.go:44-83` |
| 滑动窗口 | `passStat`（通过量）、`rtStat`（时延分布）两个 `rollingCounter` | `bbr.go:181-182` |
| 指标快照 | `Stat()` 暴露 CPU/InFlight/MaxInFlight/MinRt/MaxPass | `bbr.go:280-288` |
| 完成回调 | `DoneFunc` 记录 RT、回补 inFlight、记通过 | `bbr.go:297-303` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Limiter` interface | `ratelimit.go:17` | 限流契约 |
| `DoneFunc`/`DoneInfo` | `ratelimit.go:9,12` | 请求完成回调与元信息 |
| `BBR` struct | `bbr.go:142` | 持有 cpu 读取器、两个窗口、原子 inFlight、三个 `atomic.Value` 缓存 |
| `cpuproc` | `bbr.go:28` | 包级常驻 goroutine，EMA 平滑 CPU |
| `cpuSampler` | `bbr.go:44` | 基于 runtime/metrics 的 CPU 使用率采样（0..1000） |
| `rollingCounter` | `bbr.go:306` | 带 `reduce` 聚合（max/min）的环形窗口 |
| `Stat` | `bbr.go:93` | 对外指标结构 |

## 3. 关键调用链

**链路一：`Allow` 放行决策**（`bbr.go:291`）
1. `shouldDrop()`（`bbr.go:253`）判定是否拒绝，拒绝则返回 `ErrLimitExceed`。
2. 放行：`atomic.AddInt64(&l.inFlight, 1)`（`bbr.go:295`），记录 `start`。
3. 返回闭包 `DoneFunc`：结束时计算 RT（毫秒）写入 `rtStat`、`inFlight--`、`passStat.add(1)`（`bbr.go:297-303`）。

**链路二：`shouldDrop` 阈值**（`bbr.go:253`）
1. `l.cpu() < CPUThreshold`（默认 800）时：若距上次丢弃 `prevDropTime` 超过 1s 则不丢弃；1s 内且 `inFlight>maxInFlight()` 才延续丢弃（`bbr.go:255-266`）。
2. `cpu() >= CPUThreshold` 时：`inFlight > 1 && inFlight > maxInFlight()` 即丢弃，并记录 `prevDropTime`（`bbr.go:267-276`）。

**链路三：`maxInFlight` 推导**（`bbr.go:249`）
- `maxPASS()` = 窗口内单桶最大通过量（`bbr.go:198`）；`minRT()` = 窗口内最小平均 RT（`bbr.go:224`）；`maxInFlight = floor(maxPASS*minRT*bucketPerSecond/1000 + 0.5)`（`bbr.go:250`）。两者均有 `atomic.Value` 缓存，1 个桶时长内不重算。

## 4. 配置项

| 选项 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `Window` | 10s | 滑动窗口 | `bbr.go:160` |
| `Bucket` | 100 | 窗口桶数（桶时长=Window/Bucket） | `bbr.go:161` |
| `CPUThreshold` | 800（千分制） | CPU 高水位阈值 | `bbr.go:162` |
| `CPUQuota` | 0（用 GOMAXPROCS 推算） | 非 0 时按 quota 归一化 CPU | `bbr.go:190-194` |
| 包级 `decay` | 0.95 | CPU EMA 平滑系数 | `bbr.go:14` |

## 5. 错误与重试语义

- 拒绝返回 `ErrLimitExceed`（`ratelimit.go:6`），由 `middleware/ratelimit` 包装为 429 `RATELIMIT`。
- 限流器不重试；拒绝是瞬时判定。
- `cpuSampler.usage()` 首帧返回 0（无差分基准），采样异常（`totalDelta<=0`）也返回 0（`bbr.go:69-82`），不报错。
- 无退避/排队：要么放行拿到 DoneFunc，要么直接拒绝。

## 6. 并发细节

- **包级 goroutine**：`init()` 起 `go cpuproc()`（`bbr.go:24-26`），500ms ticker 常驻；进程生命周期内不退出（进程退出即终止）。`gCPU` 用 `atomic.StoreInt64` 读写（`bbr.go:38-40`）。
- **inFlight**：`atomic.AddInt64` 原子增减（`bbr.go:295,301`），无锁。
- **缓存**：`prevDropTime`/`maxPASSCache`/`minRtCache` 均为 `atomic.Value`（`bbr.go:150-152`），无锁读。
- **窗口锁**：`rollingCounter.mu sync.Mutex` 保护 `add`/`reduce`（`bbr.go:329,346`）；`reduce` 遍历全部桶计算 max/min。
- **CPUQuota 归一化**：设置后 `cpu()` 闭包把全局 `gCPU` 按 `GOMAXPROCS/CPUQuota` 缩放，适配容器配额（`bbr.go:190-194`）。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `internal/ratelimit`：BBR 限流器、CPU 采样、滑动窗口、错误与接口。

**Out-of-Scope（不在本仓库源码内）**
- BBR 网络拥塞控制原型（Google TCP BBR）——理论来源。
- `runtime/metrics`、`runtime.GOMAXPROCS` 为 Go 标准库。
- `middleware/ratelimit` 的服务端装配——见 `middleware/`。
- 不做：令牌桶/漏桶定速、分布式限流、限流事件 metrics 上报。

## 8. 与相邻子系统交互

- 上游：`middleware/ratelimit.Server` → `limiter.Allow()` → 放行则调 handler → `done(DoneInfo{Err})` 回写。
- 本叶子 → 下游：无网络调用；只读进程内 CPU 指标与自身统计。
- 与 `middleware/ratelimit`：默认 `internalratelimit.NewLimiter()` 即本 BBR 实现（`middleware/ratelimit.go:41`）。

## 9. 语言专项适配口径

- **并发模型**：Go 平台类。两个并发原语并存——(a) 包级单 goroutine + atomic 共享 `gCPU`（生产者-消费者）；(b) 请求路径全 atomic（inFlight/缓存）+ 窗口互斥锁。无 context 传播、无 channel 通信。
- **容器感知**：通过 `runtime/metrics` CPU 差分 + `CPUQuota` 归一化适配 K8s CPU quota 场景（Go 平台特有的可观测性边界）。
- **internal 边界**：`internal/ratelimit` 内部使用，公开别名经 `middleware/ratelimit` 导出 `Limiter/DoneFunc/DoneInfo`（类型别名）。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `bbr-ratelimit-architecture.html` | architecture | standard |
| 决策数据流 | `bbr-ratelimit-dataflow.html` | dataflow | standard |

JSON IR 位于 `json/`。两张图均降 standard：组件图主路径标签在 showcase 严格布局下与组件框重叠；数据流图扇出边（放行/拒绝）标签间距不足。按速查规范降档并如实披露。本叶子不补 sequence 图：`Allow→Done` 为同步闭包调用链，已在第 3 节文字化。
