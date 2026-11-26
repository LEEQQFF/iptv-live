#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的 iptv-live 全链条流水线。

输入（全部来自 config/sources.yaml）：
  - 普通 M3U/TXT 源（含 SparkTV 默认订阅地址清单的 11 个地址）
  - 官方动态源（ysp / snrtv）、官方固定源（fixed）
  - 内置频道库 channels.json（type: builtin）

链条：
  抓取 -> 解析/归一化 -> 聚合 -> 去重(URL + 频道名别名) ->
  归类(央视/央视系列/卫视/34省级/港澳台/网络) -> 严格检活(增量缓存) ->
  官方源置顶(官方域名/白名单 > 存活 > 延迟升序) ->
  导出 channels.json / m3u 订阅 / Markdown / CSV / 网页 data.json

设计目标：GitHub Actions 每 10 分钟滚动执行；失败源沿用缓存，保证订阅不中断。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools" / "iptv_pipeline"))

import main as legacy  # 复用抓取/解析/归类/检活函数
import regroup as rg   # 复用省级/央视系列归类规则

CACHE = ROOT / "tools" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
UA = legacy.UA
CST = timezone(timedelta(hours=8))

OFFICIAL_HOSTS = ("cctv.com", "cntv.cn", "bestv.cn", "yangshipin.cn", "ysp.cctv.cn")
FULL_RECHECK_MINUTES = 180


def now_cn() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 抓取
def load_builtin(src: dict) -> list[dict]:
    """把 channels.json 内置库转成统一条目，带来源标记。"""
    path = ROOT / src.get("path", "channels.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for g in data.get("groups", []):
        for ch in g.get("channels", []):
            for s in ch.get("streams", []):
                u = (s.get("url") or "").strip()
                if not u:
                    continue
                items.append({
                    "raw_name": ch.get("name", ""),
                    "url": u,
                    "tvg_id": ch.get("id", ""),
                    "logo": ch.get("logo", ""),
                    "source": src["name"],
                    "province": ch.get("province", "") or (g["name"] if g["name"] in rg.PROVINCE_ORDER else ""),
                    "city": ch.get("city", ""),
                    "builtin_official": bool(s.get("official")),
                })
    return items


def fetch_one(src: dict) -> tuple[list[dict], str]:
    name = src["name"]
    typ = src.get("type", "m3u")
    if typ == "builtin":
        try:
            items = load_builtin(src)
            return items, f"ok ({len(items)}条, 内置库)"
        except Exception as e:
            return [], f"failed: {type(e).__name__}"
    if typ == "fixed":
        return [{"raw_name": e["name"], "url": e["url"], "tvg_id": "", "logo": "",
                 "source": name, "whitelist": True} for e in src.get("entries", [])], "fixed"
    if typ == "snrtv":
        try:
            from snrtv import fetch_snrtv
            es = fetch_snrtv()
            return [{"raw_name": e["name"], "url": e["url"], "tvg_id": "", "logo": "",
                     "source": name, "whitelist": True} for e in es], f"ok ({len(es)}条, 官方动态)"
        except Exception as e:
            return [], f"failed: {type(e).__name__}"
    if typ == "ysp":
        try:
            from ysp import fetch_yangshipin
            es = fetch_yangshipin()
            return [{"raw_name": e["name"], "url": e["url"], "tvg_id": "", "logo": "",
                     "source": name, "whitelist": True} for e in es], f"ok ({len(es)}条, 官方动态)"
        except Exception as e:
            return [], f"failed: {type(e).__name__}"

    # 普通 m3u/txt，按镜像顺序回退
    text, used = legacy.fetch_source(src)
    if not text:
        # 尝试本地缓存
        cache = CACHE / f"src_{re.sub(r'[^a-zA-Z0-9]+', '_', name)}.m3u"
        if cache.exists():
            text = cache.read_text(encoding="utf-8", errors="ignore")
            used = "缓存"
        else:
            return [], "failed"
    if used != "缓存":
        (CACHE / f"src_{re.sub(r'[^a-zA-Z0-9]+', '_', name)}.m3u").write_text(text, encoding="utf-8")
    items = legacy.parse_m3u(text, name)
    return items, f"ok ({len(items)}条, {used})"


def fetch_all(cfg: dict) -> tuple[list[dict], dict]:
    all_items, health = [], {}
    sources = cfg["sources"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_one, s): s["name"] for s in sources}
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                items, h = fut.result()
            except Exception as e:
                items, h = [], f"failed: {type(e).__name__}"
            health[name] = {"status": h, "items": len(items)}
            all_items.extend(items)
            print(f"[源] {name}: {h}", flush=True)
    return all_items, health


