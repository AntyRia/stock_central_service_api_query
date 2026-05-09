from __future__ import annotations

import argparse
import os

from release_common import (
    DEFAULT_PYPI_TOKEN,
    DEFAULT_PYPI_USERNAME,
    REPOSITORY_URL,
    ensure_upload_dependencies,
    release_dir,
    upload_file,
    write_pypirc,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()

    pypi_user = os.environ.get("PYPI_USERNAME", DEFAULT_PYPI_USERNAME)
    pypi_pass = os.environ.get("PYPI_PASSWORD") or os.environ.get("PYPI_TOKEN") or DEFAULT_PYPI_TOKEN
    if not pypi_pass:
        raise SystemExit("missing PYPI_PASSWORD or PYPI_TOKEN")

    target = release_dir(args.version)
    if not target.exists():
        raise SystemExit(f"release folder not found: {target}")

    wheel_files = sorted(target.glob("*.whl"))
    if not wheel_files:
        raise SystemExit(f"no wheel files found in {target}")

    ensure_upload_dependencies()
    write_pypirc(pypi_user, pypi_pass)
    for wheel in wheel_files:
        upload_file(REPOSITORY_URL, pypi_user, pypi_pass, wheel)

    print(f"upload success: version={args.version}")
    for path in wheel_files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
