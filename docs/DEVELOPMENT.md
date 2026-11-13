# DeskIsle 開發說明

給想從原始碼執行、修改或打包 DeskIsle 的人。一般使用請看 [README](../README.md);
完整的設計說明在 [PLAN.md](PLAN.md)。

## 從原始碼執行

需要 Python 3.9 以上(64 位元):

```
pip install -r requirements.txt
python deskisle_app.py            開啟設定介面(多一頁「測試」)
```

想看另一種配色,可以用環境變數強制指定:`DESKISLE_APPEARANCE=light` 或 `dark`
(PowerShell:`$env:DESKISLE_APPEARANCE="light"; python deskisle_app.py`)。

## 命令列

```
python -m deskisle preview            輸出 deskisle_preview.png,不動桌布
python -m deskisle apply              畫一次並設為桌布
python -m deskisle watch              持續監看,圖示一移動就重畫(Ctrl+C 結束)
python -m deskisle restore            還原成原本的桌布
python -m deskisle icons              列出偵測到的圖示與座標
python -m deskisle themes             列出主題
python -m deskisle config --theme cosmos --save     把主題存成預設
```

`preview`、`apply`、`watch` 都可以加 `--theme 主題`、`--seed 數字`(換一種海岸線形狀)、
`--decorations 數量`(0 = 不放裝飾物)。`preview --debug` 會畫出圖示外框。

每個主題的預覽圖可以用 `python -m deskisle preview --theme 主題 -o 檔名.png` 產生。

## 專案結構

```
deskisle_app.py   視窗程式進入點          build.py   打包腳本
deskisle/
  engine/         畫桌布的核心(地形、主題、裝飾物),與作業系統無關
  system/         作業系統相關:windows/、macos/,由 system/__init__.py 依系統選擇
  ui/             設定視窗(自繪元件、預覽)、系統匣、測試頁
  config.py       設定檔          watcher.py   監看器          cli.py   命令列
tests/            自動化測試
docs/PLAN.md      完整設計說明
docs/images/      README 用的圖片
```

## 測試頁

以原始碼執行時,設定介面會多一頁「測試」:在預覽上畫圖示外框、用隨機假圖示測試排列、
列出偵測到的圖示、效能測試、輸出全尺寸圖、執行自動化測試。這一頁的功能都不會動到桌布,
打包後的 exe 沒有這一頁。

## 自動化測試

```
python -m unittest discover -s tests
```

桌布、開機啟動相關的測試都用假的系統呼叫或臨時的登錄機碼,不會動到系統設定。

## 打包

```
pip install pyinstaller
python build.py                    →  dist\DeskIsle.exe
```

`dist` 裡已經有 `DeskIsle.exe`(例如舊版正在執行、檔案被鎖住)時不會覆蓋,
而是另存為 `DeskIsle_2.exe`、`DeskIsle_3.exe`…

```
dist\DeskIsle.exe --selftest 結果.json     不開視窗、不動桌布的自我檢查
```

在 Mac 上執行 `python3 build.py` 會打包成 `dist/DeskIsle.app`(PyInstaller 不能跨平台打包)。

## 設定檔

`%LOCALAPPDATA%\DeskIsle\config.json`(macOS:`~/Library/Application Support/DeskIsle/config.json`),
介面會自動寫入。各項目的說明見 [PLAN.md](PLAN.md) 第 12 節。
