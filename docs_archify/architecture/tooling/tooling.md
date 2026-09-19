# 工具链（tooling）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

tooling 域覆盖框架的工程工具：`cmd/kratos` 命令行脚手架（new/proto/run/upgrade 等子命令），
以及 `protoc-gen-go-errors`、`protoc-gen-go-http` 两个 protoc 插件（根据 proto 注解生成错误码与
HTTP 路由代码）。这些工具各自带独立 `go.mod`，作为独立二进制分发。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| kratos-cli | [kratos-cli.md](kratos-cli/kratos-cli.md) | [架构图](kratos-cli/kratos-cli-architecture.html) | — | kratos 脚手架 CLI（new/proto/run/upgrade） |
| protoc-gen-plugins | [protoc-gen-plugins.md](protoc-gen-plugins/protoc-gen-plugins.md) | [架构图](protoc-gen-plugins/protoc-gen-plugins-architecture.html) | [时序图](protoc-gen-plugins/protoc-gen-plugins-sequence.html) | errors/http 两个 protoc 插件 |

## 3. 域级机制细节

- **多二进制独立 go.mod**：`cmd/kratos`、`protoc-gen-go-errors`、`protoc-gen-go-http` 各自独立模块，不污染主框架依赖。
- **CLI 栈**：cobra + survey + huh 构建交互式命令。
- **插件模板**：`//go:embed` 嵌入 `.tpl`，用 `protogen.Options.Run` 读 stdin CodeGeneratorRequest、写 stdout。
