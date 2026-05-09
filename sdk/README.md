# finsight-data

`finsight-data` 是 FinSight 只读数据接口的 Python SDK，只提供最新交易日快照查询能力，不提供任何写库能力。

SDK 默认内置服务地址，正常使用时不需要手动传 API 域名；同时会自动携带设备指纹，用于单设备绑定、异常设备识别和恶意请求封禁。

## 安装要求

- Python `3.9` 及以上
- 需要有效的 `data_api` 类型 token
- 同一个 token 不允许并发请求

安装：

```bash
pip install finsight-data
```

## 快速开始

```python
from finsight_data import FinSightDataClient

client = FinSightDataClient(token="YOUR_DATA_API_TOKEN")

sector = client.get_stock_sector_fund_flow_daily_latest()
stock = client.get_stock_individual_fund_flow_daily_latest()
kline = client.get_stock_daily_kline_q_latest()
usage = client.get_token_usage()
```

## 初始化参数

```python
FinSightDataClient(
    token="YOUR_DATA_API_TOKEN",
    timeout=20,
    base_url=None,
    device_fingerprint=None,
)
```

参数说明：

- `token`：必填，数据接口 token
- `timeout`：请求超时秒数，默认 `20`
- `base_url`：可选，默认使用 SDK 内置地址；通常不需要手动传
- `device_fingerprint`：可选，自定义设备指纹；默认由 SDK 自动生成

## 可用接口

### 1. `get_stock_sector_fund_flow_daily_latest()`

用途：

- 查询 `stock_sector_fund_flow_daily` 表最新交易日的全部板块资金流向数据
- 默认按 `main_net_inflow_amount DESC` 排序

参数：

- `board_type`：板块类型过滤，支持 `行业`、`概念`、`板块`
- `keyword`：按板块代码或板块名称模糊过滤
- `offset`：偏移量，默认 `0`
- `limit`：返回条数上限；默认不传时为全量返回
- `allow_rebind`：设备不一致时是否允许消耗一次换绑机会，默认 `False`

示例：

```python
data = client.get_stock_sector_fund_flow_daily_latest(
    board_type="行业",
    keyword="半导体",
)
```

### 2. `get_stock_individual_fund_flow_daily_latest()`

用途：

- 查询 `stock_individual_fund_flow_daily` 表最新交易日的全部个股资金流向数据
- 默认按 `main_net_inflow_amount DESC` 排序

参数：

- `codes`：股票代码列表，精确过滤
- `keyword`：按股票代码或名称模糊过滤
- `offset`：偏移量，默认 `0`
- `limit`：返回条数上限；默认不传时为全量返回
- `allow_rebind`：设备不一致时是否允许换绑

示例：

```python
data = client.get_stock_individual_fund_flow_daily_latest(
    codes=["600519", "000858"],
)
```

### 3. `get_stock_daily_kline_q_latest()`

用途：

- 查询 `stock_daily_kline_q` 表最新交易日的全市场前复权日线 K 线
- 默认按 `amount DESC` 排序

参数：

- `codes`：股票代码列表，精确过滤
- `keyword`：按股票代码或名称模糊过滤
- `offset`：偏移量，默认 `0`
- `limit`：返回条数上限；默认不传时为全量返回
- `allow_rebind`：设备不一致时是否允许换绑

示例：

```python
data = client.get_stock_daily_kline_q_latest(keyword="贵州茅台")
```

### 4. `get_all_latest()`

用途：

- 一次性拉取当前 token 已授权的全部最新交易日表
- 适合首次全量同步、本地缓存初始化

参数：

- `allow_rebind`：设备不一致时是否允许换绑

### 5. `get_token_usage()`

用途：

- 查询当前 token 的额度使用情况、剩余额度、重置时间、设备绑定状态
- 这是给最终用户看的接口，不返回后台内部主键、设备哈希摘要、授权表原始配置等内部信息

参数：

- `allow_rebind`：设备不一致时是否允许换绑

示例：

```python
usage = client.get_token_usage()
print(usage["summary"]["day"]["remaining"])
```

## 统一返回结构

三个数据接口都返回相同的外层结构：

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
    "refreshed_at": "2026-04-28T11:20:00+0800"
  },
  "token_scope": "data_api"
}
```

字段说明：

- `trade_date`：本次返回的数据交易日
- `rows`：实际数据行
- `total_rows`：满足筛选条件的总行数
- `returned_rows`：本次实际返回行数
- `cache`：服务端缓存信息
- `token_scope`：固定应为 `data_api`

## `get_token_usage()` 返回结构

示例：

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

重点字段：

- `account`：当前 token 所属用户
- `device_binding`：当前 token 的设备绑定状态和剩余换绑次数
- `quota_policy.concurrent_requests.limit`：并发限制，当前应为 `1`
- `summary`：分钟、小时、天三级总额度汇总
- `endpoints`：逐接口额度统计，包含接口名、用途、筛选项和剩余额度

## 设备绑定与换绑

规则：

- token 首次成功请求后会绑定当前设备
- 已绑定后，换到新设备请求会直接拒绝，不返回数据
- 同一 token 默认仅允许一次换绑机会
- 需要换绑时，在单次请求里显式传 `allow_rebind=True`

示例：

```python
data = client.get_stock_daily_kline_q_latest(allow_rebind=True)
```

## 并发限制

`data_api` token 的并发规则非常严格：

- 同一个 token 同时只能有 `1` 个活跃请求
- 如果检测到同一 token 并发建立多个连接，请求会被直接拒绝
- 队列上限和配额可以通过 `get_token_usage()` 查看

因此不建议对同一个 token 做多线程/多协程并发拉取。

## 版本发布产物目录

SDK wheel 统一存放在：

```text
releases/<version>/
```

例如：

```text
releases/0.1.3/
```

规则：

- 一个版本一个目录
- 目录内放该版本全部平台 wheel
- 同目录有一个 `README.md`，记录该版本的 wheel 清单
- 可以在不同机器上分批构建，再把 wheel 汇总到同一版本目录

## 开发者打包与上传

本项目只保留两组脚本：

- `build_release.py` / `build_release.sh` / `build_release.cmd`
- `upload_release.py` / `upload_release.sh` / `upload_release.cmd`

完整的逐平台构建和上传说明，请看：

- 项目总文档：`../README.md`
- 发布目录索引：`releases/README.md`

## 常见错误

### 1. `ModuleNotFoundError: No module named 'twine'`

原因：

- 你执行脚本时用的解释器，和安装 `twine` 时用的解释器不是同一个

处理：

```powershell
python -m pip install --upgrade build twine Cython requests setuptools wheel
python .\build_release.py 0.1.3
```

### 2. PowerShell 里执行 `./publish_pypi.sh` 失败

原因：

- `sh` 脚本不是 Windows PowerShell 的调用方式

正确方式：

```powershell
python .\build_release.py 0.1.3
python .\upload_release.py 0.1.3
```

或在 `cmd` 中执行：

```bat
build_release.cmd 0.1.3
upload_release.cmd 0.1.3
```
