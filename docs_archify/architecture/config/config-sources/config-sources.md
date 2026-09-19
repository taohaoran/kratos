# 配置来源实现（config-sources）

> 本文是 `config` 域下的叶子子系统文档。域级总览见 `../config.md`，核心抽象见 `../config-core/`，
> 本文只展开两个内置 Source 实现：`config/env`（环境变量）与 `config/file`（本地文件/目录）。
> 外部配置中心（etcd/nacos/apollo 等）见 `../../contrib/contrib-config/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 环境变量 Source | 把 `os.Environ()` 按 `KEY=VALUE` 切成 `KeyValue`，可按前缀过滤并去前缀 | `config/env/env.go:18`（`(*env).Load`） |
| 环境变量前缀过滤 | 支持多个前缀；命中后剥离前缀与下划线，如 `APP_FOO` → `FOO` | `config/env/env.go:29-36` |
| 环境变量 Watcher | 实现 `Watcher` 但永不推送，仅在 `Stop()` 时解除 `Next()` 阻塞 | `config/env/watcher.go:22` |
| 文件 Source（单文件） | 读取单个配置文件，按扩展名推断 Format | `config/file/file.go:23`（`loadFile`） |
| 文件 Source（目录） | 遍历目录下非隐藏文件、跳过子目录，每个文件一个 `KeyValue` | `config/file/file.go:44`（`loadDir`） |
| 扩展名格式推断 | 取文件名最后一个 `.` 后的字符串作为 Format（如 `app.yaml` → `yaml`） | `config/file/format.go:5` |
| 文件 Watcher | 基于 `fsnotify` 监听文件/目录变更，事件后重新读文件 | `config/file/watcher.go:36`（`Next`） |
| Rename 容错 | 收到 Rename 事件后重新 `Add` 监听路径（兼容编辑器原子替换写盘） | `config/file/watcher.go:41-46` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `env` 结构 | `config/env/env.go:10` | 持有 `prefixes []string`，实现 `config.Source` |
| `env.NewSource(prefixes ...string)` | `config/env/env.go:14` | 构造环境变量 Source，可变参数前缀 |
| `env.watcher` | `config/env/watcher.go:11` | 持有 `ctx/cancel`，`Next` 永久阻塞 |
| `file` 结构 | `config/file/file.go:14` | 持有 `path string`，实现 `config.Source` |
| `file.NewSource(path)` | `config/file/file.go:19` | 构造文件 Source，path 可为文件或目录 |
| `file.watcher` | `config/file/watcher.go:16` | 持有 `*file`、`*fsnotify.Watcher`、`ctx/cancel` |
| `format(name)` | `config/file/format.go:5` | 扩展名 → Format 字符串 |

## 3. 关键调用链

**调用链一：环境变量加载**
1. 应用 `config.New(config.WithSource(env.NewSource("APP_")))`（`config/env/env.go:14`）。
2. `(*env).Load()` 调 `e.load(os.Environ())`（`config/env/env.go:18-19`），对每个 `k=v` 用 `strings.Cut` 切分。
3. 有前缀时 `matchPrefix` 命中才保留，`TrimPrefix` 去前缀再去一个 `_`（`config/env/env.go:30-35`）。
4. 产出的 `KeyValue` 不带 Format，交给 config 核心的 `defaultDecoder` 把 `KEY` 按 `.` 展开（见 config-core）。

**调用链二：环境变量 watcher 行为**
1. `env.Watch()` 调 `NewWatcher()`，内部 `context.WithCancel(context.Background())`（`config/env/watcher.go:16-19`）。
2. `Next()` 直接 `<-w.ctx.Done()` 阻塞（`config/env/watcher.go:22-24`）——进程运行期间永不返回增量。
3. `Stop()` 调 `w.cancel()`，`Next()` 返回 `ctx.Err()`（即 `context.Canceled`），config 核心据此正常退出 watch 协程。
4. 语义：环境变量在进程启动后视为不变，不支持热更新。

**调用链三：文件热更新**
1. `file.Watch()` 调 `newWatcher(f)`：`fsnotify.NewWatcher()` + `fw.Add(f.path)` 注册监听（`config/file/watcher.go:24-33`）。
2. `Next()` 三路 `select`：`ctx.Done()` 退出、`fw.Events` 处理变更、`fw.Errors` 透传错误（`config/file/watcher.go:36-64`）。
3. 收到事件若是 `Rename`，重新 `Add` 事件路径（应对编辑器先 rename 再写的原子替换）（`config/file/watcher.go:41-46`）。
4. `time.Sleep(time.Millisecond)` 等落盘完成后 `w.f.loadFile(path)` 重读并返回单个 `KeyValue`（`config/file/watcher.go:56-61`）。
5. `Stop()` 先 `cancel()` 再 `fw.Close()` 释放 fsnotify 资源（`config/file/watcher.go:67-70`）。

## 4. 配置项

| 配置 / 参数 | 默认 / 行为 | 位置 |
|-------------|-------------|------|
| `env.NewSource(prefixes ...string)` | 不传前缀则加载全部环境变量；传前缀仅加载匹配项并剥离前缀 | `config/env/env.go:14` |
| `file.NewSource(path)` | path 是文件则单文件加载，是目录则遍历非隐藏文件 | `config/file/file.go:63` |
| 文件隐藏文件过滤 | 目录加载时跳过 `.` 开头文件与子目录 | `config/file/file.go:51` |
| fsnotify 重命名重监听 | 收到 Rename 事件且路径仍存在则重新 `Add` | `config/file/watcher.go:42-46` |
| 落盘等待 | 事件后固定 `time.Sleep(time.Millisecond)` 再读 | `config/file/watcher.go:56` |

## 5. 错误与重试语义

- **文件读取失败**：`loadFile` 的 `os.Open/io.ReadAll/Stat` 错误直接返回，config 核心 `Load` 启动期失败即退出。
- **fsnotify 错误**：`Next()` 从 `fw.Errors` 收到错误直接返回，由 config 核心的 watch 循环以 1 秒间隔重试（见 config-core）。
- **Rename 后路径消失**：`os.Stat` 报错时不重新 Add，下次事件再处理；不做重试。
- **env watcher 无错误路径**：除 `Stop()` 触发的 `context.Canceled` 外，`Next()` 永不返回。
- **不做重试**：文件 Source 本身不含重试逻辑，重试由 config 核心 watch 协程统一负责。

## 6. 并发细节

- **env watcher**：无 goroutine，仅一个 `ctx.Done()` channel 阻塞；`Stop()` 幂等，cancel 多次安全。
- **file watcher**：fsnotify 内部自有 goroutine 分发事件；本实现不额外起协程，`Next()` 在 config 核心的 watch 协程上阻塞接收。
- **资源关闭**：`Stop()` 同时 cancel ctx 并 `fw.Close()`，保证 `Next()` 两路 select 同时解除阻塞，无悬挂。
- **目录场景**：监听目录时，任一文件变更都按事件名定位到具体文件重读，不重新全量遍历目录。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `config/env/env.go`、`config/env/watcher.go`。
- `config/file/file.go`、`config/file/watcher.go`、`config/file/format.go`。

**Out-of-Scope（不在本仓库源码内）**
- `github.com/fsnotify/fsnotify`：跨平台文件系统事件库（第三方依赖）。
- 环境变量变更的外部触发（如容器注入新 env）：本实现不监听，视为不可变。
- 远程配置中心 Source：见 `contrib/config/*`。

## 8. 与相邻子系统交互

- **config 核心 → 本叶子**：核心通过 `config.Source` 接口调 `Load/Watch`，不感知具体实现。
- **本叶子 → fsnotify**：file watcher 直接依赖 fsnotify 的事件 channel。
- **本叶子 → encoding**：不直接依赖；file Source 只负责把文件字节 + Format 交给核心，由核心按 Format 取 codec 解码。
- **应用 → 本叶子**：应用通过 `config.WithSource(env.NewSource(...), file.NewSource(...))` 组合多个 Source。

## 9. 语言专项适配口径

- **并发模型**：env watcher 是"空实现 + context 阻塞"的极简模式，用 `context.CancelFunc` 而非自己起 goroutine；file watcher 把事件源（fsnotify）与消费（config 核心 watch 协程）解耦，事件通过 fsnotify 内部 channel 传递。
- **接口契约**：两个实现都 `var _ config.Source = (*file)(nil)` / `var _ config.Watcher = (*watcher)(nil)` 编译期断言接口满足，保证契约漂移在编译期暴露。
- **跨平台**：file watcher 依赖 fsnotify 抽象底层 inotify/kqueue/FSEvents，Go 层不处理平台差异；`project_windows_test.go` 等平台相关测试说明 CLI 侧有平台分支，本叶子无平台分支。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| config-sources 架构图 | `config-sources-architecture.html` | architecture | showcase |

本叶子不补时序图/数据流图：两个 Source 实现逻辑均为线性流程，已在第 3 节文字化，架构图足以表达组件边界与依赖。JSON IR 源文件位于 `json/` 目录。
