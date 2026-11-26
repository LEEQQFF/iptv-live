#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把网页提交的修改（GitHub Issue 载荷）合并到 config/manual_overrides.json。

网页是纯静态的 GitHub Pages，无法匿名写仓库；因此网页生成带标记和 JSON 的
Issue，由本脚本在 GitHub Actions 中读取、校验、合并，随后 pipeline 重新运行，
结果自动提交并发布到公网订阅地址。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES = ROOT / "config" / "manual_overrides.json"
REPORT = ROOT / "output" / "web-edit-result.json"
MARKER = "<!-- iptv-live:apply -->"
CST = timezone(timedelta(hours=8))


def now_cn() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def clean_text(v, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def extract_payload(body: str) -> dict | None:
    if not body or MARKER not in body:
        return None
    seg = body.split(MARKER, 1)[1]
    m = re.search(r"```(?:json)?\s*(.*?)```", seg, re.S)
    raw = m.group(1) if m else seg.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception as e:
        print(f"[网页修改] JSON 解析失败：{e}", flush=True)
        return None


def normalize_ops(payload: dict) -> list[dict]:
    if isinstance(payload.get("ops"), list):
        return [o for o in payload["ops"] if isinstance(o, dict)]
    if isinstance(payload.get("changes"), list):
        return [o for o in payload["changes"] if isinstance(o, dict)]
    op = payload.get("op")
    if op:
        return [payload]
    ops: list[dict] = []
    for k, target in (("channel_names", "rename_channel"), ("channel_groups", "move_channel")):
        m = payload.get(k)
        if isinstance(m, dict):
            for key, value in m.items():
                ops.append({"op": target, "key": key,
                            "name" if target == "rename_channel" else "group": value})
    return ops


def load() -> dict:
    if OVERRIDES.exists():
        try:
            d = json.loads(OVERRIDES.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in {
                    "channel_names": {}, "channel_groups": {}, "groups": [],
                    "group_aliases": {}, "source_adds": [], "source_removals": [], "history": [],
                }.items():
                    d.setdefault(k, v)
                return d
        except Exception:
            pass
    return {"schema": 1, "updated": "", "channel_names": {}, "channel_groups": {},
            "groups": [], "group_aliases": {}, "source_adds": [], "source_removals": [],
            "history": []}


def source_name(url: str) -> str:
    host = urlparse(url).netloc or "source"
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:6]
    return f"web-{host[:18]}-{h}"


def apply(ov: dict, ops: list[dict]) -> tuple[int, list[str], bool]:
    applied = 0
    notes: list[str] = []
    need_discover = False
    for op in ops:
        kind = str(op.get("op") or "").strip()
        if kind == "discover":
            need_discover = True
            applied += 1
            notes.append("auto-discover")
            continue
        if kind == "rename_channel":
            key = clean_text(op.get("key"), 200)
            name = clean_text(op.get("name"), 60)
            if key and name:
                ov["channel_names"][key] = name
                applied += 1
                notes.append(f"rename:{key} -> {name}")
        elif kind == "move_channel":
            key = clean_text(op.get("key"), 200)
            grp = clean_text(op.get("group"), 40)
            if key and grp:
                ov["channel_groups"][key] = grp
                if grp not in ov["groups"]:
                    ov["groups"].append(grp)
                applied += 1
                notes.append(f"group:{key} -> {grp}")
        elif kind == "add_group":
            grp = clean_text(op.get("name"), 40)
            if grp and grp not in ov["groups"]:
                ov["groups"].append(grp)
                applied += 1
                notes.append(f"add-group:{grp}")
        elif kind == "rename_group":
            old = clean_text(op.get("from"), 40)
            new = clean_text(op.get("to"), 40)
            if old and new and old != new:
                ov["group_aliases"][old] = new
                ov["groups"] = [new if g == old else g for g in ov["groups"]]
                ov["channel_groups"] = {k: (new if v == old else v)
                                        for k, v in ov["channel_groups"].items()}
                applied += 1
                notes.append(f"rename-group:{old} -> {new}")
        elif kind in ("add_source", "add_sources"):
            items = op.get("sources") if kind == "add_sources" else [op]
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                url = clean_text(item.get("url"), 1000)
                if not url.startswith(("http://", "https://")):
                    continue
                entries = []
                for e in (item.get("entries") or [])[:200]:
                    if not isinstance(e, dict):
                        continue
                    eu = clean_text(e.get("url"), 1000)
                    if eu.startswith(("http://", "https://")):
                        entries.append({"name": clean_text(e.get("name"), 60) or "手动直播源",
                                        "url": eu})
                name = clean_text(item.get("name"), 80) or source_name(url)
                exists = next((s for s in ov["source_adds"]
                               if s.get("url") == url or s.get("name") == name), None)
                add = {"name": name, "url": url, "entries": entries}
                if exists:
                    exists.update(add)
                else:
                    ov["source_adds"].append(add)
                applied += 1
                notes.append(f"add-source:{name} ({len(entries) or 1})")
        elif kind == "remove_source":
            name = clean_text(op.get("name"), 80)
            if name and name not in ov["source_removals"]:
                ov["source_removals"].append(name)
                applied += 1
                notes.append(f"remove-source:{name}")
    return applied, notes, need_discover


def main() -> None:
    body = os.environ.get("ISSUE_BODY", "")
    payload = extract_payload(body)
    result = {"updated": now_cn(), "applied": 0, "notes": [], "discover": False,
              "valid": bool(payload)}
    if payload:
        ops = normalize_ops(payload)
        ov = load()
        applied, notes, discover = apply(ov, ops)
        # 限量保护：防止误操作把配置撑爆
        ov["source_adds"] = ov["source_adds"][-80:]
        ov["history"] = (ov.get("history") or [])[-49:]
        ov["history"].append({"at": now_cn(), "count": applied, "notes": notes[:20]})
        ov["updated"] = now_cn()
        OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDES.write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf-8")
        result.update({"applied": applied, "notes": notes, "discover": discover})
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print("[网页修改] 未发现有效载荷，跳过", flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
