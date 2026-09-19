# kratos 命令行脚手架（kratos-cli）

> 本文是 `tooling` 域下的叶子子系统文档。域级总览见 `../tooling.md`，本文只展开 `cmd/kratos`
> 这个 CLI 工具本身；protoc 代码生成插件见 `../protoc-gen-plugins/`。
>
> 源码基准：`github.com/go-kratos/kratos/cmd/kratos/v3`（独立模块），commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 根命令装配 | cobra rootCmd，版本 `v3.0.0`，注册五个子命令 | `cmd/kratos/main.go:15`、`cmd/kratos/main.go:22` |
| 新建项目 | `kratos new <name>`：从模板仓库（service/admin）克隆脚手架 | `cmd/kratos/internal/project/project.go:25` |
| 项目内加服务 | `--nomod` 模式在已有 go.mod 仓库内加子项目 | `cmd/kratos/internal/project/project.go:84-108` |
| 交互式模板选择 | huh TUI 选 service/admin/custom，custom 提示输 URL | `cmd/kratos/internal/project/project.go:164-205` |
| 加 proto 模板 | `kratos proto add helloworld/v1/hello.proto`：按路径生成 .proto 骨架 | `cmd/kratos/internal/proto/add/add.go:15` |
| 生成 proto client | `kratos proto client`：调 protoc 生成客户端桩 | `cmd/kratos/internal/proto/client/client.go:16` |
| 生成 server 实现 | `kratos proto server`：用 emicklei/proto 解析 .proto 生成 service 骨架 | `cmd/kratos/internal/proto/server/server.go:17` |
| 本地运行 | `kratos run`：自动找 `cmd/*` 目录，封装 `go run` | `cmd/kratos/internal/run/run.go:15` |
| 更新日志 | `kratos changelog [dev|version]`：调 GitHub API 取 release/commits | `cmd/kratos/internal/change/change.go:11` |
| 升级工具 | `kratos upgrade`：`go install`  kratos CLI + protoc 插件到 latest | `cmd/kratos/internal/upgrade/upgrade.go:12` |
| 公共工具 | `base`：GoInstall/ModulePath/repo/path/vcs_url 等辅助 | `cmd/kratos/internal/base/install.go` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `rootCmd` | `cmd/kratos/main.go:15` | cobra 根命令 |
| `CmdNew` | `internal/project/project.go:25` | `new` 子命令 |
| `CmdProto` | `internal/proto/proto.go:12` | `proto` 父命令，挂 add/client/server |
| `CmdRun` | `internal/run/run.go:15` | `run` 子命令 |
| `CmdChange` | `internal/change/change.go:11` | `changelog` 子命令 |
| `CmdUpgrade` | `internal/upgrade/upgrade.go:12` | `upgrade` 子命令 |
| `Project` | `internal/project/new.go:12` | 项目模板，`New/Add` 克隆仓库 |
| `GoInstall(path...)` | `internal/base/install.go:11` | 逐个 `go install`，缺 `@` 补 `@latest` |
| `projects` 表 | `internal/project/project.go:19-22` | 内置模板仓库 URL 映射（service/admin） |

## 3. 关键调用链

**调用链一：`kratos new` 建项目**
1. 根 `main()` 执行 `rootCmd.Execute()`，cobra 路由到 `CmdNew.Run`（`cmd/kratos/main.go:31`）。
2. `run` 解析项目名（无参则 survey 交互询问），`processProjectParams` 把 `~/xxx`、相对路径转成绝对路径（`internal/project/project.go:46-70`、`project.go:124-147`）。
3. 无 `--repo` 时 `selectRepo()` 用 huh TUI 选模板（service/admin/custom）（`project.go:164-205`）。
4. 起 goroutine 执行 `p.New(ctx, workingDir, repoURL, branch)`：若目标已存在则询问是否覆盖，`git clone` 模板仓库（`project.go:83-109`、`new.go:20-40`）。
5. 外层 `select` 监听 `ctx.Done()`（60s 超时）与 `done` channel，超时打印 "project creation timed out"（`project.go:110-121`）。

**调用链二：`kratos run` 本地运行**
1. `Run` 用 `cmd.ArgsLenAtDash` 拆分 `--` 前后参数（`internal/run/run.go:82-88`）。
2. 未指定目录时 `findCMD(base)` 向上最多 5 层找含 `cmd` 目录的位置，找到多个用 survey 让用户选（`run.go:90-138`）。
3. 最终 `exec.Command("go", "run", dir, programArgs...)`，stdout/stderr 直连终端（`run.go:71-79`）。

**调用链三：`kratos upgrade` 升级工具**
1. `Run` 调 `base.GoInstall(...)`，传入 6 个工具路径（kratos CLI、protoc-gen-go-http、protoc-gen-go-errors、protoc-gen-go、protoc-gen-go-grpc、protoc-gen-openapi）（`internal/upgrade/upgrade.go:20-28`）。
2. `GoInstall` 逐个 `exec.Command("go", "install", p)`，缺 `@` 补 `@latest`，任一失败即返回（`internal/base/install.go:11-24`）。

