# FinSight Data Query Service

这是一个只读数据查询服务，面向 `data_api` token 提供最新交易日快照接口，不提供任何写库能力。

当前首批开放三张表：

- `stock_sector_fund_flow_daily`
- `stock_individual_fund_flow_daily`
- `stock_daily_kline_q`

服务侧已经接入：

- 独立 `data_api` token 权限域
- 单 token 严格串行访问
- 请求排队与额度限制
- 单设备绑定与一次换绑机会
- 用户侧额度查询接口 `/api/token/usage`

## 访问入口

数据接口控制台：

```text
http://0dsh4t9p.zjz-service.cn/data_api/
```

注意：

- 域名只使用 `0dsh4t9p.zjz-service.cn`
- 页面入口是 `/data_api/`
- SDK 默认内置该地址，终端用户通常不需要知道真实请求地址

## SDK 安装

```bash
pip install finsight-data
```

## SDK 快速开始

```python
from finsight_data import FinSightDataClient

client = FinSightDataClient(token="你的 data_api token")

sector = client.get_stock_sector_fund_flow_daily_latest()
stock = client.get_stock_individual_fund_flow_daily_latest()
kline = client.get_stock_daily_kline_q_latest()
usage = client.get_token_usage()
```

SDK 特性：

- 默认内置服务地址，不需要显式传 `base_url`
- 自动附带设备指纹，用于设备绑定和风控
- 同一 token 不允许并发请求

## 接口说明

### `get_stock_sector_fund_flow_daily_latest()`

作用：

- 查询 `stock_sector_fund_flow_daily` 最新交易日全量板块资金流向
- 默认按 `main_net_inflow_amount DESC` 排序

参数：

- `board_type`：板块类型过滤，支持 `行业`、`概念`、`板块`
- `keyword`：按板块代码或板块名称模糊过滤
- `offset`：偏移量
- `limit`：可选，不传默认全量
- `allow_rebind`：设备不一致时是否允许使用一次换绑机会

### `get_stock_individual_fund_flow_daily_latest()`

作用：

- 查询 `stock_individual_fund_flow_daily` 最新交易日全量个股资金流向
- 默认按 `main_net_inflow_amount DESC` 排序

参数：

- `codes`：股票代码列表，精确过滤
- `keyword`：股票代码或名称模糊过滤
- `offset`：偏移量
- `limit`：可选，不传默认全量
- `allow_rebind`：设备不一致时是否允许换绑

### `get_stock_daily_kline_q_latest()`

作用：

- 查询 `stock_daily_kline_q` 最新交易日全市场前复权日线 K 线
- 默认按 `amount DESC` 排序

参数：

- `codes`：股票代码列表，精确过滤
- `keyword`：股票代码或名称模糊过滤
- `offset`：偏移量
- `limit`：可选，不传默认全量
- `allow_rebind`：设备不一致时是否允许换绑

### `get_all_latest()`

作用：

- 一次拉取当前 token 已授权的全部最新交易日表
- 适合首次缓存预热或离线同步

### `get_token_usage()`

作用：

- 返回当前 token 的额度使用、剩余额度、重置时间、设备绑定状态
- 这是用户侧接口，不返回后台内部主键、原始设备指纹哈希、内部授权表等信息

## 返回结构

三个数据接口统一返回：

```json
{
  "ok": true,
  "table": "stock_daily_kline_q",
  "trade_date": "2026-04-28",
  "rows": [],
  "total_rows": 5300,
  "returned_rows": 5300,
  "offset": 0,
  "limit": null,
  "cache": {
    "source": "memory",
    "refreshed_at": "2026-04-28T11:20:00+08:00"
  },
  "token_scope": "data_api"
}
```

字段说明：

- `trade_date`：返回数据所属交易日
- `rows`：数据行列表
- `total_rows`：满足条件的总数
- `returned_rows`：本次实际返回条数
- `cache`：服务端缓存来源与刷新时间
- `token_scope`：固定为 `data_api`

`get_token_usage()` 返回：

```json
{
  "ok": true,
  "service": "finsight-data",
  "token_scope": "data_api",
  "account": {
    "username": "demo_user",
    "is_admin": false
  },
  "device_binding": {
    "mode": "bind_on_first_use",
    "is_bound": true,
    "rebind_remaining": 1
  },
  "quota_policy": {
    "concurrent_requests": {
      "limit": 1,
      "in_use": 0,
      "remaining": 1
    },
    "queue": {
      "limit": 3
    }
  },
  "summary": {
    "minute": {
      "limit": 5,
      "used": 2,
      "remaining": 3,
      "resets_at": "2026-04-28T11:31:00+08:00"
    },
    "hour": {
      "limit": 20,
      "used": 2,
      "remaining": 18,
      "resets_at": "2026-04-28T12:00:00+08:00"
    },
    "day": {
      "limit": 100,
      "used": 2,
      "remaining": 98,
      "resets_at": "2026-04-29T00:00:00+08:00"
    }
  },
  "endpoints": []
}
```

`endpoints` 中会逐接口返回：

- 接口名称
- SDK 方法名
- API 路径
- 对应数据表
- 用途说明
- 可用筛选参数
- 分钟、小时、天三级额度窗口的 `limit / used / remaining / resets_at`

## Token 和设备规则

- `dashboard` token 只给 `real_time_analyse/web/dashboard.html` 使用
- `data_api` token 只给 SDK 和 `/data_api` 相关接口使用
- 两类 token 严格隔离，不能共用
- 同一用户可以同时持有多个不同类型 token
- `data_api` token 默认单设备绑定
- 每个 token 默认提供一次换绑机会

换绑示例：

```python
client.get_stock_daily_kline_q_latest(allow_rebind=True)
```

## 并发与队列

