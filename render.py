"""Stage 3 渲染器：把審好稿的週報 Markdown 交給 PPT_Generator，產出 PPTX。

流程：create project → upload → style → outline → generate → poll → export → download

用法：
    uv run render.py reports/2026-W30.md
    uv run render.py reports/2026-W30.md --name "週報 W30"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
import yaml

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


class RenderError(Exception):
    """可預期的失敗，訊息直接給使用者看。"""


def load_ppt_config(path: Path) -> dict:
    if not path.is_file():
        raise RenderError(f"找不到設定檔 {path}")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    ppt = cfg.get("ppt_generator") or {}
    missing = [k for k in ("base_url", "style_id", "palette_id") if not ppt.get(k)]
    if missing:
        raise RenderError(f"config.yaml 的 ppt_generator 區塊缺少欄位：{', '.join(missing)}")
    return ppt


def _request(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    try:
        resp = session.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
    except requests.RequestException as exc:
        raise RenderError(
            f"無法連線 PPT_Generator（{url}）：{exc.__class__.__name__}\n"
            "請確認後端已啟動，且 config.yaml 的 ppt_generator.base_url 正確"
        ) from exc
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except ValueError:
            detail = resp.text[:200]
        raise RenderError(f"PPT_Generator 回應 {resp.status_code}（{url}）：{detail}")
    return resp.json()


def render(markdown_path: Path, ppt_cfg: dict, project_name: str) -> Path:
    if not markdown_path.is_file():
        raise RenderError(f"找不到週報檔案 {markdown_path}")

    base = ppt_cfg["base_url"].rstrip("/")
    session = requests.Session()

    print(f"1/6 建立專案「{project_name}」...", file=sys.stderr)
    project = _request(session, "POST", f"{base}/projects", json={"name": project_name})
    pid = project["id"]

    print("2/6 上傳週報 Markdown ...", file=sys.stderr)
    with markdown_path.open("rb") as f:
        upload = _request(
            session,
            "POST",
            f"{base}/projects/{pid}/upload",
            files=[("files", (markdown_path.name, f, "text/markdown"))],
        )
    failed = [r for r in upload.get("results", []) if not r.get("success")]
    if failed:
        raise RenderError(f"上傳失敗：{failed[0].get('error', '不明原因')}")

    print(f"3/6 套用風格 {ppt_cfg['style_id']} / {ppt_cfg['palette_id']} ...", file=sys.stderr)
    _request(
        session,
        "POST",
        f"{base}/projects/{pid}/style",
        json={"style_id": ppt_cfg["style_id"], "palette_id": ppt_cfg["palette_id"]},
    )

    print("4/6 生成大綱（LLM）...", file=sys.stderr)
    outline = _request(session, "POST", f"{base}/projects/{pid}/outline")
    print(f"    共 {len(outline.get('slides', []))} 頁", file=sys.stderr)

    print("5/6 生成投影片（LLM，背景任務）...", file=sys.stderr)
    _request(session, "POST", f"{base}/projects/{pid}/generate")

    interval = float(ppt_cfg.get("poll_interval_seconds", 3))
    deadline = time.monotonic() + float(ppt_cfg.get("poll_timeout_seconds", 600))
    while True:
        if time.monotonic() > deadline:
            raise RenderError("生成逾時，請到 PPT_Generator 前端查看專案狀態")
        time.sleep(interval)
        progress = _request(session, "GET", f"{base}/projects/{pid}/progress")
        if progress.get("last_error"):
            raise RenderError(f"生成失敗：{progress['last_error']}")
        stage = progress.get("stage")
        slides = progress.get("slides", [])
        done = sum(1 for s in slides if s.get("status") == "done")
        print(f"    進度 {done}/{len(slides)}（stage={stage}）", file=sys.stderr)
        if stage != "generating":
            break

    print("6/6 匯出 PPTX ...", file=sys.stderr)
    export = _request(session, "POST", f"{base}/projects/{pid}/export")
    for warning in export.get("warnings", []):
        print(f"    警告：{warning}", file=sys.stderr)

    download_url = export["download_url"]
    # download_url 形如 /api/projects/{id}/exports/{filename}，與 base 的 /api prefix 重疊
    origin = base[: -len("/api")] if base.endswith("/api") else base
    try:
        resp = session.get(f"{origin}{download_url}", timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RenderError(f"下載 PPTX 失敗：{exc}") from exc

    output_path = markdown_path.with_suffix(".pptx")
    output_path.write_bytes(resp.content)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="週報 Markdown → PPTX")
    parser.add_argument("markdown", type=Path, help="審好稿的週報 .md 路徑")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--name", help="PPT_Generator 專案名稱（預設用檔名）")
    args = parser.parse_args()

    try:
        ppt_cfg = load_ppt_config(args.config)
        name = args.name or f"週報 {args.markdown.stem}"
        output = render(args.markdown, ppt_cfg, name)
        print(f"完成：{output}", file=sys.stderr)
        return 0
    except RenderError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