# ---------------------------------------------------------------- 归类
def classify_channel(name: str, item: dict, name_map: dict, city_map: dict) -> tuple[str, str, str]:
    """返回 (分组名, 规范频道名, tvg_id)。
    优先级：央视主频道 -> 央视系列 -> 卫视 -> 省级行政区 -> 网络。
    """
    raw = str(name or "")
    n = rg.norm(raw)
    s = rg.simplify(raw)

    # 央视主频道 CCTV1-17 / CCTV+1..3，按序号
    m = re.search(r"CCTV\s*[-·]?\s*(\d{1,2})", s, re.I)
    if m:
        num = int(m.group(1))
        if 1 <= num <= 17:
            plus = "+" in s[m.end():m.end()+2]
            disp = f"CCTV-{num}{'+' if plus else ''}"
            return "央视", disp, f"cctv{num}{'+' if plus else ''}"
    # 央视系列（CHC/CGTN/CETV/央视付费频道等）
    if rg.CCTV_SERIES_RE.search(s) or item.get("builtin_official"):
        canon = re.sub(r"\s+", "", raw)[:28] or "央视系列"
        return "央视系列", canon, rg.norm(canon)

    # 省级行政区（含港澳台）
    prov = rg.infer_province(raw, item, name_map, city_map)
    if prov:
        # 卫视：xx卫视 归入卫视组
        if "卫视" in raw or "衛視" in raw:
            return "卫视", re.sub(r"\s+", "", raw)[:28], rg.norm(raw)
        return prov, re.sub(r"\s+", "", raw)[:28], rg.norm(raw)

    # 英文/拼音卫视
    ws = legacy.WEISHI_ALIAS.get(s, s)
    if ws in legacy.WEISHI:
        return "卫视", ws, ws

    # 其余 -> 网络
    canon = re.sub(r"\s+", "", raw)[:40] or "未命名"
    return "网络", canon, rg.norm(canon)


