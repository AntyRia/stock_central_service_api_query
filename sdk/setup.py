from __future__ import annotations

import os
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_py import build_py as _build_py
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel


PACKAGE_NAME = "finsight_data"
COMPILED_MODULES = {"client", "fingerprint"}


class PlatformWheel(_bdist_wheel):
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False
        plat_name = os.getenv("WHEEL_PLAT_NAME", "").strip()
        if plat_name:
            self.plat_name_supplied = True
            self.plat_name = plat_name


class SelectiveBuildPy(_build_py):
    def find_package_modules(self, package: str, package_dir: str):
        modules = super().find_package_modules(package, package_dir)
        if os.getenv("FINSIGHT_BUILD_COMPILED", "").strip() != "1":
            return modules
        if package != PACKAGE_NAME:
            return modules
        return [module for module in modules if module[1] not in COMPILED_MODULES]


def build_extensions():
    if os.getenv("FINSIGHT_BUILD_COMPILED", "").strip() != "1":
        return []

    from Cython.Build import cythonize

    source_dir = os.getenv("FINSIGHT_COMPILED_SOURCE_DIR", "")
    source_root = Path(source_dir) if source_dir else Path(__file__).resolve().parent / PACKAGE_NAME
    extensions = [
        Extension(f"{PACKAGE_NAME}.{module_name}", [str(source_root / f"{module_name}.py")])
        for module_name in sorted(COMPILED_MODULES)
    ]
    return cythonize(extensions, compiler_directives={"language_level": "3"})


setup(
    ext_modules=build_extensions(),
    cmdclass={
        "bdist_wheel": PlatformWheel,
        "build_py": SelectiveBuildPy,
    },
)
