# weekly-report

從公司 GitLab 收集個人一週活動，由 Claude Code 摘要成週報 Markdown（人工審稿後），
再透過 [PPT_Generator](https://github.com/a23444452) 產出週報 PPTX。

```
collector.py ──► data/raw-activity.json ──► /weekly-report skill（Claude 摘要）
                                                    │
                                        reports/YYYY-Wnn.md ◄── ★ 人工審稿 ★
                                                    │
render.py ──► PPT_Generator API ──► reports/YYYY-Wnn.pptx
```

設計重點：

- **摘要不需要額外的 LLM 金鑰** — 由公司環境裡的 Claude Code（走公司 gateway）在 skill 對話中完成。
- **人工審稿點** — skill 生成草稿後必定停下，你改完才出 PPT。
- **上週對照** — 生成時會拿上週報告的「下週計畫」逐項對照本週實際完成狀況。

## 公司環境部署步驟

### 1. 安裝依賴

```bash
uv sync
```

### 2. 設定 GitLab

到公司 GitLab → User Settings → Access Tokens，建立 Personal Access Token，
**scope 只勾 `read_api`**。然後：

```bash
cp .env.example .env
# 編輯 .env 填入 token，使用前 source .env（或用你慣用的環境變數管理方式）
```

編輯 `config.yaml`：

- `gitlab.base_url`：公司 GitLab 網址
- `gitlab.username`：你的 GitLab username
- `repos`：4-5 個 repo 的完整路徑（`namespace/project`）
- `ppt_generator.base_url`：PPT_Generator 後端位址（含 `/api`）

### 3. 驗證 collector

```bash
source .env
uv run collector.py
```

成功會輸出 `data/raw-activity.json`。常見問題：

| 錯誤 | 處理 |
|---|---|
| `GITLAB_TOKEN 未設定` | `source .env` 或重新 export |
| 401 | token 過期或 scope 不含 read_api，重新產生 |
| 404 | `repos` 路徑拼錯，對照 GitLab 專案頁的 URL |
| 連不上 | `base_url` 錯誤，或需要公司內網/VPN |

### 4. 查 PPT_Generator 可用風格（一次性）

```bash
curl http://localhost:8000/api/styles
```

把想用的 `style_id` / `palette_id` 填進 `config.yaml`。

### 5. 日常使用（每週五）

在本專案目錄開 Claude Code：

```
/weekly-report
```

流程：collector 收集 → Claude 生成草稿存到 `reports/` → **你審稿修改** → 說「出 PPT」→
拿到 `reports/YYYY-Wnn.pptx`。

也可以手動分段跑：

```bash
uv run collector.py                       # 只收集
uv run render.py reports/2026-W30.md      # 只渲染（稿已審好時）
```

## 測試

```bash
uv run pytest
```

## 目錄結構

```
├── collector.py           # Stage 1：GitLab API → data/raw-activity.json
├── render.py              # Stage 3：週報 .md → PPT_Generator → .pptx
├── config.yaml            # GitLab / repos / PPT 風格設定
├── prompts/weekly.md      # 摘要規則與輸出格式（可依主管口味調整）
├── reports/               # 歷週週報 .md 與 .pptx（.md 建議入版控，累積季報素材）
├── data/                  # raw-activity.json（gitignored）
└── .claude/skills/weekly-report/   # Claude Code skill 入口
```

## 安全備忘

- token 只放 `.env`（已 gitignored），scope 僅 `read_api`。
- 週報內容只流經：公司 GitLab → 本機 → 公司 gateway（Claude）→ 本機 PPT_Generator，不出外網。
- `data/raw-activity.json` 含內部 issue/MR 標題，已 gitignored，勿手動加入版控。