# ---------------------------------------------------------------- 聚合 + 去重
def aggregate(items: list[dict], cfg: dict, name_map: dict, city_map: dict) -> dict:
    st = cfg["settings"]
    exclude = st.get("exclude_keywords", [])
    official_domains = tuple(st.get("official_domains", []))
    prevalidated = set(st.get("prevalidated_sources", []))

    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    url_index: dict[str, tuple[str, str, dict]] = {}  # url -> (group, name, stream)
    stats = Counter()

    for it in items:
        raw = str(it.get("raw_name") or "").strip()
        url = str(it.get("url") or "").strip()
        if not url or not raw:
            stats["skip_empty"] += 1
            continue
        if any(k in raw for k in exclude):
            stats["skip_excluded"] += 1
            continue
        if not re.match(r"https?://", url, re.I):
            stats["skip_nonhttp"] += 1
            continue

        # URL 级去重（忽略动态 token 查询参数）
        key = legacy.url_key(url)
        if key in url_index:
            g, n, stream = url_index[key]
            if it["source"] not in stream["sources"]:
                stream["sources"].append(it["source"])
            if it.get("whitelist"):
                stream["whitelist"] = True
            if it["source"] in prevalidated:
                stream["prevalidated"] = True
            stats["dedup_url"] += 1
            continue

        grp, canon, tid = classify_channel(raw, it, name_map, city_map)
        if not canon:
            stats["skip_unnamed"] += 1
            continue

        host = urlparse(url).netloc.lower()
        is_official = (it.get("builtin_official") or
                       any(host == d or host.endswith("." + d) for d in official_domains) or
                       any(h in host for h in OFFICIAL_HOSTS))
        stream = {
            "url": url,
            "sources": [it["source"]],
            "official": is_official,
            "whitelist": bool(it.get("whitelist")),
            "prevalidated": it["source"] in prevalidated,
            "ip": bool(re.match(r"^\d+\.\d+\.\d+\.\d+", host)),
            "src": it["source"],
            "quality": "",
            "label": "",
            "status": "unknown",
            "ms": 9999,
            "code": 0,
            "reason": "unchecked",
        }
        ch = groups[grp].get(canon)
        if not ch:
            ch = {
                "id": tid or rg.norm(canon),
                "name": canon,
                "logo": it.get("logo", ""),
                "province": it.get("province", "") or (grp if grp in rg.PROVINCE_ORDER else ""),
                "city": it.get("city", ""),
                "streams": [],
            }
            groups[grp][canon] = ch
        if not ch["logo"] and it.get("logo"):
            ch["logo"] = it["logo"]
        ch["streams"].append(stream)
        url_index[key] = (grp, canon, stream)

    # 组装为有序 groups
    ordered_names = []
    if "央视" in groups: ordered_names.append("央视")
    if "央视系列" in groups: ordered_names.append("央视系列")
    if "卫视" in groups: ordered_names.append("卫视")
    ordered_names += [p for p in rg.PROVINCE_ORDER if p in groups]
    if "网络" in groups: ordered_names.append("网络")
    ordered_names += [n for n in sorted(groups) if n not in ordered_names]

    result = []
    for gname in ordered_names:
        chans = list(groups[gname].values())
        if gname == "央视":
            chans.sort(key=lambda c: (rg.cctv_key(c["name"]), rg.norm(c["name"])))
        else:
            chans.sort(key=lambda c: rg.norm(c["name"]))
        result.append({"name": gname, "channels": chans})

    return {"groups": result, "grouping": ordered_names, "stats": dict(stats)}


# ---------------------------------------------------------------- 检活
def refresh_liveness(groups: list[dict], cfg: dict) -> dict:
    urls = sorted({s["url"] for g in groups for c in g["channels"] for s in c["streams"]})
    p = CACHE / "liveness.json"
    state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"results": {}}
    cached = state.get("results", {})
    pcfg = cfg["settings"].get("probe", {})
    timeout = pcfg.get("timeout", 8)
    workers = pcfg.get("workers", 64)

    stale = []
    for u in urls:
        v = cached.get(u)
        if not v:
            stale.append(u)
        elif v.get("status") == "alive":
            try:
                t = datetime.fromisoformat(state["checkedAt"])
            except Exception:
                t = datetime.now(CST) - timedelta(days=1)
            if (datetime.now(CST) - t).total_seconds() / 60 >= FULL_RECHECK_MINUTES:
                stale.append(u)

    # 每频道限量送测：优先未测/疑似存活，控制单次耗时
    max_pc = pcfg.get("max_per_channel", 8)
    priority = set(stale)
    for g in groups:
        for c in g["channels"]:
            cand = [s for s in c["streams"] if s["url"] in priority]
            cand.sort(key=lambda s: (0 if s["official"] else 1,
                                     0 if s.get("status") == "alive" else 1,
                                     s.get("ms", 9999)))
            for s in cand[max_pc:]:
                priority.discard(s["url"])
    stale = [u for u in stale if u in priority]

    if stale:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(legacy.probe_one, u, timeout): u for u in stale}
            for fut in concurrent.futures.as_completed(futs):
                u = futs[fut]
                try:
                    _, ok, lat = fut.result()
                    cached[u] = {"status": "alive" if ok else "dead",
                                 "code": 200 if ok else 0,
                                 "ms": int(lat * 1000) if lat else 9999,
                                 "bytes": 0, "reason": "ok" if ok else "probe_failed"}
                except Exception:
                    cached[u] = {"status": "dead", "code": 0, "ms": 9999,
                                 "bytes": 0, "reason": "probe_error"}

    results = {u: cached.get(u, {"status": "unknown", "code": 0, "ms": 9999,
                                 "bytes": 0, "reason": "unchecked"}) for u in urls}
    p.write_text(json.dumps({"checkedAt": now_cn(), "results": results}, ensure_ascii=False),
                 encoding="utf-8")
    return {"total": len(urls), "rechecked": len(stale), "results": results}


