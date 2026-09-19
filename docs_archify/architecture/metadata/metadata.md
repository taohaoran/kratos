# 元数据（metadata）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

metadata 域负责跨进程的 key-value 透传（与 gRPC metadata / HTTP header 对齐）。所有 key 归一化为
小写，元数据以不可导出类型 `serverMetadataKey{}` / `clientMetadataKey{}` 挂在 `context.Context`
上，避免与其他包的 ctx key 碰撞。提供 `New.AppendToClientContext/FromClientContext/FromServerContext`
等挂摘 API。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| metadata-propagation | [metadata-propagation.md](metadata-propagation/metadata-propagation.md) | [架构图](metadata-propagation/metadata-propagation-architecture.html) | — | 透传 Metadata 的 ctx 挂摘 |

## 3. 域级机制细节

- **类型**：`Metadata = map[string][]string`，key 全小写。
- **ctx key 防碰撞**：`serverMetadataKey{}`/`clientMetadataKey{}` 不可导出，外部无法误用。
- **入参校验**：`AppendToClientContext` 要求奇数个 kv（key/value 成对），否则 panic。
