# DeskIsle(桌島)

> 你的檔案,就是島嶼。

DeskIsle 會讀取 Windows 桌面上每個圖示的位置,畫出一張跟著檔案長出來的桌布:
有檔案的地方是沙灘,沒有檔案的地方是海洋,再點綴上椰子樹、珊瑚、魚群和小船。
把檔案拖到別處,陸地就跟著移動。

完整的設計說明在 [PLAN.md](PLAN.md)。

## 直接使用(不需要安裝任何東西)

把 `dist\DeskIsle.exe` 複製到任何 64 位元的 Windows 10 / 11 電腦,點兩下就能用。

1. 在「外觀」頁點主題縮圖、調整滑桿,右邊會即時預覽(這時還不會動到桌布)。
2. 按「套用到桌布」。
3. 想讓桌布自動跟著圖示變化,到「運作」頁勾選「自動跟隨桌面圖示」。
   預設每次圖示移動後都會換一種海岸線形狀(換一個種子),不想要的話取消勾選
   「圖示移動後換一種海岸線形狀」。
4. 關閉視窗後程式會縮在系統匣繼續運作;在系統匣圖示上按右鍵可以結束。
5. 想回到原本的桌布,按「還原原本桌布」。
6. 有多個螢幕時,在「螢幕」頁勾選要換桌布的螢幕(橫向、直向都可以),
   沒勾的螢幕會維持原本的桌布。

exe 沒有簽章,在別台電腦第一次執行時 Windows 可能會跳出 SmartScreen 警告,
按「其他資訊 → 仍要執行」即可。

## 主題

| 主題 | 有檔案的地方 | 沒有檔案的地方 | 裝飾物 |
|---|---|---|---|
| `beach` 沙灘(預設) | 沙灘 | 海洋 | 椰子樹、貝殼、海星、珊瑚、魚群、小船 |
| `meadow` 草地 | 草地 | 湖泊 | 樹、花叢、荷葉、魚群、小船 |
| `volcano` 火山 | 玄武岩 | 熔岩 | 岩塊、發光裂縫、漂浮岩殼 |
| `cosmos` 宇宙 | 月面 | 星空 | 隕石坑、行星、星系、星雲、滿天星 |
| `arctic` 極地 | 雪原 | 極海 | 雪松、浮冰 |
| `desert` 沙漠綠洲 | 綠洲 | 沙丘 | 椰子樹、仙人掌、砂岩 |
| `night` 夜晚海灘 | 月光下的沙灘 | 夜海 | 發光浪花、水母 |

每個主題的預覽圖可以用 `python -m deskisle preview --theme 主題 -o 檔名.png` 產生。

## 資源用量

桌布是靜態圖片,不使用顯示卡。實測(1920×1080、37 個圖示):

- 縮在系統匣閒置:單核心 CPU 的 0.1% 左右,記憶體約 30 MB
- 圖示排列改變時重畫一次:約 0.45 秒
- 全螢幕程式(遊戲、影片)執行或螢幕鎖定時自動暫停

想更省電,可以在「運作」頁把檢查間隔調長。做法細節見 [PLAN.md](PLAN.md) 第 9 節。

## 還原桌布

第一次套用之前,DeskIsle 會把原本的桌布路徑與樣式記下來,並複製一份原圖。
按「還原原本桌布」(或 `python -m deskisle restore`)會把它設回去。

如果原本用的是「Windows 焦點」或「幻燈片」:圖片會還原,但「自動更換」這個功能
需要到 設定 → 個人化 → 背景 重新選一次。

## macOS(實驗性)

DeskIsle 也可以在 macOS 上執行,但**還沒有在真的 Mac 上測試過**(開發環境是 Windows),
歡迎回報問題。

```
python3 -m pip install -r requirements.txt
python3 deskisle_app.py
```

- 需要 Python 3.9 以上,而且要有 tkinter(python.org 的安裝程式內建;
  Homebrew 的 Python 要另外 `brew install python-tk`)。
- 第一次執行時 macOS 會問「是否允許控制 Finder」,要按「好」——DeskIsle 要靠 Finder
  才能知道桌面圖示的位置。按錯了可以到「系統設定 → 隱私權與安全性 → 自動化」打開。
- 與 Windows 版的差異:
  - 沒有系統匣圖示,關閉視窗時會縮到 Dock。
  - 圖示的外框是依 Finder 的圖示大小估算的,不像 Windows 那麼精確(留白會把誤差蓋過去)。
  - Finder 記錄圖示位置有時會晚幾秒,所以拖動圖示後桌布可能過幾秒才更新(最慢約 10 秒)。
  - 只會改「目前這個桌面空間(Space)」的桌布。
  - 「全螢幕時暫停」在 Mac 上沒有作用。
- 開機啟動是在 `~/Library/LaunchAgents/com.deskisle.app.plist` 放一個登入項目。
- 設定與產生的桌布在 `~/Library/Application Support/DeskIsle/`。
- 在 Mac 上執行 `python3 build.py` 會打包成 `dist/DeskIsle.app`(PyInstaller 不能跨平台打包)。

## 從原始碼執行(開發用)

需要 Python 3.9 以上(64 位元):

```
pip install -r requirements.txt
python deskisle_app.py            開啟設定介面(多一頁「測試」)
```

命令列:

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

### 測試頁

以原始碼執行時,設定介面會多一頁「測試」:在預覽上畫圖示外框、用隨機假圖示測試排列、
列出偵測到的圖示、效能測試、輸出全尺寸圖、執行自動化測試。這一頁的功能都不會動到桌布,
打包後的 exe 沒有這一頁。

### 自動化測試

```
python -m unittest discover -s tests
```

桌布、開機啟動相關的測試都用假的系統呼叫或臨時的登錄機碼,不會動到系統設定。

### 打包

```
pip install pyinstaller
python build.py                    →  dist\DeskIsle.exe
dist\DeskIsle.exe --selftest 結果.json     不開視窗、不動桌布的自我檢查
```

## 設定檔

`%LOCALAPPDATA%\DeskIsle\config.json`(macOS:`~/Library/Application Support/DeskIsle/config.json`),介面會自動寫入。各項目的說明見 [PLAN.md](PLAN.md) 第 12 節。

## 已知限制

- 多螢幕與非 100% 縮放尚未在實機上測試。每個螢幕各自設定桌布需要 Windows 8 以上;
  做不到時會退回「整個桌面畫成一張圖、以跨螢幕模式套用」。
- 只更新部分螢幕時,桌布的「樣式」會統一設成「填滿」,沒勾選的螢幕圖片不變,但若原本是「符合」
  之類的樣式會跟著變成「填滿」。
- 極地主題的雪地顏色偏淺,圖示的白色文字比較不明顯。
- exe 尚未在其他電腦上測試過。
- macOS 版尚未在實機上測試過(見上面的「macOS」一節)。
- 目前的驗證狀態見 [PLAN.md](PLAN.md) 第 13 節。
