---
name: weekly-report
description: 產生本週工作週報。先跑 collector 收集 GitLab 活動，由 Claude 摘要成週報 Markdown 停下讓使用者審稿；使用者確認後再呼叫 render.py 產出 PPTX。
argument-hint: "（可選）--since YYYY-MM-DD --until YYYY-MM-DD"
---

# 週報產生流程

三段式：收集（腳本）→ 摘要（你，Claude）→ 渲染（腳本）。**摘要與渲染之間必須停下讓使用者審稿，不可跳過。**

## Step 1 — 收集 GitLab 活動

```bash
uv run collector.py
```

使用者有給引數（如 `--since`）就原樣傳給 collector。

失敗處理：
- 提示 `GITLAB_TOKEN 未設定` → 告訴使用者設定環境變數後重試，不要繼續。
- 401 / 404 → 把錯誤訊息原樣轉告（訊息已含修復指引）。

## Step 2 — 生成週報草稿（由你完成，不呼叫額外 API）

1. Read `data/raw-activity.json`。
2. Read `reports/` 下**最新**的一份 `*.md`（依檔名排序），抽出其「下週計畫」段落；沒有歷史報告就跳過對照。
3. Read `prompts/weekly.md`，**嚴格依其規則與輸出格式**生成週報。
4. 存檔到 `reports/<ISO週編號>.md`，檔名格式 `YYYY-Wnn.md`（例：`2026-W30.md`），
   以 raw-activity.json 的 `week_end` 那天所屬 ISO 週為準。同名檔案已存在則覆蓋前先告知使用者。
5. **停下**。把草稿全文貼給使用者看，說明：
   - 哪些項目對應到了上週計畫、哪些沒對到
   - 「下週計畫」目前只是依 open issues 起草的版本，請使用者補充真實優先序
   - 請使用者直接編輯檔案或口頭告訴你要改什麼

## Step 3 — 渲染 PPTX（僅在使用者明確確認後）

使用者說「出 PPT」「確認」「可以了」之類的話之後才執行：

```bash
uv run render.py reports/<檔名>.md
```

- 前置條件：PPT_Generator 後端需在運行中。連線失敗時轉告錯誤訊息（已含指引），
  並提醒使用者啟動 PPT_Generator 後端。
- 成功後回報 PPTX 路徑。使用者要調整風格 → 改 `config.yaml` 的 `ppt_generator.style_id` /
  `palette_id`（可用 `curl <base_url>/styles` 查清單）後重跑本步驟。

## 邊界

- 不自動 commit、不自動推送、不把週報內容送到 GitLab/PPT_Generator 以外的任何地方。
- raw data 裡沒有的活動不可虛構；資料異常稀少時提醒使用者確認 config.yaml 的 repos 與區間。