def apply_liveness_and_order(groups: list[dict], results: dict, cfg: dict) -> dict:
    """写回检活结果并排序：官方/白名单 > 存活 > 延迟升序。"""
    stats = Counter()
    for g in groups:
        for c in g["channels"]:
            for s in c["streams"]:
                v = results.get(s["url"], {})
                s["status"] = v.get("status", "unknown")
                s["ms"] = v.get("ms", 9999) if s["status"] == "alive" else 9999
                s["code"] = v.get("code", 0)
                s["reason"] = v.get("reason", "unchecked")
                stats[s["status"]] += 1
            c["streams"].sort(key=lambda s: (
                0 if (s["official"] or s.get("whitelist")) else 1,
                0 if s["status"] == "alive" else (1 if s["status"] == "unknown" else 2),
                s["ms"] if isinstance(s["ms"], int) else 9999,
            ))
            c["alive"] = sum(1 for s in c["streams"] if s["status"] == "alive")
            c["dead"] = sum(1 for s in c["streams"] if s["status"] == "dead")
            c["official"] = sum(1 for s in c["streams"] if s["official"])
            c["best"] = next((s["url"] for s in c["streams"] if s["status"] == "alive"), "")
    return dict(stats)


# ---------------------------------------------------------------- 导出
def export_m3u(groups: list[dict], sources: list[dict]) -> dict:
    epg = "https://leeqqff.github.io/iptv-live/e.xml"

    def esc(v):
        return str(v or "").replace('"', "").replace(",", "，").replace("\n", " ").strip()

    def build(alive_only: bool, limit: int) -> tuple[str, int, int]:
        lines = [
            f'#EXTM3U x-tvg-url="{epg}" url-tvg="{epg}"',
            "# 订阅名称：iptv-live 24小时滚动维护频道库",
            f"# 生成时间：{now_cn()}",
            "# 链条：多源聚合 -> 去重 -> 央视/卫视/省级/网络归类 -> 严格检活 -> 官方源置顶",
            f"# 源数量：{len(sources)}；过滤：{'仅存活线路' if alive_only else '全部线路'}",
            "",
        ]
        chans = streams = 0
        for g in groups:
            lines.append(f"# ===== {g['name']} =====")
            for c in g["channels"]:
                ss = [s for s in c["streams"] if s["status"] == "alive"] if alive_only else list(c["streams"])
                if limit:
                    ss = ss[:limit]
                if not ss:
                    continue
                chans += 1
                name, tid = esc(c["name"]), esc(c["id"])
                tname = esc(c["name"].split()[0]) if c["name"] else ""
                logo = f' tvg-logo="{esc(c["logo"])}"' if c.get("logo") else ""
                for s in ss:
                    u = s["url"].strip()
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
    return {"primary": {"channels": pc, "streams": ps},
            "full": {"channels": fc, "streams": fs}}


