# 台灣上班日美股財經 Podcast

每天台灣時間早上 06:00（週一至週五、排除台灣國定假日），使用 Gemini 搜尋最新美股資訊、撰寫約 30 分鐘的繁體中文口播稿，並合成 MP3。每集另存逐字稿與搜尋引用來源。

## 安裝

需要 Python 3.10 以上。Gemini API 會產生費用；請先在 Google AI Studio 建立 API key。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

編輯 `.env`，將 `GEMINI_API_KEY` 設為自己的 API key。不要提交 `.env`。

## 測試 Gemini 文字與搜尋

```powershell
.\.venv\Scripts\python.exe gemini_check.py
```

此工具先測一次一般文字生成，等待 2 秒後再測 Google Search grounding，分別顯示兩項結果。Grounding 測試會呼叫搜尋工具，可能產生用量費用。

## 探測可用的 Grounding 模型

```powershell
.\.venv\Scripts\python.exe gemini_grounding_probe.py
```

依序測試幾個 Gemini 3+ 模型並檢查 grounding 引用。遇到 429 配額錯誤會預設停止，避免重複送出搜尋請求；若仍要繼續測其他模型，可加 `--continue-on-quota`，但可能產生額外費用。

## 立即測試

```powershell
.\.venv\Scripts\python.exe podcast.py --once --force
```

`--force` 會略過週末／國定假日檢查；一般手動執行 `--once` 則遵守上班日限制。

## 每日排程

讓程式在登入 Windows 時啟動，並由 Python 依 `Asia/Taipei` 時區等待工作日早上六點：

```powershell
.\install_task.ps1
```

此排程會在目前 Windows 使用者登入時啟動；排程器執行期間需保持該使用者登入。若要移除：

```powershell
Unregister-ScheduledTask -TaskName TaiwanMarketPodcast -Confirm:$false
```

也可以在終端機直接啟動常駐排程：

```powershell
.\.venv\Scripts\python.exe podcast.py --schedule
```

## 輸出與設定

預設輸出在 `output/`：MP3、逐字稿、Google Search 引用來源及執行記錄。Gemini TTS WAV 會暫存後轉成 MP3，不需要另行安裝 FFmpeg。

預設文字模型為 `gemini-3.5-flash-lite`，語音模型為 `gemini-3.8-flash-lite-tts`。可在 `.env` 覆寫 `GEMINI_TEXT_MODEL`、`GEMINI_TTS_MODEL` 與 `GEMINI_TTS_VOICE`。腳本會記錄實際音訊長度；播讀速度與 Gemini 生成內容會使每集長度略有差異。

內容僅供資訊參考，不構成投資建議。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
