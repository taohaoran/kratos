# endpoint / group / host 工具集（endpoint-group-host）

> 本文是 `resilience-internal` 域下的叶子子系统文档。域级总览见 `../resilience-internal.md`。
> 本文展开 `internal/endpoint`、`internal/group`、`internal/host` 三个被 transport 层广泛复用的小工具包。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| endpoint 构造 | `NewEndpoint(scheme,host)` 拼 `*url.URL` | `internal/endpoint/endpoint.go:8` |
| endpoint 选取 | `ParseEndpoint(endpoints, scheme)` 按 scheme 匹配返回 host | `internal/endpoint/endpoint.go:13` |
| 安全 scheme | `Scheme(scheme,isSecure)` 拼 `http(s)` | `internal/endpoint/endpoint.go:29` |
| 泛型懒加载容器 | `Group[T]`：首次 Get 才建对象并缓存 | `internal/group/group.go:12` |
| 容器复位/清空 | `Reset`（换工厂+清空）、`Clear` | `internal/group/group.go:52,63` |
| 地址拆分 | `ExtractHostPort(addr)` 拆 host/port | `internal/host/host.go:10` |
| 监听端口 | `Port(lis)` 从 `*net.TCPAddr` 取真实端口 | `internal/host/host.go:26` |
| 私有 IP 提取 | `Extract(hostPort, lis)` 从网卡选可通告 IP | `internal/host/host.go:34` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Group[T]` struct | `group.go:12` | 泛型懒加载容器：`factory` + `vals map[string]T` + `sync.RWMutex` |
| `Factory[T]` | `group.go:9` | 无参对象工厂签名；nil 构造直接 panic |
| `consistent`（不在本叶子，见 subset） | — | group 是泛型缓存，与一致性哈希无关 |
| `Extract` | `host.go:34` | 核心：监听地址为 `0.0.0.0` 时遍历网卡挑首个全局单播 IPv4 |

## 3. 关键调用链

**链路一：`group.Get` 双重检查锁**（`group.go:30`）
1. 先 `RLock` 读缓存命中即返回（`group.go:31-36`）。
2. 未命中释放读锁，`Lock` 拿写锁，再查一次防并发重复创建（`group.go:40-44`）。
3. `factory()` 创建并写入 `vals[key]`（`group.go:46-47`）。

**链路二：`host.Extract` 私有 IP 选择**（`host.go:34`）
1. 若显式 addr 非 `0.0.0.0`/`[::]`/`::`，直接 `JoinHostPort` 返回（`host.go:46-48`）。
2. 否则 `net.Interfaces()` 遍历上行（`FlagUp`）网卡（`host.go:57-60`）。
3. 对每网卡地址做 `isValidIP`（全局单播且非本地组播）筛选，命中 IPv4 即 `break`（`host.go:78-84`）。
4. 返回所选 IP 与监听器端口拼接（`host.go:87-88`）。

**链路三：`endpoint.ParseEndpoint`**（`endpoint.go:13`）
- 遍历 endpoint 串，`url.Parse` 后按 `u.Scheme == scheme` 匹配，命中返回 `u.Host`；无匹配返回空串（不报错）。

## 4. 配置项

本叶子无运行时配置项。行为由调用方传入参数决定：
- `group`：`NewGroup` 工厂不可为 nil（否则 panic，`group.go:21,54`）。
- `host.Extract`：`lis==nil` 且 hostPort 无法 SplitHostPort 时返回 error（`host.go:36-38`）。

## 5. 错误与重试语义

- `endpoint.ParseEndpoint`：解析失败返回该 error；无匹配 scheme 返回空串+nil（`endpoint.go:16-24`）。
- `host.ExtractHostPort`：`SplitHostPort` 失败或 port 非数字即返回 error（`host.go:12-17`）。
- `host.Extract`：网卡遍历中单网卡 `Addrs()` 失败 `continue` 跳过（`host.go:65-67`）；全网卡无可用 IP 返回空串+nil（`host.go:90`）。
- `group`：工厂 panic 会向上抛；不捕获、不重试。
- 无重试/退避。

## 6. 并发细节

- **group 锁**：`sync.RWMutex`（`group.go:15`），读路径 `RLock`、写路径 `Lock`，典型单飞（single-flight）懒加载，避免并发重复构造。
- **host/endpoint**：纯函数，无共享状态，天然并发安全。
- **goroutine**：本叶子不创建 goroutine。
- **网络栈**：`host.Extract` 直接调 `net.Interfaces()` 做系统调用，每次调用即时读取，无缓存。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `internal/endpoint`、`internal/group`、`internal/host` 三个工具包。

**Out-of-Scope（不在本仓库源码内）**
- `net`、`net/url` 标准库。
- 消费方 `transport/http/server.go`、`transport/grpc/server.go`、`middleware/circuitbreaker`（用 group 做每 operation 熔断器缓存）。
- 不做：服务注册健康探测、多网卡优先级策略（仅按接口 Index 升序取首个 IPv4）。

## 8. 与相邻子系统交互

- 上游：`transport/http/server`、`transport/grpc/server` 用 `host.Extract` 推导对外地址、`endpoint.ParseEndpoint` 选取监听 URL；`middleware/circuitbreaker` 用 `group.Group[CircuitBreaker]` 做每方法熔断器懒加载。
- 本叶子 → 下游：仅调用标准库，无外部依赖。

## 9. 语言专项适配口径

- **并发模型**：Go 泛型（`Group[T]`，Go 1.18+）实现类型安全的懒加载缓存；`RWMutex` 读多写少优化。无 channel/context。
- **internal 边界**：三个包均在 `internal/`，仅框架内部 transport/middleware 使用，不对外暴露。
- **平台特性**：`host.Extract` 依赖 `net.Interfaces`/`net.Interface.Flags`，跨平台行为依赖 OS 网络栈（Linux/BSD 一致）。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| 组件图 | `endpoint-group-host-architecture.html` | architecture | standard |

JSON IR 位于 `json/`。降 standard 原因：showcase 严格布局下三分支连线标签与外部调用方组件边界轻微重叠，standard 通过（如实披露）。本叶子不补 sequence/dataflow：均为同步工具函数调用，无异步管道或消息时序。
