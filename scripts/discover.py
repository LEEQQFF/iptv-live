#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅地址监测 / 自动发现 / 上游修正。

链路：
  1. 从现有 sources.yaml、已发现源、GitHub 公开仓库、公开网页中收集候选订阅地址；
  2. 解析订阅地址的更高层级仓库（GitHub owner/repo），读取其 README 与仓库树，
     寻找同一仓库内更正确、更多的 m3u/m3u8/txt 订阅文件；
  3. 对候选地址做真实抓取 + 解析校验，只有能解析出足够直播线路的地址才启用；
  4. 结果写入 config/auto_sources.json（流水线自动纳入），报告写入 output/discovery.json。

参数：
  --light   滚动维护时轻量执行（默认）；--full 全量检索（网页“自动发现”触发）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import main as legacy  # noqa: E402  复用抓取/解析/去重键

AUTO = ROOT / "config" / "auto_sources.json"
REPORT = ROOT / "output" / "discovery.json"
SOURCES = ROOT / "config" / "sources.yaml"
UA = legacy.UA
CST = timezone(timedelta(hours=8))
API = "https://api.github.com"

URL_RE = re.compile(r'https?://[^\s<>"\'`)\]]+?(?:\.m3u8?|\.txt)(?:\?[^\s<>"\'`)\]]*)?', re.I)
REPO_PATTERNS = [
    re.compile(r'raw\.githubusercontent\.com/([^/]+)/([^/]+)/', re.I),
    re.compile(r'(?:^|//)github\.com/([^/]+)/([^/]+)/', re.I),
    re.compile(r'cdn\.jsdelivr\.net/gh/([^/]+)/([^/]+)[@/]', re.I),
    re.compile(r'fastly\.jsdelivr\.net/gh/([^/]+)/([^/]+)[@/]', re.I),
    re.compile(r'ghgo\.xyz/raw\.githubusercontent\.com/([^/]+)/([^/]+)/', re.I),
    re.compile(r'([^/.]+)\.github\.io/([^/]+)/', re.I),
]

SEARCH_QUERIES = [
    "iptv china m3u in:name,description,readme",
    "iptv 直播 m3u8 in:name,description,readme",
    "iptv cn playlist in:name,description,readme",
]


