"""Stage 1 收集器：從公司 GitLab 拉取近一週的個人活動，輸出 raw-activity.json。

不呼叫任何 LLM。輸出交給 /weekly-report skill（Claude Code）做摘要。

用法：
    uv run collector.py                        # 依 config.yaml 抓最近 N 天
    uv run collector.py --since 2026-07-20 --until 2026-07-26
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"
DEFAULT_OUTPUT = Path(__file__).parent / "data" / "raw-activity.json"
PER_PAGE = 100
MAX_PAGES = 10  # 單一列表最多抓 1000 筆，個人週活動遠低於此


class CollectorError(Exception):
    """設定或 API 層的可預期錯誤，訊息直接給使用者看。"""


# ---------- 設定 ----------


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise CollectorError(f"找不到設定檔 {path}，請先複製並編輯 config.yaml")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    gitlab = cfg.get("gitlab") or {}
    missing = [k for k in ("base_url", "username") if not gitlab.get(k)]
    if missing:
        raise CollectorError(f"config.yaml 的 gitlab 區塊缺少欄位：{', '.join(missing)}")
    if not cfg.get("repos"):
        raise CollectorError("config.yaml 的 repos 清單是空的，請至少填一個 namespace/project")
    if "example.com" in gitlab["base_url"]:
        raise CollectorError("gitlab.base_url 還是範本預設值，請改成公司 GitLab 網址")
    return cfg


def resolve_window(cfg: dict, since_arg: str | None, until_arg: str | None) -> tuple[date, date]:
    """回傳收集區間（含頭尾）。CLI 參數優先於 config 的 days。"""
    until = date.fromisoformat(until_arg) if until_arg else date.today()
    if since_arg:
        since = date.fromisoformat(since_arg)
    else:
        days = int(cfg.get("days", 7))
        since = until - timedelta(days=days - 1)
    if since > until:
        raise CollectorError(f"區間錯誤：since ({since}) 晚於 until ({until})")
    return since, until


def in_window(iso_timestamp: str | None, since: date, until: date) -> bool:
    """判斷 GitLab 回傳的 ISO 時間戳是否落在收集區間內（以本地日期計）。"""
    if not iso_timestamp:
        return False
    ts = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    local_day = ts.astimezone().date()
    return since <= local_day <= until


# ---------- GitLab API ----------


def api_get_all(session: requests.Session, url: str, params: dict) -> list[dict]:
    """抓完分頁的 GET，最多 MAX_PAGES 頁。"""
    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            resp = session.get(url, params={**params, "per_page": PER_PAGE, "page": page}, timeout=30)
        except requests.RequestException as exc:
            raise CollectorError(f"無法連線 GitLab（{url}）：{exc.__class__.__name__}") from exc
        if resp.status_code == 401:
            raise CollectorError("GitLab 回應 401：GITLAB_TOKEN 無效或過期，請重新產生（scope 需含 read_api）")
        if resp.status_code == 404:
            raise CollectorError(f"GitLab 回應 404：{url}\n請確認 config.yaml 的 repo 路徑（namespace/project）拼寫正確")
        if not resp.ok:
            raise CollectorError(f"GitLab API 錯誤 {resp.status_code}：{resp.text[:200]}")
        batch = resp.json()
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


def collect_project(
    session: requests.Session, gitlab_cfg: dict, repo_path: str, since: date, until: date
) -> dict:
    """收集單一 repo 的 MR／issue／commit 活動。"""
    api_base = gitlab_cfg["base_url"].rstrip("/") + "/api/v4"
    project = quote(repo_path, safe="")
    username = gitlab_cfg["username"]
    # updated_after 只是粗篩（GitLab 沒有 merged_after 參數），實際區間由 in_window 判定
    updated_after = f"{since.isoformat()}T00:00:00Z"

    mrs = api_get_all(
        session,
        f"{api_base}/projects/{project}/merge_requests",
        {"state": "merged", "author_username": username, "updated_after": updated_after},
    )
    merged_mrs = [
        {
            "title": mr["title"],
            "description": (mr.get("description") or "")[:500],
            "merged_at": mr.get("merged_at"),
            "web_url": mr.get("web_url"),
            "labels": mr.get("labels", []),
        }
        for mr in mrs
        if in_window(mr.get("merged_at"), since, until)
    ]

    closed_issues = [
        {
            "title": i["title"],
            "closed_at": i.get("closed_at"),
            "web_url": i.get("web_url"),
            "labels": i.get("labels", []),
        }
        for i in api_get_all(
            session,
            f"{api_base}/projects/{project}/issues",
            {"state": "closed", "assignee_username": username, "updated_after": updated_after},
        )
        if in_window(i.get("closed_at"), since, until)
    ]

    opened_issues = [
        {
            "title": i["title"],
            "created_at": i.get("created_at"),
            "web_url": i.get("web_url"),
            "labels": i.get("labels", []),
        }
        for i in api_get_all(
            session,
            f"{api_base}/projects/{project}/issues",
            {"author_username": username, "created_after": updated_after},
        )
        if in_window(i.get("created_at"), since, until)
    ]

    commits: list[dict] = []
    commit_author = gitlab_cfg.get("commit_author")
    if commit_author:
        commits = [
            {
                "title": c["title"],
                "created_at": c.get("created_at"),
                "web_url": c.get("web_url"),
            }
            for c in api_get_all(
                session,
                f"{api_base}/projects/{project}/repository/commits",
                {"since": updated_after, "author": commit_author, "all": "true"},
            )
            if in_window(c.get("created_at"), since, until)
        ]

    return {
        "repo": repo_path,
        "merged_mrs": merged_mrs,
        "closed_issues": closed_issues,
        "opened_issues": opened_issues,
        "commits": commits,
    }


# ---------- 主流程 ----------


def main() -> int:
    parser = argparse.ArgumentParser(description="收集 GitLab 個人週活動")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--since", help="起日 YYYY-MM-DD（預設依 config 的 days 回推）")
    parser.add_argument("--until", help="迄日 YYYY-MM-DD（預設今天）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        since, until = resolve_window(cfg, args.since, args.until)

        token = os.environ.get("GITLAB_TOKEN")
        if not token:
            raise CollectorError(
                "環境變數 GITLAB_TOKEN 未設定。\n"
                "請在 GitLab 個人設定產生 Personal Access Token（scope: read_api），"
                "並 export GITLAB_TOKEN=<token>（或寫入 .env 後 source）"
            )

        session = requests.Session()
        session.headers["PRIVATE-TOKEN"] = token

        projects = []
        for repo in cfg["repos"]:
            print(f"收集 {repo} ...", file=sys.stderr)
            projects.append(collect_project(session, cfg["gitlab"], repo, since, until))

        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "week_start": since.isoformat(),
            "week_end": until.isoformat(),
            "username": cfg["gitlab"]["username"],
            "projects": projects,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        total_mrs = sum(len(p["merged_mrs"]) for p in projects)
        total_issues = sum(len(p["closed_issues"]) for p in projects)
        print(
            f"完成：{since} ~ {until}，{len(projects)} 個 repo、"
            f"{total_mrs} 個 merged MR、{total_issues} 個 closed issue → {args.output}",
            file=sys.stderr,
        )
        return 0
    except CollectorError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
