from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import uuid
from pathlib import Path


def _safe_read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _run_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=4, check=False)
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or completed.stderr or "").strip()


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    version_text = _safe_read("/proc/version").lower()
    return "microsoft" in version_text or "wsl" in version_text


def _persistent_fallback_id() -> str:
    home = Path.home()
    target_dir = home / ".finsight"
    target_file = target_dir / "device_fingerprint"
    try:
        if target_file.exists():
            return target_file.read_text(encoding="utf-8").strip()
        target_dir.mkdir(parents=True, exist_ok=True)
        value = str(uuid.uuid4())
        target_file.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return f"fallback-{uuid.getnode()}"


def _windows_machine_guid_from_python() -> str:
    try:
        import winreg
    except Exception:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value or "").strip()
    except Exception:
        return ""


def _windows_machine_guid_from_regexe() -> str:
    text = _run_command(["reg", "query", r"HKLM\\SOFTWARE\\Microsoft\\Cryptography", "/v", "MachineGuid"])
    match = re.search(r"MachineGuid\s+REG_\w+\s+([A-Fa-f0-9-]+)", text)
    return match.group(1).strip() if match else ""


def _windows_machine_guid_from_powershell() -> str:
    text = _run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            r"(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid",
        ]
    )
    return text.strip()


def _windows_machine_guid() -> str:
    return _windows_machine_guid_from_python() or _windows_machine_guid_from_regexe() or _windows_machine_guid_from_powershell()


def _mac_platform_uuid() -> str:
    text = _run_command(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', text)
    return match.group(1).strip() if match else ""


def _linux_machine_identifier() -> str:
    for path in (
        "/etc/machine-id",
        "/var/lib/dbus/machine-id",
        "/sys/class/dmi/id/product_uuid",
    ):
        value = _safe_read(path)
        if value:
            return value
    return ""


def _primary_device_identifier() -> str:
    system = platform.system().lower()
    if system == "windows":
        return _windows_machine_guid() or _persistent_fallback_id()
    if system == "darwin":
        return _mac_platform_uuid() or _persistent_fallback_id()
    if system == "linux":
        if _is_wsl():
            return _windows_machine_guid_from_regexe() or _windows_machine_guid_from_powershell() or _linux_machine_identifier() or _persistent_fallback_id()
        return _linux_machine_identifier() or _persistent_fallback_id()
    return _persistent_fallback_id()


def build_device_fingerprint() -> str:
    parts = [
        platform.system().lower(),
        platform.machine().lower(),
        _primary_device_identifier(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
