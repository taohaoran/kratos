# Kratos v3 系统架构文档

> 基于 Kratos 源码（`github.com/go-kratos/kratos/v3`，Go 1.25.0，commit `668db92c` / v3.0.0，约 321 个 Go 文件 / 4.5 万行）深度分析产出，
> 覆盖系统级、**12 个域、29 个叶子子系统**的功能、问题域、系统边界、架构图、时序图、数据流图与状态机图。
> 所有图表由 archify 渲染为自包含交互式 HTML（每图约 800KB，零外部依赖）。
> 输出目录说明：项目根已存在 `docs/`，故本套文档输出在 `docs_archify/architecture/`，与项目自有文档隔离。

## 文档导航

### 系统级
| 文档 | 说明 | 图表 |
|------|------|------|
| [system-overview.md](system-overview.md) | 功能总览、解决的问题、系统边界、核心代码映射 | [系统架构图](system-architecture.html) · [App 生命周期时序图](system-app-lifecycle-sequence.html) · [请求数据流图](system-dataflow.html) |

### app-runtime（app-runtime/）
| 子系统 | 文档 | 架构图 | 时序图 | 职责一句话 |
|--------|------|--------|--------|-----------|
| 域总览 | [app-runtime.md](app-runtime/app-runtime.md) | — | — | 应用生命周期编排 |
| app-lifecycle | [app-lifecycle.md](app-runtime/app-lifecycle/app-lifecycle.md) | [架构图](app-runtime/app-lifecycle/app-lifecycle-architecture.html) | [时序图](app-runtime/app-lifecycle/app-lifecycle-sequence.html) | errgroup 并行启动、信号监听、优雅停止 |

### transport（transport/）
| 子系统 | 文档 | 架构图 | 时序图 | 数据流图 |
|--------|------|--------|--------|----------|
| 域总览 | [transport.md](transport/transport.md) | — | — | — |
| transport-abstraction | [transport-abstraction.md](transport/transport-abstraction/transport-abstraction.md) | [架构图](transport/transport-abstraction/transport-abstraction-architecture.html) | — | — |
| grpc-server | [grpc-server.md](transport/grpc-server/grpc-server.md) | [架构图](transport/grpc-server/grpc-server-architecture.html) | [时序图](transport/grpc-server/grpc-server-sequence.html) | — |
| grpc-client | [grpc-client.md](transport/grpc-client/grpc-client.md) | [架构图](transport/grpc-client/grpc-client-architecture.html) | — | [数据流图](transport/grpc-client/grpc-client-dataflow.html) |
| http-server | [http-server.md](transport/http-server/http-server.md) | [架构图](transport/http-server/http-server-architecture.html) | [时序图](transport/http-server/http-server-sequence.html) | — |
| http-client | [http-client.md](transport/http-client/http-client.md) | [架构图](transport/http-client/http-client-architecture.html) | [时序图](transport/http-client/http-client-sequence.html) | — |
| http-binding-codec | [http-binding-codec.md](transport/http-binding-codec/http-binding-codec.md) | [架构图](transport/http-binding-codec/http-binding-codec-architecture.html) | — | — |

### middleware（middleware/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [middleware.md](middleware/middleware.md) | — | — |
| middleware-stack | [middleware-stack.md](middleware/middleware-stack/middleware-stack.md) | [架构图](middleware/middleware-stack/middleware-stack-architecture.html) | 中间件栈组装与按操作匹配 |
| builtin-resilience-middleware | [builtin-resilience-middleware.md](middleware/builtin-resilience-middleware/builtin-resilience-middleware.md) | [架构图](middleware/builtin-resilience-middleware/builtin-resilience-middleware-architecture.html) | recovery/ratelimit/circuitbreaker |
| builtin-observability-middleware | [builtin-observability-middleware.md](middleware/builtin-observability-middleware/builtin-observability-middleware.md) | [架构图](middleware/builtin-observability-middleware/builtin-observability-middleware-architecture.html) | logging/metadata/selector/validate |

