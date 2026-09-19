# 中间件（middleware）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0，Go 1.25）。

## 1. 域职责

middleware 域是 kratos 框架的**横切关注点层**，定义与 transport 协议无关的装饰器模型，
并提供一组内置中间件。核心职责：

- **中间件契约**：定义 `Handler`（`func(ctx,req)(any,error)`）与 `Middleware`
  （`func(Handler)Handler`）类型，以及 `Chain` 反向包裹组装。
- **按 operation 匹配**：`matcher.Matcher` 支持 `Use`（全局默认）、`Add(selector)`（`/*`、
  `/pkg.Svc/*`、`/pkg.Svc/Method` 三级），运行期 `Match(operation)` 选出适用中间件。
- **韧性中间件**：recovery（panic 恢复）、ratelimit（bbr 限流）、circuitbreaker（SRE 熔断）。
- **可观测性中间件**：logging（slog 请求日志）、metadata（头透传）、selector（条件选中间件）、
  validate（请求校验）。

域内共享机制：所有中间件都是 `middleware.Middleware`，被 transport server/client 经
`middleware.Chain(Match(operation)...)(handler)` 包裹；中间件通过 `transport.FromServerContext/
FromClientContext` 读取请求的传输侧视图，从而与协议解耦。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| middleware-stack | [middleware-stack.md](middleware-stack/middleware-stack.md) | [架构图](middleware-stack/middleware-stack-architecture.html) | — | Handler/Middleware/Chain 与按 operation 匹配 |
| builtin-resilience-middleware | [builtin-resilience-middleware.md](builtin-resilience-middleware/builtin-resilience-middleware.md) | [架构图](builtin-resilience-middleware/builtin-resilience-middleware-architecture.html) | — | recovery/ratelimit/circuitbreaker 韧性三件套 |
| builtin-observability-middleware | [builtin-observability-middleware.md](builtin-observability-middleware/builtin-observability-middleware.md) | [架构图](builtin-observability-middleware/builtin-observability-middleware-architecture.html) | — | logging/metadata/selector/validate 可观测四件套 |

## 3. 域级机制细节

- **Chain 包裹顺序**：`Chain(m...)` 从后向前包裹（`m[len-1]...m[0]`），执行时按声明顺序
  `m[0]→m[1]→...→handler`。
- **Match 优先级**：defaults（Use）总前置 → 精确 operation 命中 → 最长前缀命中
  （prefix 按字典序降序排序）。
- **transporter 解耦**：中间件不感知 gRPC/HTTP，统一经 context 中的 `Transporter` 取
  `Kind()/Operation()/RequestHeader()`。
- **错误模型**：韧性/校验中间件把失败转成 `*errors.Error`（429/503/400），
  logging 经 `errors.FromError` 提取 code/reason。
- **可插拔算法**：限流默认 bbr、熔断默认 SRE，均可经 option 注入自定义实现；
  更丰富的 metrics/tracing 在 contrib/otel。

## 4. 域级图

本域未单独绘制域级架构图；三个叶子架构图已覆盖组件与依赖关系。
