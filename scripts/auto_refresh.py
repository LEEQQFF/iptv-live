#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-minute rolling refresh for the manually curated iptv-live channel library.

Pipeline: fetch subscriptions -> parse/dedupe/regroup -> incremental liveness ->
rebuild channels.json + m3u subscriptions + web data.json.

Designed to be self-contained inside GitHub Actions: all inputs (raw library,
subscription URL list, cached M3U/JSON) live in the repository.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "iptv_pipeline"))

import parse_merge as pm  # noqa: E402
import regroup as rg  # noqa: E402
import check_liveness as cl  # noqa: E402

CACHE = ROOT / "tools" / "cache"
FULL_REFRESH_MINUTES = 180  # full re-check of all stable URLs every 3 hours
OFFICIAL_HOSTS = ("cctv.com", "cntv.cn", "bestv.cn")


def official_stream(stream: dict) -> bool:
    if stream.get("official"):
        return True
    u = str(stream.get("url", "")).lower()
    return any(host in u for host in OFFICIAL_HOSTS)


def now_cn() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def fetch_subscriptions() -> dict[str, int]:
    """Refresh cached M3U files; keep existing copy on failure."""
    import requests

    md = (ROOT / "SparkTV-默认订阅地址清单.md").read_text(encoding="utf-8")
    block = re.search(r"```text\n(.*?)```", md, re.S)
    urls = [u.strip() for u in block.group(1).splitlines() if u.strip()] if block else []

    def get(item):
        i, url = item
        target = CACHE / f"sub_{i:02d}.m3u"
        try:
            r = requests.get(url, timeout=(5, 25), headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            if len(r.content) < 100:
                return i, "skip", len(r.content)
            target.write_bytes(r.content)
            return i, "ok", len(r.content)
        except Exception as e:
            return i, "keep", str(e)[:80]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        rows = sorted(ex.map(get, enumerate(urls, 1)))
    return {"sources": len(urls), "fetched": sum(1 for _, s, _ in rows if s == "ok"),
            "kept": sum(1 for _, s, _ in rows if s == "keep"), "detail": rows}


def dedupe_streams(groups):
    """Global URL dedupe within each channel plus official/alive/latency ordering."""
    for g in groups:
        for ch in g["channels"]:
            seen = set()
            uniq = []
            for s in ch.get("streams", []):
                u = (s.get("url") or "").strip()
                if not u or u in seen:
                    continue
                seen.add(u)
                s["url"] = u
                s["official"] = official_stream(s)
                if "status" not in s:
                    s["status"] = "unknown"
                uniq.append(s)
            uniq.sort(key=lambda s: (
                0 if s.get("official") else 1,
                0 if s.get("status") == "alive" else (1 if s.get("status") == "unknown" else 2),
                int(s.get("ms") or 9999),
            ))
            ch["streams"] = uniq
            ch["alive"] = sum(1 for s in uniq if s.get("status") == "alive")
            ch["dead"] = sum(1 for s in uniq if s.get("status") == "dead")
            ch["official"] = sum(1 for s in uniq if s.get("official"))
            best = next((s["url"] for s in uniq if s.get("status") == "alive"), "")
            ch["best"] = best


def refresh_liveness(groups, force_after_minutes: int):
    """Re-check URLs not in cache, plus alive URLs older than threshold."""
    urls = sorted({s["url"].strip() for g in groups for c in g["channels"]
                   for s in c["streams"] if s.get("url", "").strip()})
    p = CACHE / "liveness.json"
    state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"results": {}}
    cached = state.get("results", {})

    stale = []
    for u in urls:
        v = cached.get(u)
        if not v:
            stale.append(u)
            continue
        if v.get("status") == "alive":
            try:
                t = datetime.fromisoformat(state["checkedAt"])
            except Exception:
                t = datetime.now(timezone(timedelta(hours=8))) - timedelta(hours=24)
            age = (datetime.now(timezone(timedelta(hours=8))) - t).total_seconds() / 60
            if age >= force_after_minutes:
                stale.append(u)

    if stale:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futures = {ex.submit(cl.check, u): u for u in stale}
            for fut in concurrent.futures.as_completed(futures):
                u = futures[fut]
                try:
                    cached[u] = fut.result()
                except Exception:
                    cached[u] = {"status": "dead", "code": 0, "ms": 9999,
                                 "bytes": 0, "reason": "refresh-error"}

    results = {u: cached.get(u, {"status": "unknown", "code": 0, "ms": 9999,
                                 "bytes": 0, "reason": "unchecked"}) for u in urls}
    p.write_text(json.dumps({"checkedAt": now_cn(), "results": results}, ensure_ascii=False),
                 encoding="utf-8")
    return {"total": len(urls), "rechecked": len(stale),
            "alive": sum(1 for v in results.values() if v.get("status") == "alive"),
            "dead": sum(1 for v in results.values() if v.get("status") == "dead")}


