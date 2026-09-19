# protoc 代码生成插件（protoc-gen-plugins）

> 本文是 `tooling` 域下的叶子子系统文档。域级总览见 `../tooling.md`，本文只展开
> `cmd/protoc-gen-go-errors` 与 `cmd/protoc-gen-go-http` 两个 protoc 插件的模板与生成逻辑。
>
> 源码基准：`github.com/go-kratos/kratos/cmd/protoc-gen-go-errors/v3` 与 `.../protoc-gen-go-http/v3`
> （各自独立 go.mod），commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 插件入口 | 基于 `protogen.Options.Run`，从 stdin 读 CodeGeneratorRequest，stdout 写 CodeGeneratorResponse | `cmd/protoc-gen-go-errors/main.go:13`、`cmd/protoc-gen-go-http/main.go:17` |
| proto3 optional 支持 | 声明 `FEATURE_PROTO3_OPTIONAL` | `errors/main.go:23`、`http/main.go:26` |
| 错误码枚举生成 | 扫描 `.proto` 中的 enum，读 `errors.default_code`/`errors.code` 扩展，渲染成 `_errors.pb.go` | `cmd/protoc-gen-go-errors/errors.go:25` |
| 错误码范围校验 | code 必须在 (0, 600]，否则 panic | `errors.go:68-70`、`errors.go:80-82` |
| 错误模板渲染 | `//go:embed errorsTemplate.tpl` 用 text/template 渲染 | `cmd/protoc-gen-go-errors/template.go:9` |
| HTTP 路由生成 | 扫描 service 的 `google.api.HttpRule`，渲染成 `_http.pb.go` | `cmd/protoc-gen-go-http/http.go:27` |
| HTTP rule 构建 | `buildHTTPRule` 把 google.api.HttpRule 转成 method 描述（path/body/路径变量） | `http.go:105` |
| 路径变量提取 | `buildPathVars`/`replacePath`/`pathTemplateRegex` 处理 `{name=...}` 模板 | `http.go:270-316` |
| omitempty 选项 | 命令行 `--omitempty`/`--omitempty_prefix`，无 HTTP rule 的文件跳过 | `http/main.go:12-14`、`http.go:28` |
| 版本打印 | `--version` flag | 两插件各自 `version.go` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `generateFile(gen, file)` | `errors/errors.go:25`、`http/http.go:27` | 按输入文件生成一个 `.pb.go` |
| `errorInfo` / `errorWrapper` | `errors/template.go:12-23` | 模板数据结构，每个 enum value 一条 |
| `errorWrapper.execute()` | `errors/template.go:25` | 解析并执行 text/template |
| `genErrorsReason` | `errors/errors.go:62` | 读 enum 扩展、校验 code、收集 errorInfo |
| `buildHTTPRule` | `http/http.go:105` | 把 `annotations.HttpRule` 转成 `methodDesc` |
| `methodDesc` | `http.go` 内 | 模板渲染用的 HTTP 方法描述 |
| `errors.E_DefaultCode` / `E_Code` | `errors/errors/errors.pb.go` | protobuf 扩展句柄（1108/1109） |

## 3. 关键调用链

**调用链一：protoc-gen-go-errors 生成错误码**
1. protoc 通过子进程启动 `protoc-gen-go-errors`，把 `CodeGeneratorRequest` 写进插件 stdin（`errors/main.go:22`）。
2. `protogen.Options.Run` 解析后回调 `func(gen *protogen.Plugin)`，遍历 `gen.Files`，对 `f.Generate` 的文件调 `generateFile`（`errors/main.go:24-29`）。
3. `generateFile` 跳过无 enum 的文件；有 enum 则建 `_errors.pb.go`，写 `package` 与 `SupportPackageIsVersion1` 兼容断言（`errors.go:25-48`）。
4. `genErrorsReason` 对每个 enum：先读 `errors.E_DefaultCode` 作默认 code，再对每个 enum value 读 `errors.E_Code` 覆盖；code 越界 panic（`errors.go:63-82`）。
5. 每个有 code 的 value 收集成 `errorInfo{Name,Value,CamelValue,HTTPCode,Comment}`，最后 `g.P(ew.execute())` 用模板渲染（`errors.go:92-105`）。
6. 若全文件没有任何 enum value 带 `errors.code`，`g.Skip()` 跳过输出（`errors.go:57-59`）。

