# SDK Releases

本目录按版本归档 `finsight-data` 的 wheel 发布产物。

## 目录规则

- 每个版本一个子目录，例如 `0.1.3/`
- 子目录内放该版本的全部 `.whl`
- 子目录内必须有一个 `README.md`，记录 wheel 清单、平台标签和发布说明
- 同一版本可以在不同机器上分批补充平台包，最后统一上传

## 当前本地版本

- `0.1.3`

## 标准使用方式

1. 先进入 `data_query_service/sdk`
2. 在不同平台机器上分别执行 `build_release`
3. 把生成的 wheel 汇总到 `releases/<version>/`
4. 检查该目录下 `README.md` 是否与 wheel 清单一致
5. 最后执行 `upload_release <version>`，一次性上传该目录全部 wheel

## 目录示例

```text
releases/
  README.md
  0.1.3/
    README.md
    finsight_data-0.1.3-...whl
    finsight_data-0.1.3-...whl
```