def apply_liveness(groups):
    state = json.loads((CACHE / "liveness.json").read_text(encoding="utf-8"))
    results = state.get("results", {})
    for g in groups:
        for c in g["channels"]:
            for s in c["streams"]:
                v = results.get(s["url"].strip())
                if v:
                    for k in ("status", "code", "ms", "bytes", "reason"):
                        if k in v:
                            s[k] = v[k]


def export_m3u(groups, data_meta):
    epg = "https://leeqqff.github.io/iptv-live/e.xml"

    def esc(v):
        return str(v or "").replace('"', "").replace(",", "，").replace("\n", " ").strip()

    def build(alive_only, limit):
        lines = [
            f'#EXTM3U x-tvg-url="{epg}" url-tvg="{epg}"',
            "# 订阅名称：iptv-live 自动维护频道库",
            f"# 生成时间：{now_cn()}",
            "# 来源 channels.json：聚合去重 -> 央视/卫视/省级/网络归类 -> 严格检活 -> 官方源置顶",
            "",
        ]
        chans = streams = 0
        for g in groups:
            lines.append(f"# ===== {g['name']} =====")
            for c in g["channels"]:
                ss = [s for s in c["streams"] if s.get("status") == "alive"] if alive_only else list(c["streams"])
                if limit:
                    ss = ss[:limit]
                if not ss:
                    continue
                chans += 1
                name = esc(c.get("name")); tid = esc(c.get("id"))
                tname = esc((c.get("name") or "").split()[0])
                logo = f' tvg-logo="{esc(c["logo"])}"' if c.get("logo") else ""
                for s in ss:
                    u = (s.get("url") or "").strip()
                    if not u:
                        continue
                    lines.append(f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{tname}"{logo}'
                                 f' group-title="{esc(g["name"])}",{name}')
                    lines.append(u)
                    streams += 1
            lines.append("")
        return "\n".join(lines) + "\n", chans, streams

    primary, pc, ps = build(True, 5)
    full, fc, fs = build(False, 0)
    (ROOT / "iptv-live.m3u").write_text(primary, encoding="utf-8")
    (ROOT / "iptv-live-all.m3u").write_text(full, encoding="utf-8")
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "manual-live.m3u").write_text(primary, encoding="utf-8")
    return {"primary": {"channels": pc, "streams": ps}, "full": {"channels": fc, "streams": fs}}


def export_web_data(groups, meta):
    """Compact JSON for the browser dashboard (source/group/liveness relations)."""
    data = {
        "updated": now_cn(),
        "meta": meta,
        "groups": [],
    }
    for g in groups:
        chans = []
        for c in g["channels"]:
            streams = [{
                "url": s.get("url", ""),
                "status": s.get("status", "unknown"),
                "ms": s.get("ms", 9999),
                "src": s.get("src", ""),
                "quality": s.get("quality", ""),
                "official": bool(s.get("official")),
                "label": s.get("label", ""),
            } for s in c.get("streams", [])]
            streams.sort(key=lambda s: (0 if s["official"] else 1,
                                        0 if s["status"] == "alive" else 2,
                                        s["ms"] if isinstance(s["ms"], int) else 9999))
            chans.append({
                "id": c.get("id", ""), "name": c.get("name", ""),
                "logo": c.get("logo", ""), "province": c.get("province", ""),
                "streams": streams,
            })
        data["groups"].append({"name": g["name"], "channels": chans})
    (ROOT / "web").mkdir(parents=True, exist_ok=True)
    (ROOT / "web" / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return len(data["groups"])


def main():
    started = time.time()
    meta = {"run": now_cn()}
    meta["subscriptions"] = fetch_subscriptions()

    # parse_merge.main() reads cached M3U and writes merged.json; regroup.main() writes regrouped.json
    pm.main()
    rg.main()

    merged = json.loads((CACHE / "regrouped.json").read_text(encoding="utf-8"))
    groups = merged["groups"]
    dedupe_streams(groups)
    meta["liveness"] = refresh_liveness(groups, FULL_REFRESH_MINUTES)
    apply_liveness(groups)
    dedupe_streams(groups)

    final = dict(merged)
    final["groups"] = groups
    final["updated"] = now_cn()
    final["source"] = "SparkTV assets/channels.json + 11 个公开订阅源；10 分钟自动维护"
    final["stats"] = {
        "channels": sum(len(g["channels"]) for g in groups),
        "streams": sum(len(c["streams"]) for g in groups for c in g["channels"]),
        "unique_urls": len({s["url"] for g in groups for c in g["channels"] for s in c["streams"]}),
        "official_streams": sum(1 for g in groups for c in g["channels"] for s in c["streams"] if s.get("official")),
        "alive_streams": sum(1 for g in groups for c in g["channels"] for s in c["streams"] if s.get("status") == "alive"),
    }
    (ROOT / "channels.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    meta["m3u"] = export_m3u(groups, final["stats"])
    meta["web_groups"] = export_web_data(groups, final["stats"])
    meta["stats"] = final["stats"]
    meta["elapsed_sec"] = round(time.time() - started, 1)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
