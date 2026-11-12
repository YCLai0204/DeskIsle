## 語言

- 回覆、程式裡的 UI 文字、註解、README、commit 訊息一律使用**繁體中文**。

## Commit 規範

- 訊息開頭一定要有 Conventional Commits 類型前綴：`feat:`、`fix:`、`refactor:`、`docs:`、`style:`、`test:`、`build:`、`chore:` 等。
- 標題與內文用繁體中文，內文用條列說明改了什麼、為什麼。
- Claude 參與的 commit，訊息最後加上署名行：`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 中文訊息先寫成檔案再用 `git commit -F <檔案>`；直接把中文放在 PowerShell 5.1 的參數裡可能會變亂碼。
- 只在使用者要求時才 commit；不要 push、不要改寫已有的歷史。