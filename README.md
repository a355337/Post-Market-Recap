# 台灣上班日美股財經 Podcast

每天台灣時間早上 06:00（週一至週五、排除台灣國定假日），收集 RSS／官方資料後使用 Gemini 撰寫約 30 分鐘的繁體中文單一主持人 Podcast 獨白稿，並合成高質感 MP3。每集另存逐字稿與來源清單。

## 安裝

需要 Python 3.10 以上。Gemini API 會產生費用；請先在 Google AI Studio 建立 API key。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

編輯 `.env`，將 `GEMINI_API_KEY` 設為自己的 API key。不要提交 `.env`。

## 單獨測試 Twelve Data API key

在 `.env` 設定 `TWELVE_DATA_API_KEY` 後，執行一次 SPY 報價請求：

```powershell
.\.venv\Scripts\python.exe twelve_data_check.py
```

可用 `--symbol QQQ` 或 `--symbol DIA` 改測其他 ETF。程式不會輸出 API key。

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

## Spotify for Creators 上傳（暫停）

目前暫時不上傳 EP2，也不將獨立上傳工具整合至 `podcast.py`。請勿執行 `spotify_uploader.py`；待登入與驗證流程確認可用後，再恢復上傳測試。工具仍保留，密碼使用 Windows keyring，預設使用 Chrome。

若日後恢復上傳，GitHub Actions 還需另行處理認證與人工驗證：Windows keyring 不會隨工作移至 Ubuntu runner，且目前流程需要在瀏覽器完成驗證、選擇節目並檢查草稿，尚不能直接用於無人值守工作流程。

## 立即測試

```powershell
.\.venv\Scripts\python.exe podcast.py --once --force
```

`--force` 會略過週末／國定假日檢查；一般手動執行 `--once` 則遵守上班日限制。

## 主題報告

使用 `--subject` 產生單一主題的繁體中文報告與 MP3，不受工作日限制：

```powershell
.\.venv\Scripts\python.exe podcast.py --subject 黃仁勳
.\.venv\Scripts\python.exe podcast.py --subject 黃仁勳 --minute 10
```

每次執行會用指定主題動態查詢 Google News RSS，並合併現有 RSS、SEC 與行情資料；文字模型依語意判斷相關來源，不依賴特定人物、公司或主題的程式碼別名。報告只根據提供且相關的來源撰寫；若沒有可引用的資料就會停止，不會憑空生成。`--minute` 可指定主題報告的目標長度（預設 10 分鐘，允許 1 至 120 分鐘），實際秒數由文字密度與 TTS 音訊長度決定。每次 MP3 完成後，程式會量測輸出 MP3 長度，並將指定/實際分鐘數、送入 TTS 的非空白字數、實測字/分鐘，以及依「本次字數 × 指定分鐘 ÷ 實際分鐘」推算的下次目標字數，存成 `_時長分析.txt`，供逐次修正參考。報告會附引用與來源清單，並使用既有的 TTS 模型及主持人聲音設定；相同主題的報告會累加 EP 編號，檔名為 `主題報告EP<編號>｜<主題>｜<日期>.mp3`，逐字稿使用相同檔名主體並存為 `.txt`，送交 TTS 前已清除來源標註的文字另存為 `_TTS逐字稿.txt`，來源另存 `_sources.txt`。Windows 不支援檔名中的半形 `|`，因此使用外觀相近的全形 `｜`。

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

預設輸出在 `output/`：MP3、逐字稿、Spotify 說明、來源清單及執行記錄。MP3 會額外生成本集摘要，標題以 8 個字內為目標；超過時會記錄警告並仍使用完整摘要命名，檔名格式為 `美股盤後EP1｜摘要.mp3`，EP 編號依 `output/` 內既有集數遞增；另產生 100 字內的 Spotify 摘要，存成 `美股盤後EP1｜摘要_Spotify說明.txt`，可直接複製到 Spotify。因 Windows 檔名不能使用半形 `|`，實際使用外觀相近的全形 `｜`。程式從 CNBC、聯準會與 BLS RSS 收集資料，再交給 Gemini 文字模型撰稿，不使用 Google Search grounding。SEC 8-K feed 與 Twelve Data 行情可選擇設定；行情以 SPY、QQQ、DIA ETF 作為指數代理，並非指數本身的點位。未設定行情 API 時，節目不會猜測點位或漲跌幅。

撰稿時會把輸出資料夾中最近三集逐字稿（每集最多 2,500 字元）附在提示中，協助延續敘事並避免重複。前集內容僅作脈絡參考，不能作為新聞事實或行情數字的依據；所有事實仍須由本段最新來源支持。

逐字稿會在開始 TTS 前寫入 `.txt` 並保留；實際送交 TTS 前也會將主持人標籤與來源標註清理乾淨，並另存為 `_TTS逐字稿.txt`。摘要、來源與逐字稿也會暫存為當日快取；若 TTS 失敗，重新執行會沿用快取，不必重新收集來源或生成逐字稿。整集成功後會刪除快取檔，但不會刪除逐字稿。

預設文字模型為 `gemini-4-hydrogen`，語音模型為 `gemini-3.8-flash-tts`。寫稿會產生單一主持人陳知衡的連續獨白格式；配音使用固定單人 Voice ID（預設 `Kore`），並套用相同的「沉穩、理性且具市場分析感」播報風格，不再啟用 TTS Multi-speaker。Gemini 模型與 Voice 設定固定於程式；SEC EDGAR User-Agent 固定於 `podcast.py`，並使用 `a355337@gmail.com` 作為聯絡 Email。若要行情代理報價，設定 [Twelve Data API key](https://twelvedata.com/)，每集會查詢 SPY、QQQ、DIA 三個 ETF。RSS 失敗會記錄警告；所有來源都無法取得時，程式會停止而不讓 Gemini 補猜資料。腳本會記錄實際音訊長度；播讀速度與 Gemini 生成內容會使每集長度略有差異。

若要使用持久化的自訂主持人聲音，執行一次 `python create_voice.py` 建立帶有 `voice_...` ID 的 Voice；取得後請將 ID 固定到 [podcast.py](podcast.py) 的 `GEMINI_TTS_HOST_A_VOICE`，並將試聽檔保存到 `output/finance_voice_sample.wav`。之後執行 `python create_voice.py --list` 可查詢專案中已保存的自訂 Voice；排程不需要再次建立 Voice，直接重用相同 ID。

Gemini API 遇到 HTTP 429（速率限制）或 503（服務暫時無法使用）時，SDK 會最多嘗試 5 次（含首次請求），以指數退避加隨機抖動等待後重送，退避上限為 60 秒；其他錯誤直接回報。若重試仍失敗，手動 `--once` 會報錯結束；常駐排程會記錄錯誤，並於下一個工作日早上 06:00 再試。

若文字模型未在單元稿中提供來源標記，程式會額外要求修訂一次，並重新驗證標記；修訂後仍無有效來源標記時會明確報錯。

文字模型請求會在 `output/podcast.log` 記錄開始、完成耗時及失敗／中斷時的例外堆疊，不會記錄提示詞或 API key。

內容僅供資訊參考，不構成投資建議。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
