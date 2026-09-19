# 配置核心（config-core）

> 本文是 `config` 域下的叶子子系统文档。域级总览见 `../config.md`，本文只展开配置的核心抽象、
> 合并/解析/快照与热更新机制；两个内置 Source 实现（env/file）见 `../config-sources/`，
> 外部配置中心适配见 `../../contrib/contrib-config/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| Config 抽象接口 | 定义 `Load/Scan/Value/Watch/Close` 五个方法，是应用与配置系统的唯一入口 | `config/config.go:26` |
| 多 Source 聚合加载 | 按 `WithSource` 顺序逐个 `Source.Load()`，合并进同一 reader | `config/config.go:92`（`(*config).Load`） |
| 增量热更新 watch | 每个 Source 起一个 watcher 协程，`Next()` 拉增量、合并、解析、比对、回调 | `config/config.go:58`（`(*config).watch`） |
| 点路径取值 | 以 `a.b.c` 分隔逐层下钻 `map[string]any`，返回原子快照 `Value` | `config/reader.go:134`（`readValue`） |
| 类型转换 Value | `Bool/Int/Float/String/Duration/Slice/Map/Scan` 一组类型化访问器 | `config/value.go:21`（`Value` 接口） |
| 原子值快照 | `atomicValue` 内嵌 `sync/atomic.Value`，热更新时原地 `Store` 不重建引用 | `config/value.go:34` |
| 合并策略 | `defaultMerge` 递归深合并 map，源覆盖目标，map 嵌套递归合并 | `config/merge.go:5` |
| 占位符解析 | `${key:default}` 递归替换字符串/数组/map 内的引用 | `config/options.go:108`（`defaultResolver`） |
| 泛型 Get | 按目标类型 `T` 直接取值，省去手写类型断言 | `config/config.go:157`（`Get[T]`） |
| 预置 codec 依赖 | 包级 import 匿名引入 json/proto/xml/yaml codec，开箱即用 | `config/config.go:11-14` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `Config` 接口 | `config/config.go:26` | 应用侧门面：加载、扫描、取值、监听、关闭 |
| `KeyValue` 结构 | `config/source.go:4` | 单个配置条目：`Key/Value/Format`；Format 为空表示纯单值 |
| `Source` 接口 | `config/source.go:11` | 配置来源抽象：`Load()` 全量 + `Watch()` 增量句柄 |
| `Watcher` 接口 | `config/source.go:17` | 增量推送抽象：`Next()` 阻塞取增量、`Stop()` 停止 |
| `Reader` 接口 | `config/reader.go:18` | 内部存储抽象：`Merge/Value/Source/Resolve` |
| `Value` 接口 | `config/value.go:21` | 类型化取值 + 原子读写（`Load/Store`） |
| `atomicValue` | `config/value.go:34` | `Value` 主要实现，包 `atomic.Value`，并发安全 |
| `errValue` | `config/value.go:179` | 取值失败的哨兵实现，所有方法返回预置错误 |
| `Decoder/Resolver/Merge` 函数类型 | `config/options.go:13/16/19` | 三个可替换策略点：解码、占位符解析、合并 |
| `Observer` 类型 | `config/config.go:23` | `Watch(key, o)` 的回调签名 `func(string, Value)` |
| `ErrNotFound` | `config/config.go:20` | key 不存在时的哨兵错误 |

## 3. 关键调用链

**调用链一：应用启动加载配置（`Load`）**
1. `config.New(WithSource(env, file))` 构造时只建 reader，不加载（`config/config.go:43`）。
2. 应用调用 `(*config).Load()`，遍历 `opts.sources`：先 `src.Load()` 得全量 `[]*KeyValue`，再 `c.reader.Merge(kvs...)` 解码合并（`config/config.go:93-104`）。
3. 每个 source 接着 `src.Watch()` 拿到 `Watcher`，`go c.watch(w)` 起后台协程，把 watcher 存入 `c.watchers`（`config/config.go:105-111`）。
4. 全部 source 合并完后统一 `c.reader.Resolve()` 解析占位符（`config/config.go:113`）。
5. 失败即返回错误并终止后续 source 加载，不做部分成功。

**调用链二：热更新增量推送（`watch` 协程）**
1. 协程 `for { kvs, err := w.Next() }` 阻塞等待 source 变更（`config/config.go:60`）。
2. `err` 为 `context.Canceled` 时 `log.Info` 后 `return` 退出协程（`config/config.go:62-65`）；其他错误 `time.Sleep(time.Second)` 后重试，不退出。
3. 拿到增量后 `c.reader.Merge(kvs...)` + `c.reader.Resolve()`，任一步失败只记日志并 `continue`，不污染已有配置（`config/config.go:70-77`）。
4. 遍历 `c.cached`（已被应用 `Value()` 过的 key 快照）：新值与旧值 `reflect.DeepEqual` 不同且类型一致才 `v.Store(n.Load())` 原地刷新，并回调该 key 的 Observer（`config/config.go:78-88`）。

**调用链三：点路径取值与类型转换（`Value`）**
1. `(*config).Value(key)` 先查 `c.cached` 命中即返回；未命中查 `c.reader.Value(key)`，命中则缓存进 `c.cached`（`config/config.go:120-127`）。
2. `reader.Value` 在锁内 `readValue(r.values, path)`：按 `.` 切分 key，逐层 `map[string]any` 下钻，末层包成 `atomicValue`（`config/reader.go:61-65`、`config/reader.go:134-158`）。
3. 应用调 `v.Int()` 时，`atomicValue` 对底层 `any` 做类型 switch：数值直接转、字符串走 `strconv.ParseInt`，否则 `typeAssertError`（`config/value.go:54-84`）。

## 4. 配置项

| option / 常量 | 默认 / 行为 | 位置 |
|---------------|-------------|------|
| `WithSource(s ...Source)` | 配置来源列表，可多个，按调用顺序合并（后者覆盖前者） | `config/options.go:37` |
| `WithDecoder(d Decoder)` | 默认 `defaultDecoder`：Format 非空走 codec.Unmarshal，空则把 `key` 按 `.` 展开成嵌套 map | `config/options.go:78` |
| `WithResolver(r Resolver)` | 默认 `defaultResolver`：递归替换 `${key:default}` | `config/options.go:108` |
| `WithResolveActualTypes(bool)` | 开启后把占位符解析结果按字面量转 bool/int/float，而非保留字符串 | `config/options.go:56` |
| `WithMergeFunc(m Merge)` | 默认 `defaultMerge` 递归深合并 | `config/merge.go:5` |
| 占位符语法 | `${key}` 或 `${key:default}`，正则 ``\${(.*?)}`` | `config/options.go:187` |

## 5. 错误与重试语义

- **加载失败**：`Load()` 中任一 source 的 `Load/Merge/Watch` 出错即 `return err`，启动期快速失败，不部分加载。
- **watch 失败重试**：`watch` 协程对非 `context.Canceled` 错误采用固定 1 秒 `time.Sleep` 重试（无指数退避），合并/解析失败只记日志 `continue` 跳过本轮，保留旧配置。
- **取消传播**：`context.Canceled` 是 watcher 主动 `Stop()` 的退出信号，协程静默退出，视为正常关闭。
- **取值错误**：key 不存在返回 `errValue`，所有访问方法返回 `ErrNotFound`；类型不匹配返回 `typeAssertError`，不 panic。
- **不做自动重试**：占位符解析、类型转换失败均返回 error 给调用方，框架不自动重试。

## 6. 并发细节

- **watch 协程**：每个 Source 一个 `go c.watch(w)`（`config/config.go:111`），由 `Close()` 遍历 `c.watchers` 调 `Stop()` 触发 `ctx.Done()` 退出；协程数 = source 数，正常关闭无泄漏。
- **共享状态**：`cached`、`observers` 用 `sync.Map`（`config/config.go:37-38`），读写无锁；`reader.values` 用 `sync.Mutex` 保护（`config/reader.go:28`）。
- **原子快照**：热更新比对时 `atomicValue.Store` 原地替换，应用持有的 `Value` 引用不失效即可看到新值；比对用 `reflect.DeepEqual` 保证只在真变化时回调。
- **临界区**：`reader.Merge` 先 `cloneMap`（gob 深拷贝）在锁外合并，最后一次性加锁替换 `r.values`（`config/reader.go:55-57`），缩短持锁时间。
- **context 传递**：watcher 内部用 `context.WithCancel(context.Background())`，与业务 context 解耦，`Stop()` 即取消。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `config/` 包核心：`config.go/source.go/reader.go/value.go/options.go/merge.go`。
- 内置 Source：`config/env`、`config/file`（详见 `config-sources` 叶子）。

**Out-of-Scope（不在本仓库源码内）**
- 配置中心 Source 实现（apollo/etcd/nacos 等）：见 `contrib/config/*`，属生态适配。
- `encoding.Codec` 的具体实现（json/yaml/proto 等）：见 `encoding-framework` 叶子。
- 业务配置结构体定义与 `protojson` 序列化：依赖 `google.golang.org/protobuf`（第三方，不在本仓库源码内）。
- 本叶子不负责 Source 实现本身，只定义 `Source/Watcher` 接口契约。

## 8. 与相邻子系统交互

- **应用代码 → 本叶子**：应用通过 `config.New(...).Load()` 装配，用 `Value(key).Int()` 或 `Get[T]` 取值。
- **本叶子 → encoding 域**：`defaultDecoder` 通过 `encoding.GetCodec(Format)` 按格式名取编解码器反序列化配置文本（`config/options.go:93`）。
- **本叶子 → Source 实现**：调用 `Source.Load/Watch`；env/file 在本仓库内，其余在 contrib。
- **本叶子 → log 域**：watch/加载全过程用 `log.Info/Error/Debug` 打点，不直接依赖可观测后端。

## 9. 语言专项适配口径

- **并发模型**：典型"每 source 一个 watcher goroutine + sync.Map 无锁缓存 + mutex 保护内部 map"模式；取消通过 `context.CancelFunc` 显式触发，watch 协程在 `Next()` 上阻塞，停止时由 `Close()` 统一回收，无泄漏风险。
- **控制器模式差异**：非 K8s Reconcile 式幂等重入；热更新是 source 主动 push（`Next()`），框架侧只做合并+diff+回调，不做对象重建或状态机回滚。
- **依赖方向**：`config` 核心只依赖 `encoding` 接口注册表与 `log`，不反向依赖任何 Source 实现（依赖倒置：Source 实现依赖 `config.Source` 接口）。
- **泛型**：`Get[T]` 是 v3 引入的泛型取值入口，按类型 switch 分发，体现 Go 1.25 泛型在框架 API 层的收敛使用。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| config-core 架构图 | `config-core-architecture.html` | architecture | showcase |
| config-core 热更新数据流 | `config-core-dataflow.html` | dataflow | standard（垂直流标签需 labelDy 微调，多次迭代后降 standard 一次通过，如实披露） |

JSON IR 源文件位于 `json/` 目录。
