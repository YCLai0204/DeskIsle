"""判斷每個桌面圖示是什麼檔案:資料夾、圖片、文件、捷徑、程式、影音。

桌面上看到的名稱常常沒有副檔名(Windows 預設隱藏副檔名,捷徑也不顯示 .lnk),
所以到桌面資料夾裡找名稱相同、或去掉副檔名後相同的檔案,再看它的副檔名。
找不到的(本機、資源回收筒這類系統圖示)當成 other。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

KINDS = ("folder", "image", "document", "shortcut", "app", "media")
KIND_LABELS = {"folder": "資料夾", "image": "圖片", "document": "文件", "shortcut": "捷徑",
               "app": "程式", "media": "影音"}

_EXTENSIONS = {
    "shortcut": {".lnk", ".url", ".website", ".webloc", ".alias"},
    "app": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".app", ".appref-ms", ".jar", ".command", ".sh"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".svg",
              ".psd", ".ico", ".raw", ".cr2", ".nef"},
    "media": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".mp4", ".mov", ".mkv", ".avi",
              ".wmv", ".webm", ".m4v"},
    "document": {".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".rtf",
                 ".odt", ".ods", ".odp", ".pages", ".numbers", ".key", ".json", ".xml", ".html", ".htm",
                 ".epub", ".hwp"},
}


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    for kind in ("shortcut", "app"):            # .app 在 Mac 上是資料夾,要先判斷
        if suffix in _EXTENSIONS[kind]:
            return kind
    try:
        if path.is_dir():
            return "folder"
    except OSError:
        return "other"
    for kind in ("image", "media", "document"):
        if suffix in _EXTENSIONS[kind]:
            return kind
    return "other"


def _index(folders: Iterable[Path]) -> Dict[str, Path]:
    """名稱(小寫)→ 檔案;同時登記完整名稱與去掉副檔名的名稱,完整名稱優先。"""
    full: Dict[str, Path] = {}
    stems: Dict[str, Path] = {}
    for folder in folders:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or entry.name.lower() == "desktop.ini":
                continue
            path = Path(entry.path)
            full.setdefault(entry.name.lower(), path)
            stems.setdefault(path.stem.lower(), path)
    return {**stems, **full}


def classify(names: Sequence[str], folders: Iterable[Path]) -> List[str]:
    """每個圖示名稱對應的檔案類型(KINDS 之一,或 other)。"""
    index = _index(folders)
    kinds = []
    for name in names:
        path = index.get(name.lower()) if name else None
        kinds.append(kind_of(path) if path is not None else "other")
    return kinds
