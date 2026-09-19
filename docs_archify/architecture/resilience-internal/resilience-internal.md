# resilience-internal 域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 域职责

resilience-internal 域集中在 `internal/` 下，为框架内部提供**韧性控制与通用工具**：
SRE 熔断器、BBR 自适应限流两个韧性算法，以及一组被 transport/middleware 广泛复用的小工具
（endpoint/group/host、subset/matcher/httputil/context）。这些包不对外暴露（internal 隔离），
通过 `middleware/circuitbreaker`、`middleware/ratelimit` 等公开中间件间接为业务所用。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| sre-circuitbreaker | [sre-circuitbreaker.md](sre-circuitbreaker/sre-circuitbreaker.md) | [架构图](sre-circuitbreaker/sre-circuitbreaker-architecture.html) | [状态机](sre-circuitbreaker/sre-circuitbreaker-lifecycle.html) | Google SRE 算法滑动窗口失败率概率熔断 |
| bbr-ratelimit | [bbr-ratelimit.md](bbr-ratelimit/bbr-ratelimit.md) | [架构图](bbr-ratelimit/bbr-ratelimit-architecture.html) | [数据流](bbr-ratelimit/bbr-ratelimit-dataflow.html) | CPU 负载+RT 自适应在途限流 |
| endpoint-group-host | [endpoint-group-host.md](endpoint-group-host/endpoint-group-host.md) | [架构图](endpoint-group-host/endpoint-group-host-architecture.html) | — | endpoint 解析、泛型懒加载容器、私有 IP 提取 |
| subset-matcher-httputil | [subset-matcher-httputil.md](subset-matcher-httputil/subset-matcher-httputil.md) | [架构图](subset-matcher-httputil/subset-matcher-httputil-architecture.html) | — | 一致性哈希子集、中间件匹配、content-type、双 ctx 合并 |

## 3. 域级机制细节

- **两类韧性原语共享滑动窗口**：SRE 熔断与 BBR 限流都用"环形时间桶 + 互斥锁"的滑动窗口，但用途不同——前者统计成功/失败比，后者统计通过量与 RT 分布。
- **internal 隔离 + 公开别名**：算法实现在 `internal/`，`middleware/circuitbreaker`、`middleware/ratelimit` 通过类型别名对外暴露 `CircuitBreaker`/`Limiter`，业务不直接依赖 internal。
- **工具包被多 transport 复用**：host/endpoint 用于 HTTP/gRPC server 推导监听地址；group 用于熔断中间件按 operation 懒加载；subset 用于客户端 resolver 切分实例子集；matcher 用于按 operation 挂中间件。
