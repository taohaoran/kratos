# Kratos v3 系统级总览

> 源码基准：`github.com/go-kratos/kratos/v3`，Go 1.25.0，commit `668db92c`（v3.0.0），MIT License。
> 规模：约 321 个 Go 文件 / 4.5 万行；三个独立二进制入口 `cmd/kratos`、`cmd/protoc-gen-go-errors`、`cmd/protoc-gen-go-http`。

## 1. 项目概述

Kratos 是轻量级 Go 云原生微服务框架（README 原文定位："为 transport / middleware / registry / config / logging / encoding / 代码生成提供小而显式的 API，让应用聚焦业务逻辑"）。其架构范式是**接口契约 + 可选适配**：核心仓库只定义窄接口与少量内建实现，具体的注册中心、配置中心、可观测后端全部放在 `contrib/` 作为独立适配包，业务侧按需引入。

| 维度 | 事实 |
|------|------|
| 主语言 | Go 1.25（无 C++/TS） |
| 模块 | 根模块 `github.com/go-kratos/kratos/v3`；三个 cmd 各有独立 go.mod |
| 并发范式 | goroutine + errgroup + channel；`context.Context` 贯穿取消传播 |
| 代码生成 | Protobuf 驱动（protoc-gen-go-http / protoc-gen-go-errors） |
| 可观测性 | 内建基于标准库 `log/slog` 的门面；OpenTelemetry 在 contrib |
| 外部依赖边界 | 接口在本仓库，后端实现（etcd/consul/otel 等）在 contrib 或外部 |

## 2. 功能总览（按域）

| 域 | 叶子数 | 功能 |
|----|--------|------|
| app-runtime | 1 | App 生命周期：errgroup 并行启动 Server、注册到 Registrar、监听 OS 信号、优雅停止 |
| transport | 6 | 统一抽象 + gRPC server/client、HTTP server/client、binding/codec/stream/pprof |
| middleware | 3 | 可组合中间件栈与按 Operation 匹配；内建 recovery/ratelimit/circuitbreaker/logging/metadata/selector/validate |
| resilience-internal | 4 | SRE 熔断、BBR 自适应限流、endpoint/group/host 抽象、subset 一致性哈希与 matcher |
| discovery | 3 | registry 接口契约、selector 框架、p2c/wrr/random/ewma/version 过滤算法 |
| config | 2 | 多 Source 聚合热更新、点路径取值、env/file source |
| encoding | 1 | form/json/proto/protojson/xml/yaml 通过 init 自注册到全局 Codec |
| errors | 1 | 业务错误码模型（HTTP/gRPC 状态映射、metadata、wrap） |
| log | 1 | 基于 `log/slog` 的门面、level/filter/builder/context |
| metadata | 1 | 跨进程 key-value 透传（gRPC metadata / HTTP header） |
| tooling | 2 | `kratos` CLI 脚手架；两个 protoc 代码生成插件 |
| contrib | 4 | registry/config/observability/middleware-encoding-transport 生态适配 |

## 3. 解决的问题

| 用户痛点 | Kratos 解法 |
|----------|-------------|
| 微服务样板代码重复、启动/停止逻辑难写 | `App` 统一编排：errgroup 并行 Start、注册中心注册、信号监听、`context.WithoutCancel` 优雅停止 |
| HTTP 与 gRPC 两套 API 割裂 | 统一 `Server`/`Transporter` 抽象，业务 Handler 与具体协议解耦 |
| 中间件散落在各框架、难以组合 | 标准 `Middleware` 函数签名 + `middleware.ServerClient` 双向栈，recovery/限流/熔断/日志/校验可任意拼装 |
| 注册中心/配置中心锁定单一厂商 | `Registrar`/`Config` 等窄接口，contrib 提供 etcd/consul/k8s/nacos/apollo 等适配，业务侧只依赖接口 |
| 错误码在 HTTP/gRPC/日志间语义不一致 | 内建 `errors` 模型，一次定义同时映射 HTTP 状态与 gRPC code，支持 metadata 透传 |
| 配置热更新需自己写 watcher | `config` 多 Source 聚合 + 增量 watcher 协程 + 原子 Value 快照，业务无感 |
| 服务发现与负载均衡策略硬编码 | selector 插件化：p2c 抖动最小、wrr 加权、ewma 响应时延、version 过滤 |
| 多套日志库替换成本高 | 直接基于标准库 `log/slog`，Handler 可替换，上下文日志挂在 ctx |

## 4. 系统边界

- **上边界（用户/第三方接入）**：业务开发者 import 本框架；上游调用方通过 HTTP/gRPC 访问 Server。这些调用方本身不在本仓库内。
- **下边界（基础设施）**：注册中心、配置中心、日志后端、监控后端、Tracing 后端——全部通过 contrib 适配，**不在本仓库核心源码内**。
- **内边界（本仓库 vs 扩展）**：根包 + transport/middleware/internal/selector/registry/config/encoding/errors/log/metadata 是核心契约与内建实现；`contrib/` 是可选生态；`cmd/` 是三个独立工具二进制。
- **侧边界**：`internal/` 包按 Go 规则仅框架内可用，外部业务代码不可 import。
- **不做什么**：不内置某一特定注册中心/配置中心的客户端；不内置 Web 框架式模板渲染；不内置服务 mesh sidecar；不替业务做业务路由与持久层 ORM。

## 5. 系统架构图说明

![系统架构图](system-architecture.html)

主路径自左向右：**调用方 → transport 传输层 → middleware 中间件链 → 业务 Service → 框架基础库**。
- 上排是请求主链路：transport 负责协议解码与路由，middleware 横切（恢复/限流/熔断/日志），业务 Service 只关心领域逻辑。
- 下排是支撑面：`selector + registry` 提供注册与寻址（transport 客户端侧调用），`框架基础库` 提供 errors/encoding/log/metadata 等被业务与中间件共用的原子能力。
- `contrib 生态` 通过虚线连到 selector/registry，表示它只实现核心接口、不改变核心契约。

## 6. 核心时序图说明

![App 生命周期时序图](system-app-lifecycle-sequence.html)

按时间分四段：
1. **启动（m1–m4）**：`main` 调 `App.Run`，App 用 errgroup 并行 Start 各 Server 并暴露 Endpoint，随后在 `registrarTimeout`（默认 10s）内把实例注册到 Registrar。
2. **就绪待命（m5）**：App 调 `signal.Notify` 阻塞等待 SIGTERM/SIGINT/SIGQUIT。
3. **停止信号到达（m6）**：收到信号触发 Stop。
4. **优雅退出（m7–m9）**：先 Deregister 摘除流量，再用 `context.WithoutCancel` 剥离父 ctx 取消后按 `stopTimeout` 优雅 Stop 各 Server，最后 Run 返回。

## 7. 系统数据流图说明

![请求数据流图](system-dataflow.html)

一次请求沿主链前进、沿回程返回：
- **接入层**：transport 解码请求，把 `Transporter` 挂进 ctx。
- **中间件层**：恢复/日志/限流/熔断按栈序包裹，`ctx` 透传 metadata 与 trace 信息。
- **业务层**：Handler 处理业务；若需调下游，由 selector 选节点、registry 寻址。
- **基础能力**：encoding 把业务结果序列化为 wire 格式，响应经 transport 原路返回客户端。
