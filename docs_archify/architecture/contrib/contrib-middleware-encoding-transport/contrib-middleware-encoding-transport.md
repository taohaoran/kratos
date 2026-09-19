# 中间件/编解码/传输生态适配（contrib-middleware-encoding-transport）

> 本文是 `contrib` 域下的叶子子系统文档。域级总览见 `../contrib.md`，本文只展开
> `contrib/middleware/{jwt,validate}`、`contrib/encoding/{json,msgpack}`、`contrib/transport/mcp`、
> `contrib/polaris` 对核心扩展点的适配。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| JWT 中间件 | 基于 `golang-jwt/v5`，bearer token 解析与校验 | `contrib/middleware/jwt/jwt.go` |
| Validate 中间件 | 校验请求（基于 proto validate / validator） | `contrib/middleware/validate/` |
| msgpack 编解码 | `init()` 自注册 `encoding.RegisterCodec`，委托 `vmihailenco/msgpack/v5` | `contrib/encoding/msgpack/msgpack.go:13` |
| json 编解码（增强） | contrib 额外 json codec | `contrib/encoding/json/` |
| MCP 传输 | 实现 `transport.Server/Endpointer/http.Handler`，基于 `mark3labs/mcp-go` | `contrib/transport/mcp/server.go:14` |
| polaris 集成 | 对接 polaris-go 的 router/config/limit/registry/discovery 五 API | `contrib/polaris/polaris.go` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `jwt.Err*` 错误族 | `middleware/jwt/jwt.go:33-44` | 9 个 `errors.Unauthorized` 错误 |
| `jwt` Middleware 构造 | `middleware/jwt/jwt.go` | 实现 `middleware.Middleware` |
| `msgpack.codec` | `encoding/msgpack/msgpack.go:18` | Marshal/Unmarshal/Name，委托 msgpack |
| `mcp.Server` | `transport/mcp/server.go:14` | 编译期断言 `transport.Server`/`Endpointer`/`http.Handler` |
| `polaris.Polaris` | `polaris/polaris.go:11` | 持有 RouterAPI/ConfigAPI/LimitAPI/ProviderAPI/ConsumerAPI |

## 3. 关键调用链

**调用链一：msgpack 自注册**
1. `msgpack.go:13` `func init() { encoding.RegisterCodec(codec{}) }`。
2. 应用 import `_ "github.com/go-kratos/kratos/contrib/encoding/msgpack"` 触发 init。
3. `config`/`transport` 通过 `encoding.GetCodec("msgpack")` 取到 codec。
4. `codec.Marshal/Unmarshal` 委托 `vmihailenco/msgpack/v5`（`msgpack.go:22-29`）。

**调用链二：JWT 中间件**
1. 应用 `grpc.Middleware(jwt.Server(keyFunc))`（`middleware/jwt/jwt.go`）。
2. 中间件从 `Authorization: Bearer <token>` 取 token（`jwt.go:16-24`）。
3. `jwt.ParseWithClaims` 校验签名/过期，失败返回 `ErrTokenExpired`/`ErrTokenInvalid`（均 `errors.Unauthorized`）。
4. 成功把 token 放入 ctx 供下游取。

**调用链三：MCP 服务**
1. `var _ transport.Server = (*Server)(nil)` 等三个断言（`transport/mcp/server.go:14-16`）。
2. 应用把 mcp Server 作为 `kratos.Server(...)` 注入 App，App 生命周期管理 Start/Stop。

## 4. 配置项

| option | 默认 / 行为 | 位置 |
|--------|-------------|------|
| jwt `bearerFormat` | `Bearer %s` | `jwt.go:18` |
| jwt `authorizationKey` | `Authorization` | `jwt.go:21` |
| mcp `Address`/`Endpoint` | 监听地址/对外 endpoint | `transport/mcp/server.go` |
| polaris `WithNamespace` | 默认命名空间 | `polaris/polaris.go:28` |

## 5. 错误与重试语义

- **JWT 错误**：全部用 `errors.Unauthorized(reason, msg)`，reason 恒为 `"UNAUTHORIZED"`（`jwt.go:33-44`）。
- **未授权**：HTTP 映射 401，gRPC `Unauthenticated`。
- **编解码错误**：msgpack 直接透传底层错误。
- **无重试**：中间件/编码失败即拒绝请求。

## 6. 并发细节

- **中间件**：jwt/validate 无状态，并发安全。
- **自注册**：`init()` 在单线程阶段执行，无并发问题。
- **MCP Server**：`http.Server` 自有连接 goroutine。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `contrib/middleware/{jwt,validate}`、`contrib/encoding/{json,msgpack}`、`contrib/transport/mcp`、`contrib/polaris`。

**Out-of-Scope（不在本仓库源码内）**
- `github.com/golang-jwt/jwt/v5`、`github.com/vmihailenco/msgpack/v5`、`github.com/mark3labs/mcp-go`、`github.com/polarismesh/polaris-go`：第三方库。
- polaris/MCP 服务端：外部系统。

## 8. 与相邻子系统交互

- **middleware 核心 ↔ jwt/validate**：实现 `middleware.Middleware` 签名。
- **encoding 核心 ↔ msgpack/json**：走 `encoding.RegisterCodec` 自注册。
- **transport 核心 ↔ mcp**：实现 `transport.Server/Endpointer`。
- **config/registry ↔ polaris**：polaris 同时适配配置与注册中心。

## 9. 语言专项适配口径

- **init 自注册**：msgpack 复用 encoding 注册表机制，与内置 json/proto/yaml 同构，零侵入。
- **接口断言**：`var _ transport.Server = (*Server)(nil)` 编译期保证 mcp 接入 App。
- **独立 go.mod**：各 contrib 子包自带 go.mod，按需引入第三方重依赖。
- **错误复用**：JWT 错误全部复用核心 `errors` 包的 `Unauthorized`，不另立错误模型。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| contrib-middleware-encoding-transport 架构图 | `contrib-middleware-encoding-transport-architecture.html` | architecture | showcase |

JSON IR 源文件位于 `json/` 目录。
