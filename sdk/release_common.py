from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_DIR = SCRIPT_DIR / "build_release_work"
DIST_DIR = SCRIPT_DIR / "dist"
RELEASES_DIR = SCRIPT_DIR / "releases"
PKG_NAME = "finsight_data"
SRC_DIR = BUILD_DIR / "compiled_src"
REPOSITORY_URL = os.environ.get("PYPI_REPOSITORY_URL", "https://upload.pypi.org/legacy/")
DEFAULT_PYPI_USERNAME = "__token__"
# SECURITY: PyPI token must come from env var PYPI_TOKEN. Never hardcode.
# Generate a new token at https://pypi.org/manage/account/token/ and export it
# before running upload_release.py:  export PYPI_TOKEN="pypi-..."
DEFAULT_PYPI_TOKEN = os.environ.get("PYPI_TOKEN", "")
REQUIRED_PYTHON = (3, 12)


def run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or SCRIPT_DIR, env=env, check=True)


def ensure_python312() -> None:
    if sys.version_info[:2] != REQUIRED_PYTHON:
        required = ".".join(str(item) for item in REQUIRED_PYTHON)
        current = ".".join(str(item) for item in sys.version_info[:3])
        raise SystemExit(f"build must run on Python {required}, current={current}")


def detect_wheel_platform() -> str:
    sys_platform = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    machine = platform.machine().lower()
    if sys_platform.startswith("macosx_"):
        return sys_platform
    if sys_platform.startswith(("linux_", "manylinux_")):
        if machine in {"x86_64", "amd64"}:
            return "manylinux_2_28_x86_64"
        if machine in {"aarch64", "arm64"}:
            return "manylinux_2_28_aarch64"
        return sys_platform
    if sys_platform.startswith("win"):
        if machine in {"amd64", "x86_64"}:
            return "win_amd64"
        if machine in {"arm64", "aarch64"}:
            return "win_arm64"
        return sys_platform
    return sys_platform


def update_version(new_version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new_version):
        raise SystemExit(f"invalid version: {new_version}")

    pyproject = SCRIPT_DIR / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{new_version}"', text, count=1)
    if count != 1:
        raise SystemExit("failed to update pyproject version")
    pyproject.write_text(text, encoding="utf-8")

    init_file = SCRIPT_DIR / PKG_NAME / "__init__.py"
    init_text = init_file.read_text(encoding="utf-8")
    init_text, count = re.subn(r'(?m)^__version__ = "[^"]+"$', f'__version__ = "{new_version}"', init_text, count=1)
    if count != 1:
        raise SystemExit("failed to update package __version__")
    init_file.write_text(init_text, encoding="utf-8")


def ensure_build_dependencies() -> None:
    run([sys.executable, "-m", "pip", "install", "--upgrade", "build", "twine", "Cython", "requests", "setuptools>=70.1", "wheel"])


def ensure_upload_dependencies() -> None:
    run([sys.executable, "-m", "pip", "install", "--upgrade", "twine", "requests"])


def release_dir(version: str) -> Path:
    return RELEASES_DIR / version


def prepare_release_dir(version: str) -> Path:
    target = release_dir(version)
    target.mkdir(parents=True, exist_ok=True)
    return target


def prepare_build_tree() -> None:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SCRIPT_DIR / "pyproject.toml", BUILD_DIR / "pyproject.toml")
    shutil.copy2(SCRIPT_DIR / "setup.py", BUILD_DIR / "setup.py")
    shutil.copy2(SCRIPT_DIR / "README.md", BUILD_DIR / "README.md")

    (BUILD_DIR / PKG_NAME).mkdir(parents=True, exist_ok=True)
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_DIR / PKG_NAME / "__init__.py", BUILD_DIR / PKG_NAME / "__init__.py")
    shutil.copy2(SCRIPT_DIR / PKG_NAME / "client.py", SRC_DIR / "client.py")
    shutil.copy2(SCRIPT_DIR / PKG_NAME / "fingerprint.py", SRC_DIR / "fingerprint.py")


def cleanup_build_tree() -> None:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    shutil.rmtree(DIST_DIR, ignore_errors=True)


def build_wheels(version: str, *, wheel_plat_name: str | None = None) -> list[Path]:
    target = prepare_release_dir(version)
    prepare_build_tree()

    build_env = os.environ.copy()
    build_env["WHEEL_PLAT_NAME"] = wheel_plat_name or os.environ.get("WHEEL_PLAT_NAME", detect_wheel_platform())
    build_env["FINSIGHT_BUILD_COMPILED"] = "1"
    build_env["FINSIGHT_COMPILED_SOURCE_DIR"] = "compiled_src"
    run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(target)], env=build_env, cwd=BUILD_DIR)
    return sorted(target.glob("*.whl"))


