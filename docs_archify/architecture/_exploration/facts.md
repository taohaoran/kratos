# kratos 项目探查事实（facts.md）

> 一次性只读探查结论，供各分片/叶子共享，禁止各自重扫全仓库。

## 1. 身份
- 模块名：`github.com/go-kratos/kratos/v3`
- 语言/版本：Go 1.25.0
- git commit：`668db92c` "deps: upgrade kratos version to v3.0.0 (#3845)"（v3.0.0）
- 定位（README 原文）：Kratos 是轻量级 Go 云原生微服务框架，为 transport / middleware / registry / config / logging / encoding / 代码生成提供小而显式的 API，让应用聚焦业务逻辑。
- License：MIT

## 2. 规模
- Go 文件数（排除 third_party/.git）：**321**
- 总行数：**约 45,357 行**
- 各目录文件数：cmd 41 / config 20 / contrib 95 / encoding 20 / errors 7 / internal 30 / log 12 / metadata 2 / middleware 16 / registry 1 / selector 22 / transport 50
- 多二进制入口（cmd/）：
  - `cmd/kratos`：命令行脚手架（new/run/proto/upgrade/change），独立 go.mod
  - `cmd/protoc-gen-go-errors`：protoc 错误码生成插件
  - `cmd/protoc-gen-go-http`：protoc HTTP 路由生成插件
  - 三个 cmd 各有独立 go.mod（workspace 外的独立模块）

## 3. 结构（一层）
根包（package kratos）：`app.go` `options.go` `version.go`
- `transport/`：抽象接口 `transport.go` + `grpc/`（server/client/balancer/resolver/interceptor/codec）+ `http/`（server/client/router/binding/codec/stream/filter/redirect/resolver/path/calloption/pprof/status）
- `middleware/`：`middleware.go` + 子包 recovery/logging/metadata/ratelimit/recovery/selector/validate/circuitbreaker
- `internal/`：circuitbreaker(sre)、ratelimit(bbr)、endpoint、group、host、httputil、matcher、subset、context
- `selector/`：selector.go/balancer.go/peer.go/options.go/global.go/default_*.go + 算法 p2c/wrr/random + node(direct/ewma) + filter(version)
- `registry/`：仅 registry.go（Registrar/Discerner/ServiceInstance 接口）
- `config/`：config.go/source.go/reader.go/value.go/options.go/merge.go + env/ file/
- `encoding/`：encoding.go + form/json/proto/protojson/xml/yaml（init 自注册）
- `errors/`：errors.go/types.go/wrap.go + errors.proto/errors.pb.go
- `log/`：log.go/handler.go/level.go/filter.go/builder.go/context.go（基于标准库 log/slog）
- `metadata/`：metadata.go（透传 key-value）
- `contrib/`：可选集成生态——registry(etcd/consul/k8s/nacos/eureka/zookeeper/servicecomb/polaris/discovery)、config(apollo/consul/etcd/k8s/nacos/polaris)、encoding(json/msgpack)、middleware(jwt/validate)、otel(log/metrics/tracing)、errortracker(sentry)、opensergo、polaris、transport(mcp)

## 4. 功能清单（README Feature）
- API-first：Protobuf + 生成 HTTP/gRPC 代码
- 统一 transport 层（HTTP + gRPC）
- 可组合中间件：recovery/logging/validation/tracing/metrics/auth 等
- 可插拔 registry / config / encoding
- 基于标准库 log/slog 的日志，contrib 提供 OpenTelemetry 扩展
- 一致的 metadata / errors / validation / OpenAPI / 代码生成工作流
- contrib 生态：registry/config/middleware/encoding/可观测性集成

## 5. 关键机制（已实读源码确认）
- **App 生命周期**（app.go:83 Run）：buildInstance → beforeStart → 用 errgroup 并行 Start 各 Server（wg.Wait 确保 start 已发起）→ Registrar.Register（registrarTimeout=10s）→ afterStart → signal.Notify 监听 SIGTERM/SIGQUIT/SIGINT → 收到信号调 Stop → Stop 时 beforeStop + Deregister + cancel ctx。优雅停止用 `context.WithoutCancel` + stopTimeout。
- **transport 抽象**（transport/transport.go）：`Server`{Start,Stop}、`Endpointer`{Endpoint()*url.URL,error}、`Transporter`{Kind/Endpoint/Operation/RequestHeader/ReplyHeader}、`Header`。server/client transport 分别挂 context。encoding 包通过 `_ "..."` import init 自注册到 encoding.GlobalCodec。
- **internal 边界**：internal/ 仅框架内部使用，提供 sre 熔断、bbr 限流、endpoint/group/host 抽象、subset 一致性哈希子集、matcher 中间件匹配、httputil、context。

## 6. 约束
- 项目根**已存在 docs/ 目录** → 输出根必须为 `docs_archify/architecture/`（不是 docs/architecture/）
- 文档语言一律简体中文；文件名/目录名英文短横线
- 外部系统/第三方组件标注"不在本仓库源码内"
- 主语言：Go（无 C++/TS），按 language-go.md 口径：并发模型/多二进制/internal 边界/可观测性边界

## 7. 工具链
- ARCHIFY_CLI=`/tmp/archify-upstream/archify/bin/archify.mjs`（Node v22，≥18）
- 出图脚本：`<skill_root>/scripts/render-diagram.sh <type> <x.json> <out.html>`（自动 showcase→standard 回退）
- 链接校验：`<skill_root>/scripts/check-links.py <输出根>`
- skill_root=`/Users/thr/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills/archify-codebase-analysis`

## 8. 输出根
`/Users/thr/Documents/AllProjects/OpenSource/kratos/docs_archify/architecture/`
