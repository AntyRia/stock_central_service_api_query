from __future__ import annotations

import argparse
import sys

from release_common import (
    build_wheels,
    cleanup_build_tree,
    ensure_build_dependencies,
    ensure_python312,
    release_dir,
    write_release_notes,
    update_version,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()

    ensure_python312()
    ensure_build_dependencies()
    update_version(args.version)
    wheel_files = build_wheels(args.version)

    import subprocess

    subprocess.run([sys.executable, "-m", "twine", "check", *[str(path) for path in wheel_files]], check=True)
    note_path = write_release_notes(args.version, sorted(release_dir(args.version).glob("*.whl")))
    cleanup_build_tree()

    print(f"build success: version={args.version}")
    print(f"release notes: {note_path}")
    for path in wheel_files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
