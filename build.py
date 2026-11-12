"""把 DeskIsle 打包成可以直接執行的程式。

    pip install pyinstaller
    python build.py

- 在 Windows 上執行 → dist/DeskIsle.exe(單一檔案)。內含 Python 與所有相依套件,
  複製到任何 64 位元的 Windows 10/11 電腦上都能直接執行。
- 在 macOS 上執行 → dist/DeskIsle.app。PyInstaller 不能跨平台打包,
  Mac 版必須在 Mac 上執行這個腳本。

打包時會排除「測試」頁(deskisle.gui_dev)。
"""
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"

# 用不到、但環境裡如果裝了可能被順便帶進去的大型套件
EXCLUDES = [
    "deskisle.gui_dev",            # 測試頁:不給使用者
    "deskisle.cli",                # 命令列介面:exe 沒有主控台
    "matplotlib", "scipy", "pandas", "IPython", "pytest", "setuptools", "pkg_resources",
    "PIL.ImageQt", "PIL.ImageTk", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "win32com", "pythoncom", "pywintypes", "win32api", "win32gui", "win32con",
    "numpy.f2py", "numpy.distutils", "lib2to3", "tkinter.test",
]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("需要先安裝 PyInstaller:pip install pyinstaller")
        return 1

    sys.path.insert(0, str(ROOT))
    from deskisle.tray import make_icon

    BUILD.mkdir(exist_ok=True)
    mac = sys.platform == "darwin"
    if mac:
        icon_path = BUILD / "deskisle.png"     # PyInstaller 會用 Pillow 轉成 .icns
        make_icon(512).save(icon_path)
    else:
        icon_path = BUILD / "deskisle.ico"
        make_icon(256).save(icon_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--windowed",
        "--name", "DeskIsle",
        "--icon", str(icon_path),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
    ]
    if mac:
        # macOS 的 .app 用資料夾模式;不需要系統匣
        command += ["--onedir", "--osx-bundle-identifier", "com.deskisle.app", "--exclude-module", "pystray"]
    else:
        command += ["--onefile", "--hidden-import", "pystray._win32"]
    for name in EXCLUDES:
        command += ["--exclude-module", name]
    command.append(str(ROOT / "deskisle_app.py"))

    print("打包中,大約需要一到兩分鐘…")
    done = subprocess.run(command, cwd=str(ROOT))
    if done.returncode != 0:
        print("打包失敗")
        return done.returncode

    if mac:
        return _finish_mac_app(DIST / "DeskIsle.app")
    exe = DIST / "DeskIsle.exe"
    print(f"完成:{exe}({exe.stat().st_size / 1_048_576:.1f} MB)")
    return 0


def _finish_mac_app(app: Path) -> int:
    """在 Info.plist 加上「控制 Finder」的用途說明,再重新簽章(ad-hoc)。

    沒有這段說明,macOS 會直接拒絕 DeskIsle 詢問 Finder 圖示位置。
    """
    info = app / "Contents" / "Info.plist"
    with info.open("rb") as handle:
        data = plistlib.load(handle)
    data["NSAppleEventsUsageDescription"] = "DeskIsle 需要向 Finder 讀取桌面圖示的位置,才能畫出跟著檔案長出來的桌布。"
    data["NSHighResolutionCapable"] = True
    with info.open("wb") as handle:
        plistlib.dump(data, handle)
    signed = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)])
    if signed.returncode != 0:
        print("注意:重新簽章失敗,第一次開啟時可能需要在「系統設定 → 隱私權與安全性」按「強制打開」")
    print(f"完成:{app}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
