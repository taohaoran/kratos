# 业务错误模型（errors-model）

> 本文是 `errors` 域下的叶子子系统文档。域级总览见 `../errors.md`，本文只展开 kratos 的业务错误码模型、
> 与 gRPC status 的双向兼容、以及对标准库 errors 包的兼容。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 业务错误结构 | `*Error` 内嵌 `Status{Code,Reason,Message,Metadata}` + 底层 `cause` | `errors/errors.go:23` |
| 错误构造 | `New(code,reason,message)`、`Newf`、`Errorf` | `errors/errors.go:68-86` |
| 常用 HTTP 语义构造 | `BadRequest/Unauthorized/Forbidden/NotFound/Conflict/TooManyRequests/ClientClosed/InternalServer/ServiceUnavailable/GatewayTimeout` | `errors/types.go` |
| 错误判定 | 对应 `IsBadRequest/IsNotFound` 等，按 `Code(err)==xxx` 判断 | `errors/types.go` |
| cause 包装 | `WithCause(cause)` 克隆并挂底层错误 | `errors/errors.go:44` |
| 元数据 | `WithMetadata(map[string]string)` 克隆并挂 KV | `errors/errors.go:51` |
| gRPC 互转 | `GRPCStatus()` 转 gRPC status + `errdetails.ErrorInfo`；`FromError` 反向还原 | `errors/errors.go:58`、`errors/errors.go:128` |
| 标准错误兼容 | 透传 `errors.Is/As/Unwrap/Join/ErrUnsupported` | `errors/wrap.go` |
| Protobuf 扩展 | `errors.proto` 定义 `Status` message 与 `default_code/code` 扩展（1108/1109），供 protoc-gen-go-errors 生成枚举 | `errors/errors.proto` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Error` 结构 | `errors/errors.go:23` | 业务错误主体，实现 `error` 接口 |
| `Status`（pb） | `errors/errors.pb.go` | protobuf 生成的 `code/reason/message/metadata` |
| `UnknownCode/UnknownReason` | `errors/errors.go:14-17` | 默认 500 / 空 reason |
| `Code(err)` / `Reason(err)` | `errors/errors.go:90/99` | 从任意 error 链提取业务码/原因，nil 返回 200/空 |
| `FromError(err)` | `errors/errors.go:128` | 任意 error → `*Error`；非 kratos 错误尝试从 gRPC status 还原 |
| `Clone(err)` | `errors/errors.go:107` | 深拷贝 metadata 的不可变克隆 |
| `ErrUnsupported` | `errors/wrap.go:20` | 透传标准库 `errors.ErrUnsupported` |

## 3. 关键调用链

**调用链一：业务错误构造与判定**
1. 业务代码 `errors.BadRequest("USER_NOT_FOUND", "用户不存在")` 实际调 `New(400, reason, message)`（`errors/types.go:5-7`）。
2. 返回 `*Error{Status:{Code:400,Reason:"USER_NOT_FOUND",Message:"..."}, cause:nil}`。
3. 调用方 `errors.Is(err, targetErr)` 时走 `(*Error).Is`：用 `errors.As` 沿链找到 `*Error`，比较 `Code` 与 `Reason` 都相等才算匹配（`errors/errors.go:36-41`）——即同 code+reason 视为同一错误，而非指针相等。
4. `errors.IsBadRequest(err)` 只是 `Code(err)==400` 的语法糖（`errors/types.go:11`）。

**调用链二：与 gRPC status 互转**
1. 服务端把 `*Error` 交给 gRPC 框架，框架调 `(*Error).GRPCStatus()`：`httpstatus.ToGRPCCode(Code)` 把 HTTP 码映射成 gRPC 码，再 `WithDetails(&errdetails.ErrorInfo{Reason,Metadata})`（`errors/errors.go:58-64`）。
2. 跨网络传到客户端后，客户端拿到的是 gRPC `status`，调 `FromError(err)`：先 `errors.As` 找 `*Error`，找不到再 `status.FromError` 拿 gRPC status，`httpstatus.FromGRPCCode` 转回 HTTP code，并从 `Details` 里找 `*errdetails.ErrorInfo` 还原 `Reason` 与 `Metadata`（`errors/errors.go:135-150`）。
3. 若既非 kratos `*Error` 也非 gRPC status，则包装成 `New(500, "", err.Error())` 兜底。

**调用链三：cause 包装链**
1. `e.WithCause(cause)` 调 `Clone(e)` 深拷贝 metadata 后挂上 `cause`（`errors/errors.go:44-47`、`errors/errors.go:107-124`）。
2. `(*Error).Unwrap()` 返回 `cause`（`errors/errors.go:33`），使 `errors.Is/As` 能穿透到 cause。
3. `Error()` 方法把 code/reason/message/metadata/cause 拼成字符串（`errors/errors.go:28-30`）。

## 4. 配置项

| 项 | 默认 / 行为 | 位置 |
|----|-------------|------|
| `UnknownCode` | 500 | `errors/errors.go:14` |
| `UnknownReason` | 空字符串 | `errors/errors.go:17` |
| protobuf 扩展号 | `default_code=1108`（EnumOptions）、`code=1109`（EnumValueOptions） | `errors/errors.proto:20-25` |
| `FromError(nil)` | 返回 nil，不构造错误 | `errors/errors.go:129-131` |
| `Code(nil)` | 返回 200（视为成功） | `errors/errors.go:91-93` |

## 5. 错误与重试语义

- **本包不负责重试**：错误模型只做错误的表示、包装与转换，重试策略在调用方/中间件。
- **FromError 容错**：无法识别的错误兜底为 500 + 原错误文本，绝不 panic。
- **Is 匹配语义**：按 Code+Reason 双字段匹配，不看 message——允许 message 变化而错误类型不变。
- **Clone 语义**：`WithCause/WithMetadata` 都先 `Clone` 再改，不修改原错误对象（不可变风格）。
- **wrap.go 透传**：`Is/As/Unwrap/Join` 直接委托标准库，保证与 Go 1.13+ 错误链完全兼容。

## 6. 并发细节

- **不可变值对象**：`*Error` 通过 `Clone` 派生新实例，运行期共享 `*Error` 无写竞争。
- **无 goroutine/锁**：纯值类型，无后台协程。
- **Metadata 拷贝**：`Clone` 对 metadata map 做深拷贝（`errors/errors.go:111-114`），避免共享可变 map。
- **grpc status 构建**：`WithDetails` 在 `GRPCStatus()` 调用时现场构造，无缓存。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `errors/errors.go`、`errors/types.go`、`errors/wrap.go`、`errors/errors.proto`、`errors/errors.pb.go`。

**Out-of-Scope（不在本仓库源码内）**
- `google.golang.org/grpc/status`、`google.golang.org/genproto/googleapis/rpc/errdetails`：gRPC 状态与错误详情的标准库。
- `transport/http/status`：HTTP↔gRPC 状态码映射表（本仓库 `transport/http/status`，由 transport 域维护）。
- protoc-gen-go-errors 如何把枚举生成 `*Error` 构造函数：见 `protoc-gen-plugins` 叶子。
- 错误如何在 HTTP/gRPC 响应中序列化：见 transport 域叶子。

## 8. 与相邻子系统交互

- **transport 域 → 本叶子**：HTTP/gRPC server 把业务返回的 `error` 经 `FromError`/`GRPCStatus` 转成对端可理解的状态码与详情。
- **middleware 域 → 本叶子**：recovery/validation 中间件把 panic/校验失败转成 `*Error`。
- **tooling 域 → 本叶子**：protoc-gen-go-errors 基于 `errors.proto` 扩展生成业务错误枚举的 Go 代码。
- **本叶子 → 标准库**：`wrap.go` 薄封装 `errors` 包，业务侧统一从 kratos errors 包导入 `Is/As`。

## 9. 语言专项适配口径

- **错误链兼容**：实现 `Unwrap() error` + `Is(error) bool`，符合 Go 1.13 错误链协议；`Is` 自定义为 Code+Reason 双字段匹配，而非默认的指针/值相等——这是 kratos 业务错误模型的核心扩展点。
- **不可变模式**：`WithCause/WithMetadata` 返回克隆，避免多 goroutine 共享可变错误对象，与 Go 值类型并发安全惯例一致。
- **Protobuf 扩展**：通过 `EnumOptions/EnumValueOptions` 扩展把错误码声明进 `.proto`，由代码生成器落地为 Go 枚举+构造函数，体现 API-first 工作流。
- **无控制器模式**：纯值类型库，无 Reconcile/informer；与 K8s 控制器模式无关。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| errors-model 架构图 | `errors-model-architecture.html` | architecture | showcase |

本叶子不补时序图：错误模型是静态值对象 + 转换函数，`GRPCStatus`/`FromError` 转换在 MD 第 3 节已文字化，无独立异步管道。JSON IR 源文件位于 `json/` 目录。
