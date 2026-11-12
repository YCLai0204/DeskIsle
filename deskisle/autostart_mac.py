"""macOS 的開機(登入)自動啟動:在 ~/Library/LaunchAgents 放一個 LaunchAgent。

只影響目前的使用者,不需要系統管理員權限;下次登入時生效。
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from typing import List

from . import is_frozen

LABEL = "com.deskisle.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def arguments() -> List[str]:
    """登入時要執行的指令(啟動後縮到 Dock)。"""
    if is_frozen():
        return [sys.executable, "--minimized"]
    script = Path(__file__).resolve().parent.parent / "deskisle_app.py"
    return [sys.executable, str(script), "--minimized"]


def command() -> str:
    return " ".join(f'"{part}"' for part in arguments())


def is_enabled() -> bool:
    """是否已設定為登入時啟動,而且指向目前這個程式。"""
    try:
        with plist_path().open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False
    return data.get("ProgramArguments") == arguments()


def enable() -> None:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump({"Label": LABEL, "ProgramArguments": arguments(), "RunAtLoad": True,
                       "ProcessType": "Interactive"}, handle)


def disable() -> None:
    try:
        plist_path().unlink()
    except FileNotFoundError:
        pass