def now_cn() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def gh_get(path: str, params: dict | None = None) -> dict | list | None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(API + path, params=params, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.json()
        print(f"[GitHub] {path} -> {r.status_code}", flush=True)
    except Exception as e:
        print(f"[GitHub] {path} -> {type(e).__name__}", flush=True)
    return None


def extract_repo(url: str) -> str:
    for p in REPO_PATTERNS:
        m = p.search(url or "")
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return ""


def seed_urls() -> list[str]:
    urls: list[str] = []
    try:
        cfg = yaml.safe_load(SOURCES.read_text(encoding="utf-8")) or {}
        for s in cfg.get("sources", []):
            urls.extend(s.get("urls") or [])
            if s.get("path"):
                urls.append(str(s["path"]))
    except Exception:
        pass
    if AUTO.exists():
        try:
            st = json.loads(AUTO.read_text(encoding="utf-8"))
            urls.extend(e.get("url", "") for e in st.get("entries", []))
        except Exception:
            pass
    seen, out = set(), []
    for u in urls:
        if not u or not u.startswith("http"):
            continue
        k = legacy.url_key(u)
        if k not in seen:
            seen.add(k)
            out.append(u)
    return out


def search_repos(limit: int = 8) -> list[str]:
    found: list[str] = []
    for q in SEARCH_QUERIES:
        data = gh_get("/search/repositories",
                      {"q": q, "sort": "updated", "order": "desc", "per_page": limit})
        if not isinstance(data, dict):
            continue
        for it in data.get("items", []):
            if it.get("archived"):
                continue
            name = it.get("full_name", "")
            if name and name not in found:
                found.append(name)
    return found


def web_search_urls(limit: int = 30) -> list[dict]:
    """从公开网页检索 m3u/txt 订阅地址（失败静默跳过，不影响主流程）。"""
    out: list[dict] = []
    queries = [
        "iptv 中国 m3u8 订阅地址 raw.githubusercontent.com",
        "iptv cn m3u playlist github",
    ]
    for q in queries:
        try:
            r = requests.get("https://html.duckduckgo.com/html/",
                             params={"q": q}, headers={"User-Agent": UA}, timeout=15)
            if r.status_code != 200:
                continue
            for u in URL_RE.findall(r.text):
                u = u.replace("&amp;", "&")
                if u.startswith("http"):
                    out.append({"url": u, "from_repo": "web-search", "from_file": q})
                if len(out) >= limit:
                    return out
        except Exception as e:
            print(f"[网页检索] {type(e).__name__}", flush=True)
    return out


def crawl_repo(full_name: str, max_files: int = 12) -> list[dict]:
    """解析订阅地址的更高层级仓库：仓库树 + README + 所有订阅文件。"""
    info = gh_get(f"/repos/{full_name}")
    branch = info.get("default_branch") if isinstance(info, dict) else ""
    branch = branch or "main"
    tree = gh_get(f"/repos/{full_name}/git/trees/{quote(branch)}", {"recursive": "1"})
    files: list[str] = []
    if isinstance(tree, dict):
        for it in tree.get("tree", []):
            path = it.get("path", "")
            size = int(it.get("size") or 0)
            if it.get("type") != "blob" or size > 3_000_000:
                continue
            low = path.lower()
            if low.endswith((".m3u", ".m3u8", ".txt")) or low in ("readme.md", "readme.txt"):
                files.append(path)
        files.sort(key=lambda p: (0 if "readme" in p.lower() else 1, len(p)))
        files = files[:max_files]
    else:
        # GitHub API 不可用时仍尝试 raw README，保证发现链路不至于完全中断
        files = ["README.md", "readme.md"]

    out: list[dict] = []
    for path in files:
        raw = f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}"
        try:
            r = requests.get(raw, headers={"User-Agent": UA}, timeout=18)
            if r.status_code != 200 or not r.text:
                continue
            text = r.text[:1_500_000]
        except Exception:
            continue
        for u in URL_RE.findall(text):
            u = u.replace("&amp;", "&")
            if u.startswith("http"):
                out.append({"url": u, "from_repo": full_name, "from_file": path})
        # 订阅文件正文中的线路本身也是可用的直播源候选
        if path.lower().endswith((".m3u", ".m3u8", ".txt")):
            for it in legacy.parse_m3u(text, full_name)[:80]:
                u = it.get("url", "")
                if u.startswith("http") and legacy.url_key(u) != legacy.url_key(raw):
                    out.append({"url": u, "from_repo": full_name, "from_file": path,
                                "direct": True, "name": it.get("raw_name", "")})
    return out


def validate(url: str) -> dict:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return {"ok": False, "reason": "scheme"}
        if p.hostname in ("localhost", "127.0.0.1") or (p.hostname or "").startswith("192.168."):
            return {"ok": False, "reason": "private"}
        r = requests.get(url, headers={"User-Agent": UA}, timeout=16)
        if r.status_code != 200 or not r.text:
            return {"ok": False, "reason": f"http {r.status_code}"}
        text = r.text[:1_500_000]
        items = legacy.parse_m3u(text, "probe")
        urls = [i["url"] for i in items if i.get("url", "").startswith("http")]
        if len(urls) < 3:
            urls = [ln.strip() for ln in text.splitlines()
                    if ln.strip().startswith("http") and len(ln.strip()) > 20]
        return {"ok": len(urls) >= 3, "items": len(urls),
                "reason": "ok" if len(urls) >= 3 else "too_few"}
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__}


