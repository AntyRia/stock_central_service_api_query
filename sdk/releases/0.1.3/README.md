# finsight-data 0.1.3

本目录存放 `0.1.3` 版本的全部 wheel 构建产物。

## 文件清单

| file | python | abi | platform |
| --- | --- | --- | --- |
| `finsight_data-0.1.3-cp312-cp312-manylinux_2_28_aarch64.whl` | `cp312` | `cp312` | `manylinux_2_28_aarch64` |
| `finsight_data-0.1.3-cp312-cp312-manylinux_2_28_x86_64.whl` | `cp312` | `cp312` | `manylinux_2_28_x86_64` |
| `finsight_data-0.1.3-cp312-cp312-win_amd64.whl` | `cp312` | `cp312` | `win_amd64` |
| `finsight_data-0.1.3-cp39-cp39-macosx_10_9_universal2.whl` | `cp39` | `cp39` | `macosx_10_9_universal2` |

## 本版本整理结果

- 本版本目录：`releases/0.1.3`
- 目录内所有 wheel 都应为 `0.1.3`
- 同一版本可以在不同机器上分批补充平台包
- 上传脚本会直接读取本目录下全部 `.whl` 文件

## 构建与上传

- 打包脚本：`build_release.py` / `build_release.cmd` / `build_release.sh`
- 上传脚本：`upload_release.py` / `upload_release.cmd` / `upload_release.sh`
- Linux 推荐使用 `python:3.12-bookworm` 环境打包
- 上传时只需要传版本号，脚本会自动上传本目录中的全部 wheel

## 本版本建议操作

1. 在各平台机器上执行 `build_release 0.1.3`，把生成的 wheel 汇总到本目录。
2. 检查本目录下 wheel 文件名、平台标签和内部 `METADATA` 版本。
3. 最后执行 `upload_release 0.1.3`，一次性上传本目录内全部 wheel。
