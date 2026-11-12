"""開機自動啟動:在「目前使用者」的啟動登錄機碼寫入一筆指令。

只影響目前登入的使用者,不需要系統管理員權限。
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from . import APP_NAME, is_frozen

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME


def command() -> str:
    """開機時要執行的指令(啟動後縮到系統匣)。"""
    if is_frozen():
        return f'"{sys.executable}" --minimized'
    # 以原始碼執行時:用不開主控台視窗的 pythonw 跑進入點腳本
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    script = Path(__file__).resolve().parent.parent / "deskisle_app.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{script}" --minimized'


def is_enabled() -> bool:
    """是否已設定為開機啟動,而且指向目前這個程式。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return value == command()


def enable() -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