def load_state() -> dict:
    if AUTO.exists():
        try:
            st = json.loads(AUTO.read_text(encoding="utf-8"))
            if isinstance(st, dict) and isinstance(st.get("entries"), list):
                return st
        except Exception:
            pass
    return {"schema": 1, "updated": "", "repos": [], "entries": []}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="全量检索全网公开仓库/网页")
    ap.add_argument("--light", action="store_true", help="轻量巡检（默认）")
    args = ap.parse_args()
    full = args.full and not args.light

    state = load_state()
    base_keys = {legacy.url_key(u) for u in seed_urls()}
    repos = list(dict.fromkeys(
        [extract_repo(u) for u in seed_urls()] +
        state.get("repos", []) +
        (search_repos(8) if full else [])
    ))
    repos = [r for r in repos if r and "/" in r][:(18 if full else 4)]
    print(f"[发现] 巡检仓库 {len(repos)} 个（{'全量' if full else '轻量'}）", flush=True)

    candidates: dict[str, dict] = {}
    for repo in repos:
        for c in crawl_repo(repo, 12 if full else 6):
            u = c["url"]
            k = legacy.url_key(u)
            if k in base_keys or k in candidates:
                continue
            candidates[k] = c
    if full:
        for c in web_search_urls(30):
            k = legacy.url_key(c["url"])
            if k not in base_keys and k not in candidates:
                candidates[k] = c
    print(f"[发现] 候选地址 {len(candidates)} 个", flush=True)

    # 优先验证“订阅清单”型候选（非单条线路），再验证直播源直链
    ordered = sorted(candidates.values(), key=lambda c: (bool(c.get("direct")), c["url"]))
    ordered = ordered[:(80 if full else 24)]
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(validate, c["url"]): c for c in ordered}
        for fut in concurrent.futures.as_completed(futs):
            c = futs[fut]
            try:
                results[c["url"]] = fut.result()
            except Exception:
                results[c["url"]] = {"ok": False, "reason": "probe_error"}

    entries = {legacy.url_key(e["url"]): e for e in state.get("entries", [])}
    added, repaired = [], []
    for c in ordered:
        v = results.get(c["url"], {"ok": False, "reason": "timeout"})
        k = legacy.url_key(c["url"])
        old = entries.get(k)
        if v.get("ok"):
            item = {
                "url": c["url"],
                "enabled": True,
                "items": v.get("items", 0),
                "from_repo": c.get("from_repo", ""),
                "from_file": c.get("from_file", ""),
                "last_ok": now_cn(),
                "fail_count": 0,
            }
            if old and old.get("fail_count", 0) > 0:
                repaired.append(c["url"])
            entries[k] = item
            added.append(c["url"])
        elif old:
            old["fail_count"] = int(old.get("fail_count", 0)) + 1
            if old["fail_count"] >= 3:
                old["enabled"] = False
            old["last_fail"] = now_cn()
            old["last_reason"] = v.get("reason", "")

    # 启用数量上限：按可解析条目数排序，避免低质量源拖慢 10 分钟滚动
    enabled = [e for e in entries.values() if e.get("enabled")]
    enabled.sort(key=lambda e: (-(int(e.get("items") or 0)), e.get("url", "")))
    for e in enabled[30:]:
        e["enabled"] = False

    state = {
        "schema": 1,
        "updated": now_cn(),
        "repos": repos[:40],
        "entries": sorted(entries.values(), key=lambda e: (not e.get("enabled"), e.get("url", ""))),
    }
    AUTO.parent.mkdir(parents=True, exist_ok=True)
    AUTO.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    report = {
        "updated": now_cn(),
        "mode": "full" if full else "light",
        "repos": repos,
        "candidates": len(candidates),
        "validated": len(results),
        "valid": len(added),
        "repaired": repaired[:20],
        "active_sources": sum(1 for e in state["entries"] if e.get("enabled")),
        "entries": state["entries"][:60],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"repos": len(repos), "candidates": len(candidates),
                      "valid": len(added), "repaired": len(repaired),
                      "active": report["active_sources"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