def export_web_data(groups: list[dict], cfg: dict, health: dict, sources: list[dict],
                    meta: dict) -> None:
    """网页数据：订阅地址清单 + 直播源 + 来源关系 + 归类 + 检活。"""
    src_urls = {}
    for s in sources:
        urls = s.get("urls") or ([s["path"]] if s.get("type") == "builtin" else [])
        src_urls[s["name"]] = urls[0] if urls else ""

    data = {
        "updated": now_cn(),
        "meta": meta,
        "subscriptions": [
            {"name": n, "url": src_urls.get(n, ""),
             "status": health.get(n, {}).get("status", ""),
             "items": health.get(n, {}).get("items", 0)}
            for n in sorted(health)
        ],
        "addresses": {
            "primary": "https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/iptv-live.m3u",
            "all": "https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/iptv-live-all.m3u",
            "pages": "https://leeqqff.github.io/iptv-live/manual-live.m3u",
            "epg": "https://leeqqff.github.io/iptv-live/e.xml",
        },
        "groups": [],
    }
    for g in groups:
        chans = []
        for c in g["channels"]:
            streams = [{
                "url": s.get("url", ""),
                "status": s.get("status", "unknown"),
                "ms": s.get("ms", 9999),
                "sources": s.get("sources", []),
                "src": s.get("src", ""),
                "official": bool(s.get("official")),
                "whitelist": bool(s.get("whitelist")),
            } for s in c.get("streams", [])]
            streams.sort(key=lambda s: (0 if (s["official"] or s["whitelist"]) else 1,
                                        0 if s["status"] == "alive" else 2,
                                        s["ms"] if isinstance(s["ms"], int) else 9999))
            chans.append({"id": c.get("id", ""), "name": c.get("name", ""),
                          "logo": c.get("logo", ""), "streams": streams})
        data["groups"].append({"name": g["name"], "channels": chans})
    (ROOT / "web").mkdir(exist_ok=True)
    (ROOT / "web" / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def export_editable(groups: list[dict]) -> None:
    import csv
    ed = ROOT / "editable"
    ed.mkdir(exist_ok=True)
    headers = ["分组", "频道", "线路数", "存活", "失效", "官方", "最佳线路", "ID"]
    for g in groups:
        with (ed / f"{g['name']}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for c in g["channels"]:
                w.writerow([g["name"], c["name"], len(c["streams"]), c.get("alive", 0),
                            c.get("dead", 0), c.get("official", 0), c.get("best", ""), c.get("id", "")])


def main():
    started = time.time()
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    sources = cfg["sources"]
    print(f"[配置] 源 {len(sources)} 个", flush=True)

    items, health = fetch_all(cfg)
    print(f"[抓取] 原始条目 {len(items)}", flush=True)

    raw = json.loads((ROOT / "channels.raw.json").read_text(encoding="utf-8"))
    name_map, city_map = rg.build_name_maps(raw)
    agg = aggregate(items, cfg, name_map, city_map)
    groups = agg["groups"]
    print(f"[聚合] 频道 {sum(len(g['channels']) for g in groups)} / 线路 "
          f"{sum(len(c['streams']) for g in groups for c in g['channels'])}", flush=True)

    live = refresh_liveness(groups, cfg)
    print(f"[检活] 复检 {live['rechecked']} / 总 {live['total']}", flush=True)
    status = apply_liveness_and_order(groups, live["results"], cfg)

    final = {
        "schema": 4,
        "updated": now_cn(),
        "source": "config/sources.yaml 全部源（含 SparkTV 11 地址 + channels.json 内置库）",
        "grouping": agg["grouping"],
        "ordering": "官方/白名单 > 存活 > 延迟升序；央视 CCTV1-17，省级按行政区，非行政区归网络",
        "liveness": {
            "checkedAt": now_cn(),
            "method": "逐条真实 HTTP GET，仅 2xx/3xx 且返回 M3U/TS 媒体字节判为存活",
            **status,
        },
        "stats": {
            "channels": sum(len(g["channels"]) for g in groups),
            "streams": sum(len(c["streams"]) for g in groups for c in g["channels"]),
            "unique_urls": len(live["results"]),
            "official_streams": sum(1 for g in groups for c in g["channels"] for s in c["streams"] if s["official"]),
            "alive_streams": status.get("alive", 0),
            "source_count": len(sources),
            "province_groups": len([g for g in groups if g["name"] in rg.PROVINCE_ORDER]),
        },
        "sources": [{"name": n, **v} for n, v in health.items()],
        "groups": groups,
    }
    (ROOT / "channels.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")

    m3u = export_m3u(groups, sources)
    export_web_data(groups, cfg, health, sources, final["stats"])
    export_editable(groups)

    # 状态报告
    (ROOT / "output" / "status.json").write_text(json.dumps({
        "updated_at": now_cn(),
        "pipeline": "scripts/pipeline.py",
        "source_count": len(sources),
        "stats": final["stats"],
        "source_health": health,
        "elapsed_sec": round(time.time() - started, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"stats": final["stats"], "m3u": m3u,
                      "elapsed_sec": round(time.time() - started, 1)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
