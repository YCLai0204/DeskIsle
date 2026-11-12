"""DeskIsle(桌島):讓桌布的地形跟著桌面圖示長出來。"""
import os
import sys

# 這個程式的運算都是單執行緒的逐元素運算,用不到數學函式庫的執行緒池。
# 在載入 numpy 之前關掉它,常駐時就不會多出一排閒置的執行緒。
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

APP_NAME = "DeskIsle"
__version__ = "0.0.3"


def is_frozen() -> bool:
    """是否為打包後的執行檔(而不是用 Python 直接執行原始碼)。"""
    return bool(getattr(sys, "frozen", False))
