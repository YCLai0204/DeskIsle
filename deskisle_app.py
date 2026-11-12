"""DeskIsle 的視窗程式進入點。

    python deskisle_app.py              開啟設定介面
    python deskisle_app.py --minimized  啟動後直接縮到系統匣(開機自動啟動時使用)

打包成 DeskIsle.exe 時用的也是這個檔案(見 build.py)。
"""
import sys

from deskisle.gui import main

if __name__ == "__main__":
    sys.exit(main())
