# 日志（log）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

log 域完全基于标准库 `log/slog` 做封装：提供 `NewLogger`、`With/WithContext` 取值 API，以及
默认 stderr + text handler + Info 级别的 builder。通过装饰器链（baseHandler ← filterHandler ←
contextHandler）支持日志脱敏、动态级别、从 ctx 提取属性，与 OpenTelemetry slog bridge 等外部
handler 无缝替换。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| slog-logging | [slog-logging.md](slog-logging/slog-logging.md) | [架构图](slog-logging/slog-logging-architecture.html) | — | 基于 log/slog 的封装、装饰器链、脱敏与级别 |

## 3. 域级机制细节

- **装饰器链**：`builder.go` 构造 `contextHandler(filterHandler(baseHandler))`。
- **脱敏**：`filter.go` 把 redacted 值替换为 `***`。
- **源码定位**：`log.go:log()` 用 `runtime.Callers(3)` 跳过封装帧。
- **ctx 属性**：`context.go` 提供 `ContextWithAttrs`，中间件可挂日志字段。
