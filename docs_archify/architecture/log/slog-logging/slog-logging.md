# 基于 slog 的日志（slog-logging）

> 本文是 `log` 域下的叶子子系统文档。域级总览见 `../log.md`，本文只展开 kratos 对标准库 `log/slog`
> 的封装、装饰器链（contextHandler/filterHandler）与默认 handler 构建。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 包级日志函数 | `Debug/Info/Warn/Error` 及 `*Context` 变体，镜像 slog | `log/log.go:46-83` |
| 默认 logger 管理 | `SetDefault/Default/With/WithGroup/Handler/Enabled` 委托 slog 全局 | `log/log.go:12-43` |
| 自定义记录入口 | `Log/LogAttrs` 按级别发记录，`runtime.Callers` 跳过包装帧 | `log/log.go:87-106` |
| 级别定义 | `Level=alias slog.Level`；`LevelFatal=LevelError+4`；`ParseLevel` | `log/level.go:9-43` |
| 脱敏过滤器 | `FilterKey` 把指定 key（含分组路径 `user.password`）值替换为 `***` | `log/filter.go:22-31` |
| 丢弃过滤器 | `FilterFunc(ctx,record) bool` 返回 true 时整条丢弃 | `log/filter.go:35-37` |
| context 属性注入 | `ContextWithAttrs` 把 attrs 挂 ctx，`contextHandler` 自动合并进每条记录 | `log/context.go:15-90` |
| handler 组装 | `NewHandler` 默认 stderr+text+Info+ctx extractor；`NewLogger` 包装任意 handler | `log/builder.go:84-108` |
| 格式切换 | `FormatText`（slog.NewTextHandler）/ `FormatJSON`（slog.NewJSONHandler） | `log/builder.go:13-18` |
| discardHandler | 空实现，`Enabled` 恒 false，用于 nil 兜底 | `log/handler.go:10` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Level` / `Leveler` / `LevelVar` | `log/level.go:9-15` | slog 类型别名 |
| `FilterOption` | `log/filter.go:12` | `FilterKey/FilterFunc` 的选项函数类型 |
| `filterHandler` | `log/filter.go:53` | 脱敏/丢弃装饰器，包裹下一个 handler |
| `contextHandler` | `log/context.go:66` | 从 ctx 抽 attrs 注入记录的装饰器 |
| `Extractor` | `log/builder.go:24` | `func(context.Context) []slog.Attr`，ctx→attrs 抽取器 |
| `NewHandler(opts...)` | `log/builder.go:84` | 组装 baseHandler + filterHandler + contextHandler |
| `NewLogger(handler, opts...)` | `log/builder.go:100` | 给任意 handler 加 kratos 装饰器后包成 `*slog.Logger` |
| `ContextWithAttrs` / `AttrsFromContext` | `log/context.go:15/31` | ctx 上挂/取 attrs 的 API |

## 3. 关键调用链

**调用链一：一次 `log.Info(...)` 调用**
1. 应用调 `log.Info("msg", "k", "v")`，进入包级 `log(ctx, LevelInfo, msg, args...)`（`log/log.go:56-58`、`log/log.go:108`）。
2. 先 `slog.Default().Handler().Enabled(ctx, level)` 短路，未启用直接返回（`log/log.go:109-112`）。
3. `runtime.Callers(3, pcs[:])` 跳过 `runtime.Callers/log/包级 helper` 三层栈，拿到真实调用方 PC（`log/log.go:113-115`）。
4. `slog.NewRecord(time.Now(), level, msg, pc)` + `record.Add(args...)` 构造记录（`log/log.go:116-117`）。
5. 交给 `handler.Handle(ctx, record)`：先 `contextHandler` 从 ctx 抽 attrs 合并，再 `filterHandler` 脱敏/过滤，最后 baseHandler 写入 stderr（`log/context.go:75-82`、`log/filter.go:63-71`）。

**调用链二：handler 组装顺序（NewHandler）**
1. `NewHandler` 先 `newBaseHandler(cfg)`：按 `Format` 选 text/json，带 `Level/AddSource/ReplaceAttr`（`log/builder.go:117-129`）。
2. `newComposedHandler`：若配了 filter 则 `newFilterHandler(h, cfg.filter...)` 包裹（`log/builder.go:110-115`）。
3. 再 `newContextHandler(h, cfg.extractors...)` 包裹；默认 extractor 是 `AttrsFromContext`（`log/builder.go:89`、`log/context.go:39-54`）。
4. 最终链：baseHandler ← filterHandler ← contextHandler，记录从右向左流过。

**调用链三：脱敏递归**
1. `filterHandler.Handle` 先 `rewrite(record)`：克隆记录，遍历 attrs 调 `redactAttr`（`log/filter.go:93-104`）。
2. `redactAttr` 遇 Group 递归下钻，累积分组路径；叶子 key 命中 `cfg.keys`（叶子名或 `a.b` 全路径）则值替换为 `***`（`log/filter.go:114-129`、`log/filter.go:131-141`）。
3. 脱敏后再判 `FilterFunc`，命中则丢弃整条记录（`log/filter.go:67-69`）。

## 4. 配置项

| option | 默认 / 行为 | 位置 |
|--------|-------------|------|
| `WithWriter` | 默认 `os.Stderr` | `log/builder.go:49` |
| `WithFormat` | 默认 `FormatText` | `log/builder.go:54` |
| `WithLevel` | 默认 `LevelInfo` | `log/builder.go:59` |
| `WithAddSource` | 默认 false | `log/builder.go:64` |
| `WithReplaceAttr` | 无 | `log/builder.go:69` |
| `WithExtractor` | 默认含 `AttrsFromContext` | `log/builder.go:37` |
| `WithFilter` | 无 | `log/builder.go:75` |
| `FilterKey` 匹配 | 支持叶子名（`password`）与分组路径（`user.password`） | `log/filter.go:131-141` |
| `LevelFatal` | `LevelError+4`（即 20） | `log/level.go:30` |
| `ParseLevel` | 解析失败回落 `LevelInfo` | `log/level.go:34-43` |

## 5. 错误与重试语义

- **Handle 错误被吞**：包级 `log()` 对 `handler.Handle` 返回的 error 直接 `_ =` 丢弃（`log/log.go:118`）——日志失败不影响业务。
- **无重试**：日志是 best-effort，写失败不重试。
- **nil 兜底**：`newFilterHandler/newContextHandler` 的 next 为 nil 时降级到 `discardHandler`（`log/filter.go:40-42`、`log/context.go:40-42`），不会 nil panic。
- **ParseLevel 容错**：字符串无法解析时回落 Info，不返回 error。

## 6. 并发细节

- **装饰器不可变**：`WithAttrs/WithGroup` 返回新的 handler 副本（`filter.go:73-87`、`context.go:92-98`），共享下一个 handler，符合 slog.Handler 契约。
- **无 goroutine/锁**：日志路径纯同步函数调用，并发安全由 slog.Handler 自身保证；kratos 装饰器无共享可变状态。
- **context 链**：`ContextWithAttrs` 用 `context.WithValue` 挂 attrs，`contextHandler.Handle` 每条记录现场读取，不缓存。
- **调用栈跳过**：`runtime.Callers(3)` 固定跳 3 层，依赖包级函数→log 内部→真实调用方的固定深度。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `log/log.go`、`log/handler.go`、`log/level.go`、`log/filter.go`、`log/builder.go`、`log/context.go`。

**Out-of-Scope（不在本仓库源码内）**
- `log/slog`：Go 标准库日志门面，kratos 完全复用。
- 结构化输出后端（OpenTelemetry/zap/ lumberjack 等）：见 `contrib/otel/*` 生态扩展。
- 日志采集/转发：由外部系统（不在本仓库源码内）负责。

## 8. 与相邻子系统交互

- **全框架 → 本叶子**：config/transport/middleware 等所有包通过 `log.Info/Error` 打点。
- **本叶子 → slog 标准库**：默认 logger 即 `slog.Default()`，应用 `slog.SetDefault` 可换后端。
- **contrib/otel → 本叶子**：通过实现 `slog.Handler` 接入 OTel，复用同一装饰器链。
- **本叶子 ↔ metadata 域**：`Extractor` 可从 ctx 中的 metadata 抽字段进日志（由中间件装配）。

## 9. 语言专项适配口径

- **完全基于 slog**：v3 放弃了 v2 自研 log 接口，改为直接复用标准库 `log/slog`，kratos 只做"装饰器 + 默认组装"。这是 v3 的重要架构收敛——日志门面交给标准库，生态（OTel handler）直接兼容。
- **装饰器模式**：contextHandler/filterHandler 都是 slog.Handler 的装饰器，满足 `Enabled/Handle/WithAttrs/WithGroup` 四方法，可任意组合。
- **调用栈深略**：包级 helper 通过 `runtime.Callers(3)` 修正 caller 信息，避免日志把包装函数当调用方。
- **无控制器/无后台协程**：纯同步库，与 K8s 控制器模式无关。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| slog-logging 架构图 | `slog-logging-architecture.html` | architecture | showcase |

本叶子不补时序图/数据流图：日志路径是同步装饰器调用链，已在第 3 节文字化；handler 组装是静态分层，架构图足以表达。JSON IR 源文件位于 `json/` 目录。
