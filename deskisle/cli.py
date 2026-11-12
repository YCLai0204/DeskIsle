"""命令列介面。"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import List, Optional

from . import APP_NAME, __version__
from .config import Config, config_path, load_config, save_config
from .themes import THEMES


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--theme", choices=sorted(THEMES), help="主題(預設讀設定檔)")
    common.add_argument("--seed", type=int, help="雜訊種子,換一個數字就換一種海岸線")
    common.add_argument("--decorations", type=float, metavar="數量",
                        help="裝飾物數量:0 = 不畫,1 = 標準,2 = 兩倍")

    parser = argparse.ArgumentParser(
        prog="deskisle",
        description=f"{APP_NAME}(桌島){__version__}:讓桌布的地形跟著桌面圖示長出來。"
                    "不加任何指令時開啟設定介面。",
    )
    sub = parser.add_subparsers(dest="command", metavar="指令")

    p = sub.add_parser("gui", help="開啟設定介面(預設)")
    p.add_argument("--minimized", action="store_true", help="啟動後直接縮到系統匣")

    sub.add_parser("icons", help="列出偵測到的桌面圖示(唯讀)")

    p = sub.add_parser("preview", parents=[common], help="畫一張圖存檔,不動桌布")
    p.add_argument("-o", "--output", default="deskisle_preview.png", help="輸出檔案(預設 %(default)s)")
    p.add_argument("--debug", action="store_true", help="畫出圖示外框以便核對位置")

    sub.add_parser("apply", parents=[common], help="畫一次並設為桌布")
    sub.add_parser("watch", parents=[common], help="持續監看,圖示移動就重畫(Ctrl+C 結束)")
    sub.add_parser("restore", help="還原成原本的桌布")
    sub.add_parser("themes", help="列出主題")

    p = sub.add_parser("config", parents=[common], help="顯示設定;加 --save 寫入設定檔")
    p.add_argument("--save", action="store_true", help="把目前設定(含 --theme/--seed)寫入設定檔")
    return parser


def _load(args) -> Config:
    config, warnings = load_config()
    for message in warnings:
        print(f"注意:{message}", file=sys.stderr)
    overrides = {}
    if getattr(args, "theme", None):
        overrides["theme"] = args.theme
    if getattr(args, "seed", None) is not None:
        overrides["seed"] = args.seed
    if getattr(args, "decorations", None) is not None:
        overrides["decorations"] = args.decorations
    return replace(config, **overrides).validate()


def _cmd_gui(args) -> int:
    from .gui import main as gui_main
    return gui_main(["--minimized"] if getattr(args, "minimized", False) else [])


def _cmd_icons(args) -> int:
    from .icons import read_layout
    layout = read_layout()
    print(f"畫面 {layout.width}x{layout.height},螢幕 {layout.monitors} 個,圖示 {len(layout.icons)} 個")
    for number, screen in enumerate(layout.screen_list(), 1):
        print(f"  {screen.describe(number)},位置 ({screen.left},{screen.top})")
    if not layout.icons_visible:
        print("桌面圖示目前是隱藏的。")
    for icon in layout.icons:
        size = f"{icon.right - icon.left}x{icon.bottom - icon.top}"
        print(f"  ({icon.left:5d},{icon.top:5d})  {size:>8}  {icon.name}")
    return 0


def _cmd_preview(args) -> int:
    from .icons import read_layout
    from .watcher import render_layout
    config = _load(args)
    layout = read_layout()
    image = render_layout(layout, config, debug=args.debug)
    output = Path(os.path.abspath(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"已輸出 {output}({layout.width}x{layout.height},{len(layout.icons)} 個圖示,主題 {config.theme})")
    print("桌布沒有變動。")
    return 0


def _print_backup_note() -> None:
    from . import wallpaper
    print("原本的桌布已備份,隨時可用 `python -m deskisle restore` 還原。" if wallpaper.load_backup()
          else "注意:沒有原本桌布的備份可供還原。")


def _cmd_apply(args) -> int:
    from .icons import read_layout
    from .watcher import apply_layout
    config = _load(args)
    layout = read_layout()
    targets = apply_layout(layout, config)
    print(f"已套用桌布:{len(layout.icons)} 個圖示,主題 {config.theme}")
    for target in targets:
        print(f"  {target}")
    _print_backup_note()
    return 0


def _cmd_watch(args) -> int:
    from .watcher import watch
    config = _load(args)
    print(f"開始監看桌面(主題 {config.theme},正對桌面時每 {config.poll_interval:g} 秒、"
          f"其他時候每 {max(config.idle_interval, config.poll_interval):g} 秒檢查一次)。按 Ctrl+C 結束。")
    updates = watch(config)
    print(f"\n已停止監看,共更新 {updates} 次。桌布會維持最後一次的樣子。")
    _print_backup_note()
    return 0


def _cmd_restore(args) -> int:
    from . import wallpaper
    state = wallpaper.restore()
    if state is None:
        print("沒有備份可還原(還沒套用過,或已經還原過了)。")
        return 1
    print(f"已還原原本的桌布:{state.path or '(純色背景)'}")
    kind = wallpaper.BACKGROUND_KINDS.get(state.kind)
    if state.kind in (2, 3):
        print(f"原本的背景類型是「{kind}」。圖片已還原,但自動更換功能需要到 "
              f"設定 → 個人化 → 背景 重新選一次「{kind}」。")
    return 0


def _cmd_themes(args) -> int:
    for theme in THEMES.values():
        print(f"  {theme.key:<8} {theme.label} — {theme.description}")
    return 0


def _cmd_config(args) -> int:
    config = _load(args)
    path = config_path()
    if args.save:
        save_config(config, path)
        print(f"已寫入 {path}")
    else:
        print(f"設定檔:{path}{'' if path.exists() else '(尚未建立,使用預設值)'}")
    for key, value in asdict(config).items():
        print(f"  {key:<14} {value}")
    return 0


_COMMANDS = {
    "gui": _cmd_gui, "icons": _cmd_icons, "preview": _cmd_preview, "apply": _cmd_apply, "watch": _cmd_watch,
    "restore": _cmd_restore, "themes": _cmd_themes, "config": _cmd_config,
}


def main(argv: Optional[List[str]] = None) -> int:
    # 主控台編碼不支援某些字元(例如檔名裡的特殊符號)時,以 ? 取代而不是當掉
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args = _build_parser().parse_args(argv)
    if sys.platform != "win32":
        print("DeskIsle 目前只支援 Windows。", file=sys.stderr)
        return 2
    try:
        return _COMMANDS[args.command or "gui"](args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # 使用者看到的是一行訊息,不是堆疊追蹤
        from .icons import IconDetectionError
        if isinstance(exc, (IconDetectionError, ValueError, OSError)):
            print(f"錯誤:{exc}", file=sys.stderr)
            return 1
        raise