### resilience-internal（resilience-internal/）
| 子系统 | 文档 | 架构图 | 状态机/数据流 | 职责一句话 |
|--------|------|--------|---------------|-----------|
| 域总览 | [resilience-internal.md](resilience-internal/resilience-internal.md) | — | — | — |
| sre-circuitbreaker | [sre-circuitbreaker.md](resilience-internal/sre-circuitbreaker/sre-circuitbreaker.md) | [架构图](resilience-internal/sre-circuitbreaker/sre-circuitbreaker-architecture.html) | [状态机图](resilience-internal/sre-circuitbreaker/sre-circuitbreaker-lifecycle.html) | Google SRE 并发量预估熔断 |
| bbr-ratelimit | [bbr-ratelimit.md](resilience-internal/bbr-ratelimit/bbr-ratelimit.md) | [架构图](resilience-internal/bbr-ratelimit/bbr-ratelimit-architecture.html) | [数据流图](resilience-internal/bbr-ratelimit/bbr-ratelimit-dataflow.html) | 基于 RT/CPU 的自适应 BBR 限流 |
| endpoint-group-host | [endpoint-group-host.md](resilience-internal/endpoint-group-host/endpoint-group-host.md) | [架构图](resilience-internal/endpoint-group-host/endpoint-group-host-architecture.html) | — | endpoint/group/host 抽象 |
| subset-matcher-httputil | [subset-matcher-httputil.md](resilience-internal/subset-matcher-httputil/subset-matcher-httputil.md) | [架构图](resilience-internal/subset-matcher-httputil/subset-matcher-httputil-architecture.html) | — | 一致性哈希子集/中间件匹配/httputil/context |

### discovery（discovery/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [discovery.md](discovery/discovery.md) | — | — |
| registry-interface | [registry-interface.md](discovery/registry-interface/registry-interface.md) | [架构图](discovery/registry-interface/registry-interface-architecture.html) | Registrar/Discerner/ServiceInstance 契约 |
| selector-framework | [selector-framework.md](discovery/selector-framework/selector-framework.md) | [架构图](discovery/selector-framework/selector-framework-architecture.html) | 选择器框架与 Peer/Balancer |
| selector-algorithms | [selector-algorithms.md](discovery/selector-algorithms/selector-algorithms.md) | [架构图](discovery/selector-algorithms/selector-algorithms-architecture.html) | p2c/wrr/random/ewma/version 过滤 |

### config（config/）
| 子系统 | 文档 | 架构图 | 数据流图 | 职责一句话 |
|--------|------|--------|----------|-----------|
| 域总览 | [config.md](config/config.md) | — | — | — |
| config-core | [config-core.md](config/config-core/config-core.md) | [架构图](config/config-core/config-core-architecture.html) | [数据流图](config/config-core/config-core-dataflow.html) | 多 Source 聚合、热更新、点路径取值 |
| config-sources | [config-sources.md](config/config-sources/config-sources.md) | [架构图](config/config-sources/config-sources-architecture.html) | — | env 与 file 两个内建 Source |

### encoding（encoding/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [encoding.md](encoding/encoding.md) | — | — |
| encoding-framework | [encoding-framework.md](encoding/encoding-framework/encoding-framework.md) | [架构图](encoding/encoding-framework/encoding-framework-architecture.html) | init 自注册的 Codec 注册表 |

### errors（errors/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [errors.md](errors/errors.md) | — | — |
| errors-model | [errors-model.md](errors/errors-model/errors-model.md) | [架构图](errors/errors-model/errors-model-architecture.html) | 业务错误码模型与 proto 定义 |

### log（log/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [log.md](log/log.md) | — | — |
| slog-logging | [slog-logging.md](log/slog-logging/slog-logging.md) | [架构图](log/slog-logging/slog-logging-architecture.html) | 基于标准库 log/slog 的日志门面 |

### metadata（metadata/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [metadata.md](metadata/metadata.md) | — | — |
| metadata-propagation | [metadata-propagation.md](metadata/metadata-propagation/metadata-propagation.md) | [架构图](metadata/metadata-propagation/metadata-propagation-architecture.html) | 跨进程 key-value 透传 |