**调用链二：protoc-gen-go-http 生成路由**
1. 同样从 stdin 读请求，`generateFile` 跳过无 service 或 `omitempty && !hasHTTPRule` 的文件（`http.go:27-28`）。
2. `genService` 遍历 service 的 method，对带 `google.api.HttpRule` 的方法调 `buildHTTPRule`（`http.go:65-82`）。
3. `buildHTTPRule` 从 rule 取 get/post/put/delete/patch 路径与 body 字段，`buildPathVars` 提取路径变量，组装成 `methodDesc`（`http.go:105`、`http.go:270`）。
4. 最终模板渲染成注册 HTTP 路由的 Go 代码。

**调用链三：模板执行**
1. `//go:embed errorsTemplate.tpl` 在编译期把模板文件嵌入二进制（`errors/template.go:9-10`）。
2. `execute()` 每次 `template.New(...).Parse(...)` 后 `Execute(buf, e)` 渲染（`template.go:25-35`）——每次生成都重新解析模板（模板小，开销可忽略）。

## 4. 配置项

| flag / 选项 | 默认 / 行为 | 位置 |
|-------------|-------------|------|
| `--version` | 打印版本退出 | 两插件 main.go |
| `--omitempty` | true：无 google.api rule 的文件不生成 _http.pb.go | `http/main.go:13` |
| `--omitempty_prefix` | 空字符串：路径前缀过滤 | `http/main.go:14` |
| 错误码范围 | (0, 600]，越界 panic | `errors.go:68` |
| 生成文件名 | `<GeneratedFilenamePrefix>_errors.pb.go` / `_http.pb.go` | `errors.go:29`、`http.go` |

## 5. 错误与重试语义

- **编译期 panic**：错误码越界、模板解析失败都直接 panic，protogen 把 panic 转成非零退出码反馈给 protoc——代码生成是开发期工具，错误要立刻暴露。
- **跳过空文件**：无 enum / 无 service / 无 HTTP rule 时 `g.Skip()`，不生成空文件，不报错。
- **不重试**：代码生成是一次性批量处理，失败即失败。
- **stdin 解析**：protogen 库负责解析，格式错误由 protogen 报错。

## 6. 并发细节

- **单进程批量**：插件一次进程调用处理一个 protoc 调用内的所有文件，串行遍历 `gen.Files`，无 goroutine。
- **无共享状态**：每次 `execute()` 现场 parse+execute 模板，无缓存。
- **stdin/stdout**：与 protoc 通过标准字节流通信，无并发。
- **go:embed**：模板在编译期嵌入，运行期只读。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `cmd/protoc-gen-go-errors/`、`cmd/protoc-gen-go-http/` 两个独立模块。

**Out-of-Scope（不在本仓库源码内）**
- `google.golang.org/protobuf/compiler/protogen`、`types/pluginpb`：protoc 插件库。
- `google.golang.org/genproto/googleapis/api/annotations`：google.api.HttpRule 定义。
- `protoc` 主程序本身：外部二进制，通过 stdin/stdout 调用。
- 生成代码在用户项目中的落盘与编译：由用户构建系统负责。

## 8. 与相邻子系统交互

- **kratos-cli → 本叶子**：`kratos proto client/server` 调 protoc 时间接使用这两个插件；`kratos upgrade` 负责安装。
- **errors 域 ↔ 本叶子**：生成的 `_errors.pb.go` import `github.com/go-kratos/kratos/v3/errors`，生成的构造函数返回 `*errors.Error`（`errors.go:18`）。
- **transport/http 域 ↔ 本叶子**：生成的 `_http.pb.go` 提供 HTTP 路由注册函数，被 transport/http server 使用。
- **业务 .proto → 本叶子**：业务在 .proto 里用 `errors.code` 扩展与 `google.api.http` 注解驱动生成。

## 9. 语言专项适配口径

- **多二进制独立 go.mod**：三个 cmd（kratos CLI、protoc-gen-go-errors、protoc-gen-go-http）各有独立 go.mod，互相不依赖主框架，避免代码生成工具拉入运行时依赖——这是 Go 多模块工作区的标准做法。
- **protogen 插件模型**：Google 官方 protoc 插件协议（stdin CodeGeneratorRequest / stdout CodeGeneratorResponse），两个插件都是无状态短生命周期进程，与 K8s 控制器模式无关。
- **go:embed 模板**：v3 用 `//go:embed` 把 `.tpl` 嵌入二进制，发布单文件插件，无需额外分发模板文件。
- **编译期兼容断言**：生成代码里 `const _ = errors.SupportPackageIsVersion1`，若用户项目引用了不兼容版本的 kratos errors 包，编译期报错。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| protoc-gen-plugins 架构图 | `protoc-gen-plugins-architecture.html` | architecture | standard（多组件标签宽度多轮微调后降 standard 一次通过，如实披露） |
| protoc 插件调用时序 | `protoc-gen-plugins-sequence.html` | sequence | showcase |

JSON IR 源文件位于 `json/` 目录。
