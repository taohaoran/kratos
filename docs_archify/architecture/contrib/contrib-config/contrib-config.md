# 配置中心生态适配（contrib-config）

> 本文是 `contrib` 域下的叶子子系统文档。域级总览见 `../contrib.md`，本文只展开 `contrib/config/*`
> 对核心 `config.Source/Watcher` 接口的各配置中心适配。内置 env/file 见 `config/config-sources/`。
>
> 源码基准：`github.com/go-kratos/kratos/v3`，commit `668db92c`（v3.0.0）。

## 1. 功能清单

| 能力 | 说明 | 源码路径 |
|------|------|----------|
| 配置中心 Source | 把 apollo/consul/etcd/k8s/nacos/polaris 适配成 `config.Source` | `contrib/config/*/config.go` |
| etcd 适配 | `New(client, WithPath, WithPrefix)` 读 etcd 键值 | `contrib/config/etcd/config.go:40` |
| etcd watcher | `clientv3.Watch` 监听路径变更，转 `[]*KeyValue` | `contrib/config/etcd/watcher.go:20` |
| apollo 适配 | 对接携程 apollo 配置中心 | `contrib/config/apollo/` |
| consul 适配 | 对接 consul KV | `contrib/config/consul/` |
| kubernetes 适配 | 对接 K8s ConfigMap/Secret | `contrib/config/kubernetes/` |
| nacos 适配 | 对接 nacos config | `contrib/config/nacos/` |
| polaris 适配 | 对接 polaris 配置 | `contrib/config/polaris/` |

## 2. 核心类型与接口清单

| 类型 / 函数 | 位置 | 职责 |
|-------------|------|------|
| `config.Source` 接口 | `config/source.go:11` | `Load()/Watch()` |
| `config.Watcher` 接口 | `config/source.go:17` | `Next()/Stop()` |
| `etcd.New(client, opts...)` | `contrib/config/etcd/config.go:40` | 构造 Source，path 必填 |
| `etcd.source` | `contrib/config/etcd/config.go:36` | 持有 client + options |
| `etcd.watcher` | `contrib/config/etcd/watcher.go:9` | 包装 `clientv3.WatchChan` |

## 3. 关键调用链

**调用链一：加载配置（以 etcd 为例）**
1. `src, err := etcd.New(client, etcd.WithPath("/app/config"))`，path 为空报错（`etcd/config.go:40-56`）。
2. 应用 `config.New(config.WithSource(src))`。
3. `Load()` 从 etcd 读 path（或前缀），转成 `[]*config.KeyValue{Key,Value,Format}`（`etcd/config.go:60`）。

**调用链二：热更新**
1. `Watch()` 调 `newWatcher(s)`，内部 `client.Watch(ctx, path, WithPrefix?)` 建 watchChan（`etcd/watcher.go:20-33`）。
2. `Next()` 从 watchChan 取响应，`resp.Err()` 透传错误，否则把变更键值转成 `[]*KeyValue`（`etcd/watcher.go:36-40`）。
3. 核心 config 收到增量后走 Merge/Resolve/Observer 流程（见 config-core）。
4. `Stop()` cancel ctx。

## 4. 配置项

| option | 默认 / 行为 | 位置 |
|--------|-------------|------|
| etcd `WithPath` | 必填，配置键路径 | `etcd/config.go:25` |
| etcd `WithPrefix` | false，是否前缀监听 | `etcd/config.go:30` |
| etcd `WithContext` | context.Background | `etcd/config.go:20` |

## 5. 错误与重试语义

- **path 缺失**：`New` 直接返回 `errors.New("path invalid")`。
- **watch 错误**：`Next()` 透传 `resp.Err()`，由 config 核心 watch 协程 1 秒重试。
- **无重试**：Source 本身不重试，重试在 config 核心。

## 6. 并发细节

- **watchChan**：etcd 客户端自有 goroutine 推送，本实现只读。
- **context 取消**：`Stop()` cancel ctx 关闭 watchChan。
- **无锁**：纯 channel 转发。

## 7. 系统边界

**In-Scope（本仓库源码内）**
- `contrib/config/*` 各适配。

**Out-of-Scope（不在本仓库源码内）**
- apollo/consul/etcd/k8s/nacos/polaris 服务端：外部系统。
- 各客户端 SDK：第三方依赖。

## 8. 与相邻子系统交互

- **config 核心 → 本叶子**：核心通过 `config.Source` 接口调用，不感知实现。
- **本叶子 → config 核心**：把后端变更转成 `[]*config.KeyValue` 喂给核心。
- **应用 → 本叶子**：`config.WithSource(etcd.New(...))`。

## 9. 语言专项适配口径

- **依赖倒置**：Source 接口在核心，实现在 contrib。
- **独立 go.mod**：每个 contrib/config 子包自带 go.mod，按需引入。
- **编译期断言**：`var _ config.Source = (*source)(nil)`。

## 10. 图表清单与质量

| 图 | 文件 | 类型 | archify 质量档 |
|----|------|------|----------------|
| contrib-config 架构图 | `contrib-config-architecture.html` | architecture | showcase |

JSON IR 源文件位于 `json/` 目录。
