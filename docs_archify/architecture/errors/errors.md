# 错误（errors）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

errors 域定义业务错误码模型：错误携带 HTTP code、业务 reason、message 与元数据，并兼容 gRPC `status`。
提供 `errors.New`、`errors.BadRequest/NotFound/...` 等语义化构造函数、`Is/As/Unwrap` 包装链，
以及与标准库 `errors` 完全透传的 `Is/As/Unwrap/Join`。gRPC/HTTP 错误经由 `FromError/GRPCStatus`
互相转换。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| errors-model | [errors-model.md](errors-model/errors-model.md) | [架构图](errors-model/errors-model-architecture.html) | — | Error 模型、语义化构造、gRPC 转换、wrap |

## 3. 域级机制细节

- **错误模型**：`Error` 内嵌 `Status{Code,Reason,Message,Metadata}` + cause，`Is` 按 Code+Reason 匹配。
- **proto 扩展**：`errors.proto` 扩展号 default_code=1108 / code=1109，由 protoc-gen-go-errors 生成。
- **code 范围**：`(0,600]`，越界 panic。
- **标准库兼容**：`wrap.go` 直接透传 `errors.Is/As/Unwrap/Join`。
