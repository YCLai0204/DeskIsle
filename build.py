"""把 DeskIsle 打包成單一執行檔 dist/DeskIsle.exe。

    pip install pyinstaller
    python build.py

產生的 exe 內含 Python 與所有相依套件,複製到任何 64 位元的 Windows 10/11
電腦上都能直接執行,不需要安裝任何東西。

打包時會排除「測試」頁(deskisle.gui_dev)。
"""
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
    icon_path = BUILD / "deskisle.ico"
    make_icon(256).save(icon_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--onefile", "--windowed",
        "--name", "DeskIsle",
        "--icon", str(icon_path),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--hidden-import", "pystray._win32",
    ]
    for name in EXCLUDES:
        command += ["--exclude-module", name]
    command.append(str(ROOT / "deskisle_app.py"))

    print("打包中,大約需要一到兩分鐘…")
    done = subprocess.run(command, cwd=str(ROOT))
    if done.returncode != 0:
        print("打包失敗")
        return done.returncode

    exe = DIST / "DeskIsle.exe"
    print(f"完成:{exe}({exe.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
