# 编解码（encoding）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

encoding 域提供一个全局编解码注册表，按名称（format）取用 `Codec`（Marshal/Unmarshal/Name）。
内置 json/proto/protojson/xml/yaml/form 六种 codec，均通过各自 `init()` 自注册；业务或第三方
（如 contrib 的 msgpack）只需 import 即可扩展，无需改动核心。config、transport 等模块通过
`encoding.GetCodec(format)` 解耦序列化细节。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| encoding-framework | [encoding-framework.md](encoding-framework/encoding-framework.md) | [架构图](encoding-framework/encoding-framework-architecture.html) | — | Codec 接口、全局注册表与 init 自注册 |

## 3. 域级机制细节

- **注册表**：`encoding.go:21` 的 `registeredCodecs map[string]Codec`，`RegisterCodec` 注册（空名/nil panic），`GetCodec` 查找。
- **自注册约定**：每个 codec 包 `func init() { RegisterCodec(...) }`，import 即注册。
- **tagName 可配置**：form 默认 `json` tag，可 ldflags 替换。
- **protojson 固定选项**：EmitUnpopulated + DiscardUnknown。
