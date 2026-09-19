# 生态集成（contrib）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

contrib 域是框架的生态扩展层，把各种第三方基础设施（注册中心、配置中心、可观测性后端、
中间件、编解码、传输协议）适配到核心定义的接口（`registry.Registrar/Discovery`、`config.Source`、
`middleware.Middleware`、`encoding.Codec`、`transport.Server` 等）。核心框架不直接依赖这些第三方库，
所有 contrib 子包自带独立 `go.mod`，应用按需引入，避免把全部生态依赖拉进主模块。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| contrib-registry | [contrib-registry.md](contrib-registry/contrib-registry.md) | [架构图](contrib-registry/contrib-registry-architecture.html) | — | 9 个注册中心适配（etcd/consul/k8s/nacos/...） |
| contrib-config | [contrib-config.md](contrib-config/contrib-config.md) | [架构图](contrib-config/contrib-config-architecture.html) | — | 6 个配置中心适配（apollo/etcd/k8s/...） |
| contrib-observability | [contrib-observability.md](contrib-observability/contrib-observability.md) | [架构图](contrib-observability/contrib-observability-architecture.html) | — | otel 日志/指标/链路、sentry、opensergo |
| contrib-middleware-encoding-transport | [contrib-middleware-encoding-transport.md](contrib-middleware-encoding-transport/contrib-middleware-encoding-transport.md) | [架构图](contrib-middleware-encoding-transport/contrib-middleware-encoding-transport-architecture.html) | — | jwt/validate 中间件、msgpack、mcp、polaris |

## 3. 域级机制细节

- **适配模式**：所有 contrib 实现都是对核心接口的薄封装，文件首行 `var _ 核心接口 = (*实现)(nil)` 编译期断言。
- **独立 go.mod**：每个 contrib 子包（etcd/otel/jwt/mcp 等）自带 `go.mod`，按需引入第三方重依赖。
- **外部边界**：所有注册中心/配置中心/可观测性后端本身"不在本仓库源码内"，仅客户端 SDK 在依赖里。
- **与核心解耦**：核心只定义接口，contrib 做实现；应用通过接口注入，可替换实现。
