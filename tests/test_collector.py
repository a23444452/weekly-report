"""collector 純邏輯測試（不打真實 API）。"""

from datetime import date
from pathlib import Path

import pytest

from collector import CollectorError, in_window, load_config, resolve_window


# ---------- resolve_window ----------


def test_resolve_window_defaults_to_config_days():
    since, until = resolve_window({"days": 7}, None, "2026-07-26")
    assert until == date(2026, 7, 26)
    assert since == date(2026, 7, 20)  # 含頭尾共 7 天


def test_resolve_window_cli_overrides_config():
    since, until = resolve_window({"days": 7}, "2026-07-01", "2026-07-03")
    assert (since, until) == (date(2026, 7, 1), date(2026, 7, 3))


def test_resolve_window_rejects_inverted_range():
    with pytest.raises(CollectorError):
        resolve_window({}, "2026-07-10", "2026-07-01")


# ---------- in_window ----------


def test_in_window_accepts_utc_z_suffix():
    assert in_window("2026-07-22T03:00:00Z", date(2026, 7, 20), date(2026, 7, 26))


def test_in_window_rejects_outside_range():
    assert not in_window("2026-07-19T23:59:59+00:00", date(2026, 7, 21), date(2026, 7, 26))


def test_in_window_rejects_none():
    assert not in_window(None, date(2026, 7, 20), date(2026, 7, 26))


# ---------- load_config ----------


def _write_config(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_ok(tmp_path):
    p = _write_config(
        tmp_path,
        """
gitlab:
  base_url: "https://gitlab.mycorp.local"
  username: "vince"
repos:
  - "team/repo-a"
""",
    )
    cfg = load_config(p)
    assert cfg["gitlab"]["username"] == "vince"


def test_load_config_rejects_missing_fields(tmp_path):
    p = _write_config(tmp_path, "gitlab:\n  base_url: 'https://g.mycorp.local'\nrepos: ['a/b']\n")
    with pytest.raises(CollectorError, match="username"):
        load_config(p)


def test_load_config_rejects_empty_repos(tmp_path):
    p = _write_config(
        tmp_path,
        "gitlab:\n  base_url: 'https://g.mycorp.local'\n  username: 'v'\nrepos: []\n",
    )
    with pytest.raises(CollectorError, match="repos"):
        load_config(p)


def test_load_config_rejects_template_placeholder(tmp_path):
    p = _write_config(
        tmp_path,
        "gitlab:\n  base_url: 'https://gitlab.example.com'\n  username: 'v'\nrepos: ['a/b']\n",
    )
    with pytest.raises(CollectorError, match="範本預設值"):
        load_config(p)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(CollectorError, match="找不到設定檔"):
        load_config(tmp_path / "nope.yaml")
