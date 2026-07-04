from __future__ import annotations

import ctypes
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


TASK_NAME = "CentradorCorrugadora"
SHORTCUT_NAME = "Centrador Corrugadora.lnk"


@dataclass
class StartupStatus:
    enabled: bool
    method: str
    detail: str = ""


def _quote(value: str | Path) -> str:
    return f'"{str(value)}"'


def _project_root(config_path: Path) -> Path:
    try:
        return config_path.resolve().parents[1]
    except IndexError:
        return Path.cwd().resolve()


def _startup_dir() -> Path:
    appdata = Path.home() / "AppData" / "Roaming"
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=20)


def _task_exists() -> bool:
    result = _run_schtasks(["/Query", "/TN", TASK_NAME])
    return result.returncode == 0


def _delete_task() -> tuple[bool, str]:
    if not _task_exists():
        return True, ""
    result = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "No se pudo eliminar la tarea programada.").strip()


def _startup_command(config_path: Path) -> str:
    config_abs = config_path.resolve()
    if getattr(sys, "frozen", False):
        return _quote(Path(sys.executable).resolve())
    root = _project_root(config_abs)
    python_exe = Path(sys.executable).resolve()
    return f'cmd.exe /c cd /d {_quote(root)} && {_quote(python_exe)} -m centrador.main --config {_quote(config_abs)}'


def _create_task(config_path: Path) -> tuple[bool, str]:
    command = _startup_command(config_path)
    result = _run_schtasks(["/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", command, "/F"])
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "No se pudo crear la tarea programada.").strip()


def _shortcut_target(config_path: Path) -> tuple[str, str, str]:
    config_abs = config_path.resolve()
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), "", str(exe.parent)
    root = _project_root(config_abs)
    python_exe = Path(sys.executable).resolve()
    return str(python_exe), f'-m centrador.main --config {_quote(config_abs)}', str(root)


def _create_shortcut(config_path: Path) -> tuple[bool, str]:
    shortcut = _shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    target, arguments, working_dir = _shortcut_target(config_path)
    ps = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({str(shortcut)!r})",
            f"$shortcut.TargetPath = {target!r}",
            f"$shortcut.Arguments = {arguments!r}",
            f"$shortcut.WorkingDirectory = {working_dir!r}",
            "$shortcut.Save()",
        ]
    )
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], capture_output=True, text=True, timeout=20)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "No se pudo crear el acceso directo de inicio.").strip()


def _delete_shortcut() -> tuple[bool, str]:
    shortcut = _shortcut_path()
    if not shortcut.exists():
        return True, ""
    try:
        shortcut.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)


def startup_status() -> StartupStatus:
    task = _task_exists()
    shortcut = _shortcut_path().exists()
    if task:
        detail = "Task Scheduler"
        if shortcut:
            detail += " + Startup"
        return StartupStatus(enabled=True, method="task", detail=detail)
    if shortcut:
        return StartupStatus(enabled=True, method="shortcut", detail="Startup")
    return StartupStatus(enabled=False, method="none", detail="")


def enable_startup(config_path: Path) -> tuple[bool, str]:
    ok, error = _create_task(config_path)
    if ok:
        _delete_shortcut()
        return True, ""
    shortcut_ok, shortcut_error = _create_shortcut(config_path)
    if shortcut_ok:
        return True, ""
    return False, f"Task Scheduler: {error}\nStartup: {shortcut_error}"


def disable_startup() -> tuple[bool, str]:
    task_ok, task_error = _delete_task()
    shortcut_ok, shortcut_error = _delete_shortcut()
    if task_ok and shortcut_ok:
        return True, ""
    errors = [error for error in (task_error, shortcut_error) if error]
    return False, "\n".join(errors) or "No se pudo desactivar el inicio con Windows."


def restart_to_uefi() -> tuple[bool, str]:
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "shutdown.exe", "/r /fw /t 0", None, 1)
    if result > 32:
        return True, ""
    return False, "Windows no pudo iniciar shutdown /r /fw /t 0 con permisos de administrador."
