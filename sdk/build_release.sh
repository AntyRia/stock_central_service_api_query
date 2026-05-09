#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-}"
TARGETS="${2:-macos,linux_x86_64,linux_aarch64}"
MINIFORGE_DIR="${SCRIPT_DIR}/.build-tools/miniforge3"
CONDA_ENV_DIR="${MINIFORGE_DIR}/envs/finsight-build312"

if [[ -z "${VERSION}" ]]; then
  echo "usage: ./build_release.sh <version> [targets]" >&2
  echo "example: ./build_release.sh 0.1.4 macos,linux_x86_64,linux_aarch64" >&2
  exit 1
fi

have_target() {
  local needle="$1"
  [[ ",${TARGETS}," == *",${needle},"* ]]
}

bootstrap_miniforge_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Miniforge bootstrap is only supported on macOS host." >&2
    exit 1
  fi
  if [[ -x "${MINIFORGE_DIR}/bin/conda" ]]; then
    return 0
  fi

  local arch installer_url installer_path
  arch="$(uname -m)"
  case "${arch}" in
    arm64) installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh" ;;
    x86_64) installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-x86_64.sh" ;;
    *)
      echo "unsupported macOS arch: ${arch}" >&2
      exit 1
      ;;
  esac

  mkdir -p "${SCRIPT_DIR}/.build-tools"
  installer_path="${SCRIPT_DIR}/.build-tools/miniforge-installer.sh"
  curl -L "${installer_url}" -o "${installer_path}"
  bash "${installer_path}" -b -p "${MINIFORGE_DIR}"
  rm -f "${installer_path}"
}

ensure_macos_python312() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "macos target requires running build_release.sh on a macOS host." >&2
    exit 1
  fi

  if command -v python3.12 >/dev/null 2>&1; then
    echo "$(command -v python3.12)"
    return 0
  fi

  bootstrap_miniforge_macos
  "${MINIFORGE_DIR}/bin/conda" create -y -p "${CONDA_ENV_DIR}" python=3.12 pip build twine cython requests setuptools wheel >/dev/null
  echo "${CONDA_ENV_DIR}/bin/python"
}

run_macos_build() {
  local pybin
  pybin="$(ensure_macos_python312)"
  echo "[build] macos via ${pybin}"
  "${pybin}" "${SCRIPT_DIR}/build_release.py" "${VERSION}"
}

run_linux_build() {
  local platform="$1"
  local label="$2"
  echo "[build] ${label} via docker ${platform}"
  docker run --rm \
    --platform "${platform}" \
    -v "${SCRIPT_DIR}:/work" \
    -w /work \
    python:3.12-bookworm \
    bash -lc "python build_release.py ${VERSION}"
}

if have_target "macos"; then
  run_macos_build
fi

if have_target "linux_x86_64"; then
  run_linux_build "linux/amd64" "linux_x86_64"
fi

if have_target "linux_aarch64"; then
  run_linux_build "linux/arm64/v8" "linux_aarch64"
fi
