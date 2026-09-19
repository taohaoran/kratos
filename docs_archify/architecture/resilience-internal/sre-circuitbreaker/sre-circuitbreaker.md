# SRE 熔断器（sre-circuitbreaker）

> 本文是 `resilience-internal` 域下的叶子子系统文档。域级总览见 `../resilience-internal.md`。
> 本文只展开 `internal/circuitbreaker` 的 SRE 熔断器算法实现；其对外封装中间件
> （按 operation 懒加载每方法一个 breaker）见 `middleware/circuitbreaker`（不属本仓库主分析路径的展开对象）。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 熔断器接口 | `CircuitBreaker{Allow,MarkSuccess,MarkFailed}` | `internal/circuitbreaker/circuitbreaker.go:9` |
| SRE 熔断器实现 | `Breaker`：基于滑动窗口失败率的概率拒绝 | `internal/circuitbreaker/sre.go:57` |
| 滑动窗口计数 | `rollingCounter`：N 个时间桶的环形窗口 | `internal/circuitbreaker/sre.go:131` |
| 状态标记 | `StateOpen`/`StateClosed` 两态（无半开） | `internal/circuitbreaker/sre.go:11-16` |
| 可选项 | WithFailureRatio/WithRequest/WithWindow/WithBucket | `internal/circuitbreaker/sre.go:29-54` |
| 拒绝错误 | `ErrNotAllowed` | `internal/circuitbreaker/circuitbreaker.go:6` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `CircuitBreaker` interface | `circuitbreaker.go:9` | 熔断器契约：Allow 放行判定、Mark 记账 |
| `Breaker` struct | `sre.go:57` | 持有 `*rollingCounter`、`k`、`request`、`state`、加锁 `random` |
| `NewBreaker` | `sre.go:68` | 构造并校验默认参数，计算 `k=1/(1-failureRatio)` |
| `rollingCounter` | `sre.go:131` | 互斥锁保护的环形桶计数；`add`/`summary`/`currentSlot` |
| `counterBucket` | `sre.go:137` | 单桶：`slot` 时间槽、`success`、`total` |

## 3. 关键调用链

**链路一：`Allow` 放行判定**（`sre.go:106`）
1. `b.stat.summary()` 汇总窗口内 `successes, total`（`sre.go:107`）。
2. `requests := b.k * float64(successes)`（`sre.go:108`），`k=1/(1-failureRatio)`。
3. 若 `total < request`（样本不足）或 `total < requests`（健康）：`CAS StateOpen→StateClosed` 并放行（`sre.go:109-112`）。
4. 否则 `CAS StateClosed→StateOpen`（`sre.go:113`），计算 `dropRatio = max(0,(total-requests)/(total+1))`（`sre.go:114`）。
5. `b.random() < dropRatio` 则返回 `ErrNotAllowed`，否则放行（`sre.go:115-118`）。

**链路二：记账**（`sre.go:122-129`）
- `MarkSuccess` → `stat.add(1)`；`MarkFailed` → `stat.add(0)`。`add` 按 `currentSlot()` 定位桶，桶 slot 变化则清零（`sre.go:150-164`）。

**链路三：滑动窗口汇总**（`sre.go:166-180`）
- `summary` 遍历全部桶，跳过空桶、过期桶（`slot-bucket.slot >= size`）和未来桶（`bucket.slot > slot`），累加 success/total。

> 关键事实：`state` 仅是一个 `atomic` 提示标志，真正的拒绝/放行决策每次都基于 `summary()` 实时统计，并非"打开就硬断"。

## 4. 配置项

| 选项 | 默认 | 行为 | 位置 |
|------|------|------|------|
| `failureRatio` | 0.5（越界回退 0.5） | 失败率阈值，k=1/(1-failureRatio) | `sre.go:70,78` |
| `request` | 20（<1 回退 1） | 最小采样数，未达一律放行 | `sre.go:71,81` |
| `bucket` | 10（<1 回退 1） | 窗口桶数 | `sre.go:72,84` |
| `window` | 3s（<=0 回退 3s） | 滑动窗口时长 | `sre.go:73,87` |

## 5. 错误与重试语义

- 拒绝仅返回 `ErrNotAllowed`（`circuitbreaker.go:6`），由上层 `middleware/circuitbreaker` 包装为 503 `CIRCUITBREAKER` 错误。
- 熔断器本身不重试、不睡眠；拒绝是瞬时概率判定。
- 恢复无固定冷却时间：只要窗口统计转健康（`total>=k*successes`）即停止按比例拒绝，属渐进恢复。
- 无 backoff/退避机制；采样窗口本身随时间滚动淘汰旧数据。

## 6. 并发细节

- **互斥锁**：`rollingCounter.mu sync.Mutex` 同时保护 `add`（`sre.go:154`）与 `summary`（`sre.go:170`）。这是本叶子唯一的粗粒度锁，读 `summary` 也拿写锁——在高 QPS 下是热点，但窗口很短、临界区仅遍历桶数组。
- **随机数源**：`rand.New(rand.NewSource(time.Now().UnixNano()))` 包在 `randMu sync.Mutex` 内（`sre.go:94-98`），保证 `*rand.Rand` 并发安全。
- **原子状态**：`b.state int32` 用 `atomic.CompareAndSwapInt32` 做 Open↔Closed 翻转（`sre.go:110,113`），无锁。
- **goroutine**：本包不创建常驻 goroutine，无泄漏风险。
- **时钟**：`currentSlot()` 直接读 `time.Now().UnixNano()`（`sre.go:182`），无独立定时器。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `internal/circuitbreaker`：熔断器接口、SRE 实现、滑动窗口计数。

**Out-of-Scope（不在本仓库源码内）**
- SRE 论文原型算法（Google SRE 第 4 章）——理论来源。
- `middleware/circuitbreaker` 的每 operation 懒加载分组（用 `internal/group`）与错误分类——见 `middleware/`。
- 不做：半开探测、固定冷却期、熔断事件指标上报（指标由 contrib/otel 负责）。

## 8. 与相邻子系统交互

- 上游：`middleware/circuitbreaker.Client` → 按 `info.Operation()` 从 `internal/group` 取/建 `Breaker` → `Allow` → 调用下游 → `MarkSuccess/MarkFailed`。
- 本叶子 → 下游：仅产出 `ErrNotAllowed`，不发网络请求。
- 与 `resilience-internal/endpoint-group-host` 叶子：`internal/group.Group[CircuitBreaker]` 是其懒加载容器的直接消费方。

## 9. 语言专项适配口径

- **并发模型**：Go 平台类，但非 K8s 控制器模式——本叶子是无状态并发原语，核心是"互斥锁保护的环形窗口 + 原子状态翻转 + 加锁随机源"。无 channel/errgroup。
- **internal 边界**：位于 `internal/circuitbreaker`，仅框架内部可见；对外类型别名在 `middleware/circuitbreaker` 重新导出，符合 internal 隔离 + 公开别名的依赖方向。
- **可观测性边界**：本包不打印日志/不发 metrics；错误仅为 sentinel error，由 middleware 层转成业务错误码。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `sre-circuitbreaker-architecture.html` | architecture | showcase |
| 两态迁移 | `sre-circuitbreaker-lifecycle.html` | lifecycle | standard |

JSON IR 位于 `json/`。lifecycle 降档原因：两态双向迁移边在相邻列下标签易重叠，双泳道自动路由后 showcase 严格布局仍报警，standard 档通过（如实披露）。本叶子不补 sequence 图：调用链已在第 3 节文字化，无跨进程消息时序。