## 4. 配置项

| flag / 环境变量 | 默认 / 行为 | 位置 |
|------------------|-------------|------|
| `new --repo/-r` | 自定义模板仓库 URL | `project.go:40` |
| `new --branch/-b` | 模板分支 | `project.go:41` |
| `new --timeout/-t` | 默认 `60s` | `project.go:42` |
| `new --nomod` | 保留现有 go.mod 模式 | `project.go:43` |
| `run -w/--work` | 目标工作目录 | `run.go:24` |
| `proto client --proto-path/-p` | 默认 `./third_party`，可用 `KRATOS_PROTO_PATH` 覆盖 | `client.go:25-30` |
| `proto server --target-dir/-t` | 默认 `internal/service` | `server.go:24` |
| `changelog --repo-url/-r` | 默认 `https://github.com/go-kratos/kratos.git`，可用 `KRATOS_REPO` 覆盖 | `change.go:24-27` |
| `GITHUB_TOKEN` 环境变量 | changelog 调用 GitHub API 的 token | `change.go:28` |

## 5. 错误与重试语义

- **外部命令失败**：`exec.Command.Run()` 错误打印红色 ERROR，不退出整个 CLI（单命令失败即返回）。
- **超时**：`new` 用 `context.WithTimeout` 包裹，60s 超时打印 "project creation timed out" 并退出（`project.go:55`、`project.go:111-115`）。
- **覆盖确认**：目标目录已存在时 survey 询问是否覆盖，用户拒绝则返回不创建（`new.go:20-35`）。
- **GitHub API 错误**：changelog 把 API 返回直接打印，不重试。
- **交互式中断**：survey/huh 询问失败或用户取消直接 `return`，非零退出码由 cobra 处理。
- **无重试**：所有外部调用（git/go/GitHub）失败即失败，不自动重试。

## 6. 并发细节

- **new 的 goroutine + select**：克隆仓库在独立 goroutine 执行，主 goroutine `select` 同时等超时与完成（`project.go:83-121`）——典型"带超时的阻塞任务"模式。
- **exec 子进程**：`go run`/`go install`/`git clone` 都是阻塞子进程，stdout/stderr 直连终端，不做并发。
- **无共享状态**：各子命令无包级可变状态（flag 变量在 init 绑定后只读）。
- **平台分支**：`project_windows_test.go`/`project_linux_test.go` 说明路径分隔符有平台差异，源码用 `filepath` 抽象。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `cmd/kratos/` 整个独立模块（main.go + internal/）。

**Out-of-Scope（不在本仓库源码内）**
- `github.com/spf13/cobra`、`github.com/AlecAivazis/survey/v2`、`github.com/charmbracelet/huh`、`github.com/emicklei/proto`、`golang.org/x/mod`：CLI 框架与解析库。
- 模板仓库 `kratos-layout`/`kratos-admin`：远程 git 仓库，不在本仓库源码内。
- `protoc` 与各 protoc 插件：外部可执行文件，CLI 只通过 `os/exec` 调用。
- GitHub REST API：远程服务，不在本仓库源码内。

## 8. 与相邻子系统交互

- **应用开发者 → 本叶子**：本地安装 `kratos` 后，用 new/proto/run 在项目脚手架与代码生成间工作。
- **本叶子 → 主框架模块**：本 CLI 是**独立 go.mod**，运行期不 import `github.com/go-kratos/kratos/v3`；它只生成符合框架约定的项目骨架。
- **本叶子 → protoc-gen 插件**：`upgrade` 命令把 protoc-gen-go-http/errors 一并安装；`proto client/server` 实际调 protoc 间接用这些插件。
- **本叶子 → 外部工具**：通过 `os/exec` 调 git/go/protoc。

## 9. 语言专项适配口径

- **多二进制与独立 go.mod**：`cmd/kratos` 是三个独立二进制之一（另两个 protoc-gen-go-errors/proto-gen-go-http），各自 `go.mod`，不与主框架共享依赖——这是 Go 多模块工作区的典型布局，避免 CLI 工具依赖膨胀主框架。
- **cobra 子命令树**：根命令在 `init()` 里 `AddCommand`，子命令各自挂自己的子命令（proto 挂 add/client/server），与 K8s 控制器模式无关，是纯 CLI 命令分发。
- **os/exec 边界**：CLI 作为"工具编排层"，通过子进程调用 git/go/protoc，不直接链接这些工具的库——进程隔离，工具版本可独立升级。
- **TUI 交互**：v3 同时用了 survey（经典提示）与 huh（Bubble Tea TUI），`selectRepo` 用 huh 的条件显隐组实现"选 custom 才显示 URL 输入"。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| kratos-cli 架构图 | `kratos-cli-architecture.html` | architecture | showcase |

本叶子不补时序图：CLI 是请求-响应式命令分发，各子命令流程已在第 3 节文字化；无跨服务异步管道。JSON IR 源文件位于 `json/` 目录。