### tooling（tooling/）
| 子系统 | 文档 | 架构图 | 时序图 | 职责一句话 |
|--------|------|--------|--------|-----------|
| 域总览 | [tooling.md](tooling/tooling.md) | — | — | — |
| kratos-cli | [kratos-cli.md](tooling/kratos-cli/kratos-cli.md) | [架构图](tooling/kratos-cli/kratos-cli-architecture.html) | — | 项目脚手架 new/run/proto/upgrade |
| protoc-gen-plugins | [protoc-gen-plugins.md](tooling/protoc-gen-plugins/protoc-gen-plugins.md) | [架构图](tooling/protoc-gen-plugins/protoc-gen-plugins-architecture.html) | [时序图](tooling/protoc-gen-plugins/protoc-gen-plugins-sequence.html) | errors/http 两个 protoc 插件 |

### contrib（contrib/）
| 子系统 | 文档 | 架构图 | 职责一句话 |
|--------|------|--------|-----------|
| 域总览 | [contrib.md](contrib/contrib.md) | — | — |
| contrib-registry | [contrib-registry.md](contrib/contrib-registry/contrib-registry.md) | [架构图](contrib/contrib-registry/contrib-registry-architecture.html) | etcd/consul/k8s/nacos 等注册中心适配 |
| contrib-config | [contrib-config.md](contrib/contrib-config/contrib-config.md) | [架构图](contrib/contrib-config/contrib-config-architecture.html) | apollo/consul/etcd 等配置中心适配 |
| contrib-observability | [contrib-observability.md](contrib/contrib-observability/contrib-observability.md) | [架构图](contrib/contrib-observability/contrib-observability-architecture.html) | OpenTelemetry/sentry/opensergo 适配 |
| contrib-middleware-encoding-transport | [contrib-middleware-encoding-transport.md](contrib/contrib-middleware-encoding-transport/contrib-middleware-encoding-transport.md) | [架构图](contrib/contrib-middleware-encoding-transport/contrib-middleware-encoding-transport-architecture.html) | jwt/validate/msgpack/mcp/polaris |

## 产出统计

| 层级 | MD | HTML | JSON IR |
|------|----|------|---------|
| 系统级 | 2（README + system-overview） | 3 | 3 |
| 域总览 | 12 | — | — |
| 叶子子系统 | 29 | 38 | 38 |
| **合计** | **43** | **41** | **41** |

- 叶子总数：**29**（规划 29，全部交付）。
- 图表总数：41 张，全部 render 退出码 0、自包含 HTML（约 800KB）。
- 质量档位：showcase 29 张 / standard 12 张（standard 均已在对应叶子 MD 第 10 节披露降档原因：竖向边标签压节点、跨列长对角穿节点、region 边框贴合等布局约束，多轮迭代后仍无法过 showcase 严格校验，按规程降 standard）。

## 覆盖范围与说明

- **已覆盖**：根包 app 生命周期、transport（grpc/http server+client+binding/codec/stream）、middleware 全栈、internal 韧性（SRE/BBR/endpoint/group/host/subset/matcher）、registry 接口、selector 框架与全部算法、config 核心与 source、encoding 自注册、errors 模型、slog 日志、metadata 透传、kratos CLI 与两个 protoc 插件、contrib 四大生态类。
- **未逐实现展开**：contrib 下各注册中心/配置中心/可观测后端只以代表实现（etcd 等）展开调用链，其余按"接口适配模式共性"描述；这些后端本身"不在本仓库源码内"。
- **源码事实校正**：SRE 熔断器源码实现为 Open/Closed 两态（无半开），与通用认知不同，已在 `sre-circuitbreaker` 叶子如实说明。
- **Go 语言适配口径**：并发模型（goroutine/errgroup/channel/sync.Primitive）、多二进制入口（cmd/kratos 与两个 protoc 插件各独立 go.mod）、`internal/` 包边界、可观测性边界（log/slog 门面 + contrib/otel）已落到每个叶子 MD 第 9 节。
- **探查目录**：`_exploration/` 为一次性只读探查结论（facts.md），不计入正式交付索引。
