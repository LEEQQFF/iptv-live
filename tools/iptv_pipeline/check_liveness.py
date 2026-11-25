#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict liveness check: every unique stream URL is requested over the network.
Status is alive only when a real 2xx/3xx response delivers playlist or media bytes."""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"
MERGED = CACHE / "merged.json"
RESULT = CACHE / "liveness.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LOCAL = threading.local()


def session():
    s = getattr(LOCAL, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "*/*", "Connection": "keep-alive"})
        LOCAL.s = s
    return s


def looks_like_media(head: bytes) -> bool:
    if not head:
        return False
    if head[:1] == b"\x47" and len(head) >= 188:
        return True
    text = head[:2048].decode("utf-8", "ignore")
    if "#EXTM3U" in text or "#EXTINF" in text or re.search(r"^https?://\S+", text, re.M):
        return True
    if re.search(r"<html|<body|access denied|forbidden|not found|error", text, re.I) and len(text) < 4000:
        return False
    return len(head) >= 64


TRANSIENT = {"http_403", "http_429", "http_500", "http_502", "http_503", "timeout", "connection", "ssl"}


def check_once(url: str) -> dict:
    started = time.monotonic()
    try:
        r = session().get(url, timeout=(2.5, 5), stream=True, allow_redirects=True)
        code = r.status_code
        head = b""
        for chunk in r.iter_content(4096):
            head += chunk
            if len(head) >= 8192:
                break
        r.close()
        ok = 200 <= code < 400 and looks_like_media(head)
        return {
            "status": "alive" if ok else "dead",
            "code": code,
            "ms": int((time.monotonic() - started) * 1000),
            "bytes": len(head),
            "reason": "ok" if ok else (f"http_{code}" if not (200 <= code < 400) else "invalid_body"),
        }
    except Exception as exc:
        name = type(exc).__name__
        if "Timeout" in name:
            reason = "timeout"
        elif "Connection" in name or "Proxy" in name:
            reason = "connection"
        elif "SSLError" in name or "Certificate" in name:
            reason = "ssl"
        elif "TooManyRedirects" in name:
            reason = "redirect_loop"
        else:
            reason = name.lower()[:40]
        return {
            "status": "dead",
            "code": 0,
            "ms": int((time.monotonic() - started) * 1000),
            "bytes": 0,
            "reason": reason,
        }


def check(url: str) -> dict:
    best = None
    for attempt in range(2):
        best = check_once(url)
        if best["status"] == "alive" or best["reason"] not in TRANSIENT:
            break
        if attempt < 1:
            time.sleep(0.2)
    return best


def main():
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    urls = sorted({s["url"].strip() for g in merged["groups"] for c in g["channels"] for s in c["streams"] if s.get("url", "").strip()})
    done = json.loads(RESULT.read_text(encoding="utf-8")) if RESULT.exists() else {}
    cached = done.get("results", done) if isinstance(done, dict) else {}
    if isinstance(done, dict) and "results" in done:
        cached = {k: v for k, v in cached.items() if v.get("status") == "alive" or v.get("reason") not in TRANSIENT}
    todo = [u for u in urls if u not in cached]
    print(f"total={len(urls)} cached={len(cached)} todo={len(todo)}", flush=True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=64) as ex:
        futures = {ex.submit(check, u): u for u in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            u = futures[fut]
            cached[u] = fut.result()
            if i % 250 == 0 or i == len(todo):
                alive = sum(1 for v in cached.values() if v["status"] == "alive")
                print(f"checked={i}/{len(todo)} alive={alive} elapsed={int(time.monotonic()-started)}s", flush=True)

    ts = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    results = {u: cached[u] for u in urls}
    RESULT.write_text(json.dumps({"checkedAt": ts, "results": results}, ensure_ascii=False), encoding="utf-8")
    alive = sum(1 for v in results.values() if v["status"] == "alive")
    print(json.dumps({"checkedAt": ts, "total": len(urls), "alive": alive, "dead": len(urls) - alive}, ensure_ascii=False))


if __name__ == "__main__":
    main()
