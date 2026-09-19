# 编解码框架（encoding-framework）

> 本文是 `encoding` 域下的叶子子系统文档。域级总览见 `../encoding.md`，本文只展开 codec 注册表
> 与各内置格式的 init 自注册机制；具体 codec 的 Marshal/Unmarshal 委托给标准库或第三方库，不展开。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| Codec 抽象接口 | `Marshal/Unmarshal/Name` 三方法，要求实现并发安全 | `encoding/encoding.go:10` |
| 全局注册表 | 包级 `registeredCodecs map[string]Codec` | `encoding/encoding.go:21` |
| 注册函数 | `RegisterCodec`：nil/空名 panic，name 转小写作 key | `encoding/encoding.go:25` |
| 查找函数 | `GetCodec(contentSubtype)`：按小写名取 codec，未注册返回 nil | `encoding/encoding.go:40` |
| json codec | 委托标准库 `encoding/json`，空数据 Unmarshal 直接返回 nil | `encoding/json/json.go:12` |
| proto codec | 委托 `google.golang.org/protobuf`，transport 默认 codec | `encoding/proto/proto.go:17` |
| protojson codec | protobuf 消息的 JSON 映射，`EmitUnpopulated` + `DiscardUnknown` | `encoding/protojson/protojson.go:26` |
| xml codec | 委托标准库 `encoding/xml` | `encoding/xml/xml.go:12` |
| yaml codec | 委托 `gopkg.in/yaml.v3` | `encoding/yaml/yaml.go:12` |
| form codec | `x-www-form-urlencoded`，委托 `go-playground/form/v4`，tag 默认 `json` 可 ldflags 替换 | `encoding/form/form.go:26` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Codec` 接口 | `encoding/encoding.go:10` | 编解码契约：线格式与 `any` 互转 + 静态名称 |
| `registeredCodecs` | `encoding/encoding.go:21` | 包级注册表，消费方按名查找 |
| `RegisterCodec(codec)` | `encoding/encoding.go:25` | 注册入口，init 阶段调用 |
| `GetCodec(name)` | `encoding/encoding.go:40` | 查找入口，未命中返回 nil |
| 各包 `Name` 常量 | 各 `encoding/<fmt>/<fmt>.go` | 注册用静态名称（如 `"json"`、`"x-www-form-urlencoded"`） |
| `form.tagName` | `encoding/form/form.go` | form 编解码 tag，默认 `"json"`，可 `-ldflags=-X ...tagName=form` 替换 |

## 3. 关键调用链

**调用链一：init 自注册（启动期一次性）**
1. 某包被 `import _ "github.com/go-kratos/kratos/v3/encoding/json"` 引入（如 `config/config.go:11`）。
2. Go 运行时按依赖顺序执行该包 `init()`（`encoding/json/json.go:12-14`）。
3. `init()` 调 `encoding.RegisterCodec(codec{})`，`RegisterCodec` 把 `codec.Name()`（`"json"`）转小写存入 `registeredCodecs["json"]`（`encoding/encoding.go:32-33`）。
4. 若注册 nil 或空名 codec，`RegisterCodec` 直接 panic，启动期即暴露配置错误。

**调用链二：消费方按名取 codec**
1. 消费方（如 config 的 `defaultDecoder`）调 `encoding.GetCodec(src.Format)`（`config/options.go:93`）。
2. 注册表按小写 key 命中则返回 `Codec`，调用方 `codec.Unmarshal(src.Value, &target)` 反序列化。
3. 未命中返回 nil，config 报 `unsupported key ... format ...` 错误。

**调用链三：form codec 与 proto 消息的特殊处理**
1. form codec 的 `Marshal/Unmarshal` 走 `go-playground/form/v4` 的 encoder/decoder，tag 名由包级变量 `tagName` 决定（默认 `json`，即复用 struct 的 json tag）。
2. proto codec 的 `Unmarshal` 用 `getProtoMessage` 反射解指针找到 `proto.Message`，再 `proto.Unmarshal`（`encoding/proto/proto.go:28-34`）。
3. protojson codec 固定 `EmitUnpopulated:true` + `DiscardUnknown:true`，全局 `MarshalOptions/UnmarshalOptions` 可改（`encoding/protojson/protojson.go:17-23`）。

## 4. 配置项

| 配置 / 选项 | 默认 / 行为 | 位置 |
|-------------|-------------|------|
| `RegisterCodec` 注册名 | 必须非空，统一转小写 | `encoding/encoding.go:29-33` |
| `form.tagName` | 默认 `"json"`，可用 `-ldflags=-X .../encoding/form.tagName=form` 改 | `encoding/form/form.go` |
| `protojson.MarshalOptions` | `EmitUnpopulated:true`（输出零值字段） | `encoding/protojson/protojson.go:17` |
| `protojson.UnmarshalOptions` | `DiscardUnknown:true`（忽略未知字段） | `encoding/protojson/protojson.go:21` |
| json 空数据 | `Unmarshal` 收到空字节直接返回 nil，不报错 | `encoding/json/json.go:29-31` |

## 5. 错误与重试语义

- **注册错误**：nil codec 或空 `Name()` 直接 panic，不返回 error——属于编程错误，启动期暴露。
- **查找未命中**：`GetCodec` 返回 nil，由调用方决定报错（config 报 unsupported format，transport 拒绝请求）。
- **编解码错误**：各 codec 直接透传底层库（json/yaml/proto）的 error，框架不包装、不重试。
- **proto 类型不匹配**：`proto.Marshal` 对非 `proto.Message` 类型会 panic（`encoding/proto/proto.go:25` 直接类型断言），属调用方使用错误。
- **无重试**：编解码是纯 CPU 操作，失败即失败，框架不做重试。

## 6. 并发细节

- **注册表只读**：`registeredCodecs` 只在 init 阶段（单线程）写入，运行期只读，无锁设计——依赖 Go init 顺序保证 happens-before。
- **Codec 并发安全**：接口注释明确要求实现并发安全（`encoding/encoding.go:8-9`），所有内置 codec 均为无状态 struct，满足要求。
- **form 编解码器**：包级 `encoder/decoder` 单例（`encoding/form/form.go:22-23`），`go-playground/form/v4` 自身并发安全。
- **无 goroutine/channel**：本叶子纯函数调用，无后台协程。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `encoding/encoding.go` 注册表与接口。
- `encoding/json`、`encoding/proto`、`encoding/protojson`、`encoding/xml`、`encoding/yaml`、`encoding/form` 六个内置 codec。

**Out-of-Scope（不在本仓库源码内）**
- `google.golang.org/protobuf` 系列（proto/protojson 底层）：第三方依赖。
- `gopkg.in/yaml.v3`、`github.com/go-playground/form/v4`：第三方编解码库。
- 其他格式（msgpack 等）：见 `contrib/encoding/*` 生态扩展。
- transport 层如何根据 content-type 选 codec：见 transport 域叶子。

## 8. 与相邻子系统交互

- **encoding 域 ← config 域**：config 的 `defaultDecoder` 通过 `GetCodec(Format)` 反序列化配置文本（`config/options.go:93`）。
- **encoding 域 ← transport 域**：gRPC/HTTP server/client 根据 content-type 取 codec 做请求/响应序列化。
- **encoding 域 → 第三方库**：各 codec 委托标准库或第三方库完成实际编解码。
- **contrib/encoding → 本域**：生态扩展（如 msgpack）同样调 `RegisterCodec` 注册，复用同一注册表。

## 9. 语言专项适配口径

- **init 自注册模式**：Go 特有的包初始化副作用模式。消费方只需 `import _ "..."` 即可注册，框架核心不依赖任何具体 codec（依赖倒置）。这是 Go 框架插件机制的经典用法，与 Go 语言专项清单中的"init 自注册"直接对应。
- **并发模型**：无 goroutine、无锁；注册表写在 init（单线程）、读在运行期（多线程），靠 Go 初始化 happens-before 保证可见性。
- **接口契约**：`Codec` 接口只 3 个方法，`Name()` 必须静态（注释要求 `cannot change between calls`），支持 transport 据此构造 content-type。
- **多二进制边界**：本包在主模块 `github.com/go-kratos/kratos/v3`，与 cmd 下的独立 go.mod 隔离。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| encoding-framework 架构图 | `encoding-framework-architecture.html` | architecture | showcase |

本叶子不补时序图/数据流图：init 自注册是启动期一次性动作，运行期是简单的"按名查表"调用，架构图已充分表达；数据流图（一次编解码）无独立管道阶段。JSON IR 源文件位于 `json/` 目录。
