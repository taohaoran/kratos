# 配置（config）域总览

> 本域包含以下叶子子系统；各叶子详情见对应文档。
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 域职责

config 域负责运行期配置的加载、合并、监听与热更新。核心是一个可同时挂载多个 `config.Source` 的配置中心，
通过点路径 `Get[T]` 取值，内置 `${key:default}` 占位符解析，并在任意 source 变更时自动重新 Merge、
Resolve 并通知观察者。内置 source 有环境变量与文件两类，其余配置中心由 contrib 域提供适配。

## 2. 叶子索引

| 叶子 | 文档 | 架构图 | 时序图 / 数据流图 | 职责一句话 |
|------|------|--------|-------------------|-----------|
| config-core | [config-core.md](config-core/config-core.md) | [架构图](config-core/config-core-architecture.html) | [数据流图](config-core/config-core-dataflow.html) | Config 接口、watch 循环、Merge/Resolve/Get |
| config-sources | [config-sources.md](config-sources/config-sources.md) | [架构图](config-sources/config-sources-architecture.html) | — | 内置 env / file 两种 Source 与 watcher |

## 3. 域级机制细节

- **多 source 合并**：`Merge` 对多个 source 的 `[]*KeyValue` 递归深合并，后者覆盖前者。
- **watch 循环**：每个 source 起一个独立 goroutine 调 `Next()`，非 Canceled 错误 sleep 1s 重试，收到变更即触发全量重载。
- **默认解析器**：`${key:default}` 语法，正则提取变量、递归解析、支持嵌套。
- **并发**：值用 `atomic.Value` 存放（`atomicValue`），无锁读；reader 写时复制。