def wheel_metadata_from_name(filename: str) -> dict[str, str]:
    pattern = r"^finsight_data-(?P<version>[^-]+)-(?P<python_tag>[^-]+)-(?P<abi_tag>[^-]+)-(?P<platform_tag>.+)\.whl$"
    match = re.match(pattern, filename)
    if not match:
        return {
            "version": "",
            "python_tag": "",
            "abi_tag": "",
            "platform_tag": "",
        }
    return match.groupdict()


def write_release_notes(version: str, wheel_files: list[Path]) -> Path:
    target = release_dir(version)
    target.mkdir(parents=True, exist_ok=True)
    platform_lines = []
    for wheel in wheel_files:
        meta = wheel_metadata_from_name(wheel.name)
        platform_lines.append(
            f"| `{wheel.name}` | `{meta['python_tag']}` | `{meta['abi_tag']}` | `{meta['platform_tag']}` |"
        )
    lines = [
        f"# finsight-data {version}",
        "",
        f"本目录存放 `{version}` 版本的全部 wheel 构建产物。",
        "",
        "## 文件清单",
        "",
        "| file | python | abi | platform |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(platform_lines)
    lines.extend(
        [
            "",
            "## 本版本整理结果",
            "",
            f"- 本版本目录：`releases/{version}`",
            f"- 目录内所有 wheel 都应为 `{version}`",
            "- 同一版本可以在不同机器上分批补充平台包",
            "- 上传脚本会直接读取本目录下全部 `.whl` 文件",
            "",
            "## 构建与上传",
            "",
            "- 打包脚本：`build_release.py` / `build_release.cmd` / `build_release.sh`",
            "- 上传脚本：`upload_release.py` / `upload_release.cmd` / `upload_release.sh`",
            "- Linux 推荐使用 `python:3.12-bookworm` 环境打包",
            "- 上传时只需要传版本号，脚本会自动上传本目录中的全部 wheel",
            "",
            "## 本版本建议操作",
            "",
            f"1. 在各平台机器上执行 `build_release {version}`，把生成的 wheel 汇总到本目录。",
            "2. 检查本目录下 wheel 文件名、平台标签和内部 `METADATA` 版本。",
            f"3. 最后执行 `upload_release {version}`，一次性上传本目录内全部 wheel。",
            "",
        ]
    )
    readme_path = target / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return readme_path


def write_pypirc(username: str, password: str) -> None:
    target = Path.home() / ".pypirc"
    target.write_text(
        "\n".join(
            [
                "[distutils]",
                "index-servers =",
                "    pypi",
                "",
                "[pypi]",
                f"repository = {REPOSITORY_URL}",
                f"username = {username}",
                f"password = {password}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def file_exists_on_pypi(package_name: str, filename: str) -> bool:
    import requests

    project_url = f"https://pypi.org/simple/{normalize_name(package_name)}/"
    try:
        response = requests.get(project_url, headers={"Connection": "close"}, timeout=(15, 20))
    except requests.RequestException:
        return False
    if response.status_code != 200:
        return False
    return filename in response.text


def upload_file(repository_url: str, username: str, password: str, filename: Path) -> None:
    import requests
    from twine.package import PackageFile

    package = PackageFile.from_filename(str(filename), None)
    metadata = package.metadata_dictionary()
    metadata[":action"] = "file_upload"
    metadata["protocol_version"] = "1"
    headers = {"Connection": "close"}
    basename = filename.name

    try:
        with filename.open("rb") as handle:
            files = {"content": (basename, handle, "application/octet-stream")}
            response = requests.post(
                repository_url,
                data=metadata,
                files=files,
                auth=(username, password),
                headers=headers,
                timeout=(30, 45),
            )
    except requests.exceptions.ReadTimeout:
        if file_exists_on_pypi(metadata["name"], basename):
            print(f"confirmed-after-timeout: {basename}")
            return
        raise

    body = (response.text or "").strip()
    if response.status_code == 200:
        print(f"uploaded: {basename}")
        return

    lowered = body.lower()
    if response.status_code in {400, 409} and "already exists" in lowered:
        print(f"skip-existing: {basename}")
        return

    print(body[:4000], file=sys.stderr)
    raise SystemExit(f"upload failed: {response.status_code} {basename}")