服务设计原则：

- 单 token 并发上限为 `1`
- 如果检测到同一 token 同时建立多个连接，请求会直接拒绝
- 额度与队列信息通过 `/api/token/usage` 查询
- 数据接口只做读操作，并尽量走缓存和快照查询，降低数据库压力

因此不建议对同一个 token 开多线程、多协程或多进程并发拉取。

## 管理页面

管理入口在 `real_time_analyse/web/index.html` 的“用户与授权”页面。

当前逻辑：

- 同一用户可绑定多个 token
- 页面区分 `dashboard` 和 `data_api`
- 体验版 `data_api` token 支持按接口每天 `5` 次额度创建
- 管理员 token 不限额度

## SDK 发布目录

SDK 发布产物统一收敛到：

```text
data_query_service/sdk/releases/<version>/
```

目录规则：

- 每个版本一个目录
- 目录内只放该版本 wheel
- 同目录放一个 `README.md`
- 不同机器可以分别补充各自平台包

当前已整理版本：

```text
sdk/releases/0.1.3/
```

## 打包与上传

现在只保留两组发布脚本：

- `build_release.*`
- `upload_release.*`

含义：

- `build_release`：只负责当前机器打包，并把 wheel 放入 `releases/<version>/`
- `upload_release`：只负责上传指定版本目录中的全部 wheel

### 一、打包前准备

进入目录：

```text
data_query_service/sdk
```

确认 Python：

macOS / Linux：

```bash
python3 --version
```

Windows PowerShell：

```powershell
python --version
```

如需手动补依赖：

```bash
python3 -m pip install --upgrade build twine Cython requests setuptools wheel
```

Windows：

```powershell
python -m pip install --upgrade build twine Cython requests setuptools wheel
```

### 二、在各平台机器打包

#### macOS

```bash
cd /Users/tangyihan/Desktop/workspace/compose_files/service/data_query_service/sdk
./build_release.sh 0.1.3
```

#### Linux x86_64

```bash
docker run --rm --platform linux/amd64 \
  -v /Users/tangyihan/Desktop/workspace/compose_files/service/data_query_service/sdk:/work \
  -w /work \
  python:3.12-bookworm \
  bash -lc 'python build_release.py 0.1.3'
```

#### Linux aarch64

```bash
docker run --rm --platform linux/arm64/v8 \
  -v /Users/tangyihan/Desktop/workspace/compose_files/service/data_query_service/sdk:/work \
  -w /work \
  python:3.12-bookworm \
  bash -lc 'python build_release.py 0.1.3'
```

#### Windows `cmd`

```bat
cd /d C:\Users\YiHan Tang\Desktop\data_query_service\sdk
build_release.cmd 0.1.3
```

#### Windows PowerShell

```powershell
Set-Location 'C:\Users\YiHan Tang\Desktop\data_query_service\sdk'
python .\build_release.py 0.1.3
```

### 三、检查打包结果

打包完成后，所有 wheel 都应该汇总到：

```text
data_query_service/sdk/releases/0.1.3/
```

至少检查：

- 文件名版本号是否是 `0.1.3`
- 平台标签是否正确
- `README.md` 是否和目录内文件一致

如果怀疑文件名和内部版本不一致，可以核对 wheel 元数据：

```python
import zipfile

with zipfile.ZipFile("finsight_data-0.1.3-cp312-cp312-win_amd64.whl") as zf:
    for name in zf.namelist():
        if name.endswith(".dist-info/METADATA"):
            print(zf.read(name).decode("utf-8", "ignore"))
            break
```

重点确认：

- `Name: finsight-data`
- `Version: 0.1.3`

### 四、统一上传某个版本

当 `releases/0.1.3/` 已经收齐全部 wheel 后，再执行上传。

macOS / Linux：

```bash
cd /Users/tangyihan/Desktop/workspace/compose_files/service/data_query_service/sdk
./upload_release.sh 0.1.3
```

Windows `cmd`：

```bat
cd /d C:\Users\YiHan Tang\Desktop\data_query_service\sdk
upload_release.cmd 0.1.3
```

Windows PowerShell：

```powershell
Set-Location 'C:\Users\YiHan Tang\Desktop\data_query_service\sdk'
python .\upload_release.py 0.1.3
```

上传脚本行为：

- 读取 `releases/0.1.3/`
- 找出目录中的全部 `.whl`
- 对每个 wheel 执行上传
- 已存在的同名文件会自动跳过

### 五、推荐的标准顺序

1. 在 Windows 机器打 `win_amd64`
2. 在 macOS 机器打 `macosx_10_9_universal2`
3. 在 Linux x86_64 环境打 `manylinux_2_28_x86_64`
4. 在 Linux aarch64 环境打 `manylinux_2_28_aarch64`
5. 把所有 wheel 汇总到同一个 `releases/0.1.3/`
6. 在任意一台网络稳定的机器执行一次 `upload_release 0.1.3`

## 常见问题

### 1. PowerShell 执行 `./publish_pypi.sh` 报错

原因：

- PowerShell 不能直接这样执行 `sh` 脚本

正确方式：

```powershell
python .\build_release.py 0.1.3
python .\upload_release.py 0.1.3
```

### 2. 安装了 `twine` 但脚本仍提示找不到

原因：

- 安装 `twine` 的解释器，和执行脚本的解释器不是同一个

处理：

```powershell
python -m pip install --upgrade build twine Cython requests setuptools wheel
python .\build_release.py 0.1.3
```

### 3. 旧版 `0.1.2` 如何处理

当前本地发布目录已经删除 `0.1.2`。如果你说的是 PyPI 上已经公开发布过的旧版本，则需要去 PyPI 后台手动管理；这不属于本地打包脚本的处理范围。
