#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 GitHub Actions 中给网页修改 Issue 回执并关闭。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "output" / "web-edit-result.json"
STATUS = ROOT / "output" / "status.json"


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    num = os.environ.get("ISSUE_NUMBER", "")
    if not (token and repo and num):
        print("[回执] 缺少 GitHub 上下文，跳过", flush=True)
        return
    res = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    stats = {}
    if STATUS.exists():
        try:
            stats = json.loads(STATUS.read_text(encoding="utf-8")).get("stats", {})
        except Exception:
            pass
    lines = [
        "✅ 直播源管理台修改已处理并自动发布。",
        "",
        f"- 应用操作：{res.get('applied', 0)} 项",
        f"- 自动发现：{'已执行全量检索' if res.get('discover') else '本次未触发'}",
        f"- 当前频道：{stats.get('channels', '-')} / 线路：{stats.get('streams', '-')} / 存活：{stats.get('alive_streams', '-')}",
        "- 公网订阅：https://leeqqff.github.io/iptv-live/l.m3u",
        "- 管理台：https://leeqqff.github.io/iptv-live/web/",
    ]
    notes = res.get("notes") or []
    if notes:
        lines += ["", "明细："] + [f"- {n}" for n in notes[:15]]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{repo}/issues/{num}"
    try:
        requests.post(base + "/comments",
                      headers=headers,
                      json={"body": "\n".join(lines)}, timeout=20)
        requests.patch(base, headers=headers, json={"state": "closed"}, timeout=20)
    except Exception as e:
        print(f"[回执] 失败：{type(e).__name__}", flush=True)


if __name__ == "__main__":
    main()
