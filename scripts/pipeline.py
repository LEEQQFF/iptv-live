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
import hashlib
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
import names as nm     # 频道/直播源名称规范化（翻译、纠错、规范名）

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
    if typ == "fixed" or typ == "manual":
        return [{"raw_name": e["name"], "url": e["url"], "tvg_id": "", "logo": "",
                 "source": name, "whitelist": typ == "manual"} for e in src.get("entries", [])], "fixed"
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


# ---------------------------------------------------------------- 动态源（自动发现 + 网页手添）
def load_dynamic_sources(cfg: dict) -> list[dict]:
    """把自动发现源与网页手动添加源并入本次流水线输入。"""
    base = cfg["sources"]
    seen = set()
    for s in base:
        for u in (s.get("urls") or []):
            seen.add(legacy.url_key(u))
        for e in (s.get("entries") or []):
            seen.add(legacy.url_key(e.get("url", "")))

    extra: list[dict] = []
    auto_path = ROOT / "config" / "auto_sources.json"
    if auto_path.exists():
        try:
            auto = json.loads(auto_path.read_text(encoding="utf-8"))
            for e in auto.get("entries", []):
                u = str(e.get("url") or "").strip()
                if not e.get("enabled") or not u.startswith("http"):
                    continue
                k = legacy.url_key(u)
                if k in seen:
                    continue
                seen.add(k)
                label = str(e.get("name") or "").strip()[:60]
                if e.get("direct") and label:
                    extra.append({"name": f"auto-{len(extra) + 1:02d}", "type": "manual",
                                  "entries": [{"name": label, "url": u}]})
                else:
                    extra.append({"name": f"auto-{len(extra) + 1:02d}", "urls": [u]})
        except Exception as e:
            print(f"[动态源] 自动发现配置读取失败：{type(e).__name__}", flush=True)

    ov_path = ROOT / "config" / "manual_overrides.json"
    if ov_path.exists():
        try:
            ov = json.loads(ov_path.read_text(encoding="utf-8"))
            removed = set(ov.get("source_removals") or [])
            for s in ov.get("source_adds", []):
                name = str(s.get("name") or "web-source").strip()
                if name in removed:
                    continue
                entries = [e for e in (s.get("entries") or [])
                           if str(e.get("url") or "").startswith("http")]
                if entries:
                    for e in entries:
                        seen.add(legacy.url_key(e["url"]))
                    extra.append({"name": name, "type": "manual", "entries": entries})
                else:
                    u = str(s.get("url") or "").strip()
                    if not u.startswith("http") or legacy.url_key(u) in seen:
                        continue
                    seen.add(legacy.url_key(u))
                    extra.append({"name": name, "urls": [u]})
        except Exception as e:
            print(f"[动态源] 手动添加配置读取失败：{type(e).__name__}", flush=True)
    return extra


# ---------------------------------------------------------------- 归类
def classify_channel(name: str, item: dict, name_map: dict, city_map: dict) -> tuple[str, str, str]:
    """返回 (分组名, 规范频道名, tvg_id)。

    先经 names.canonical 把上游 raw 名翻译/修正为国内规范频道名，再归类。
    优先级：央视主频道 -> 央视系列 -> 卫视 -> 省级行政区 -> 网络。
    """
    raw = str(name or "")
    # 名称规范化：翻译英文/拼音、繁简统一、清理画质/地区/时长噪声
    canon = nm.canonical(raw, item)
    if not canon:  # 噪声/无效名称，交由 aggregate 跳过
        return "", "", ""
    s = rg.simplify(canon)

    # 央视主频道 CCTV1-17 / CCTV+1..3，按序号
    m = re.search(r"CCTV\s*[-·]?\s*(\d{1,2})", s, re.I)
    if m and 1 <= int(m.group(1)) <= 17:
        num = int(m.group(1))
        plus = "+" in canon
        disp = f"CCTV-{num}{'+' if plus else ''}"
        return "央视", disp, f"cctv{num}{'+' if plus else ''}"
    # 央视系列（CHC/CGTN/CETV/央视付费频道等）
    if rg.CCTV_SERIES_RE.search(s):
        return "央视系列", canon, rg.norm(canon)

    # 省级行政区（含港澳台）；用规范名推断，翻译后的省级频道也能正确归位
    prov = rg.infer_province(canon, item, name_map, city_map)
    if prov:
        if "卫视" in canon or "衛視" in canon:
            return "卫视", canon, rg.norm(canon)
        return prov, canon, rg.norm(canon)

    # 英文/拼音卫视兜底（规范名已是中文，通常不会走到这里）
    ws = legacy.WEISHI_ALIAS.get(s, s)
    if ws in legacy.WEISHI:
        return "卫视", ws, ws

    # 其余 -> 网络
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
                "uid": hashlib.md5(f"{grp}|{canon}|{url}".encode("utf-8")).hexdigest()[:10],
                "name": canon,
                "name_source": str(it.get("raw_name") or raw),
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


# ---------------------------------------------------------------- 网页人工维护
def apply_manual_overrides(groups: list[dict], name_map: dict, city_map: dict) -> tuple[list[dict], dict]:
    """应用网页提交的改名/归类/分组重命名，并按新名称重新归类。

    人工名称写入 channel.name（维护名），上游原始名保留在 channel.name_source。
    """
    path = ROOT / "config" / "manual_overrides.json"
    if not path.exists():
        return groups, {"renamed": 0, "moved": 0}
    try:
        ov = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return groups, {"renamed": 0, "moved": 0}

    alias = {str(k): str(v) for k, v in (ov.get("group_aliases") or {}).items() if k and v}
    names = {str(k): str(v).strip()[:60] for k, v in (ov.get("channel_names") or {}).items()
             if k and str(v).strip()}
    gmap = {str(k): str(v).strip()[:40] for k, v in (ov.get("channel_groups") or {}).items()
            if k and str(v).strip()}

    pairs: list[list] = []
    for g in groups:
        gname = alias.get(g["name"], g["name"])
        for ch in g.get("channels", []):
            g["name"] = gname
            pairs.append([gname, ch])

    renamed = moved = 0
    for pair in pairs:
        gname, ch = pair
        keys = [ch.get("uid", ""), ch.get("id", ""), ch.get("name", ""), ch.get("name_source", "")]
        new_name = next((names[k] for k in keys if k in names), None)
        if new_name:
            if new_name != ch.get("name"):
                renamed += 1
            ch["name"] = new_name
            ch["name_maintained"] = True
        target = next((gmap[k] for k in keys if k in gmap), None)
        if target:
            target = alias.get(target, target)
        elif new_name:
            target, _, _ = classify_channel(new_name,
                                            {"raw_name": new_name}, name_map, city_map)
        if target and target != gname:
            pair[0] = target
            moved += 1

    order = list(dict.fromkeys([g["name"] for g in groups] +
                               [str(x) for x in (ov.get("groups") or [])] +
                               [p[0] for p in pairs]))
    buckets: dict[str, list] = defaultdict(list)
    for gname, ch in pairs:
        buckets[gname].append(ch)
    result = []
    for gname in order:
        if gname in buckets:
            chans = buckets[gname]
            if gname == "央视":
                chans.sort(key=lambda c: (rg.cctv_key(c["name"]), rg.norm(c["name"])))
            else:
                chans.sort(key=lambda c: rg.norm(c["name"]))
            result.append({"name": gname, "channels": chans})
    return result, {"renamed": renamed, "moved": moved}


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
                # 规范显示名：CCTV-N 综合 -> CCTV-N（订阅端名称尽量短且规范）
                disp = c["name"]
                m = re.match(r"(CCTV-\d{1,2}\+?)\s+\S", disp)
                if m:
                    disp = m.group(1)
                name, tid = esc(disp), esc(c["id"])
                tname = esc(disp)
                # tvg-logo 仅保留短地址，超长 URL（如 imgur 直链）直接省略，
                # 避免 EXTINF 行过长导致部分播放器解析失败
                logo_url = str(c.get("logo") or "").strip()
                logo = f' tvg-logo="{esc(logo_url)}"' if logo_url and len(logo_url) <= 120 else ""
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

    disc_path = ROOT / "output" / "discovery.json"
    discovery = {}
    if disc_path.exists():
        try:
            d = json.loads(disc_path.read_text(encoding="utf-8"))
            discovery = {k: d.get(k, []) if isinstance(d.get(k, []), list) else d.get(k, 0)
                         for k in ("updated", "mode", "repos", "candidates", "validated",
                                   "valid", "repaired", "fail_samples", "active_sources")}
        except Exception:
            pass

    data = {
        "updated": now_cn(),
        "meta": meta,
        "discovery": discovery,
        "subscriptions": [
            {"name": n, "url": src_urls.get(n, ""),
             "status": health.get(n, {}).get("status", ""),
             "items": health.get(n, {}).get("items", 0)}
            for n in sorted(health)
        ],
        "addresses": {
            # 所有公网地址尽量短：Pages 根路径 + 单字符文件名；较长 CDN/raw 仅作备用。
            "primary": "https://leeqqff.github.io/iptv-live/l.m3u",
            "ultra": "https://leeqqff.github.io/iptv-live/l",
            "pages": "https://leeqqff.github.io/iptv-live/l.m3u",
            "all": "https://leeqqff.github.io/iptv-live/a.m3u",
            "epg": "https://leeqqff.github.io/iptv-live/e.xml",
            "web": "https://leeqqff.github.io/iptv-live/",
            "raw": "https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/iptv-live.m3u",
            "cdn": "https://fastly.jsdelivr.net/gh/LEEQQFF/iptv-live@main/iptv-live.m3u",
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
            chans.append({"id": c.get("id", ""), "uid": c.get("uid", ""),
                          "name": c.get("name", ""),
                          "name_source": c.get("name_source", c.get("name", "")),
                          "logo": c.get("logo", ""), "streams": streams})
        data["groups"].append({"name": g["name"], "channels": chans})
    (ROOT / "web").mkdir(exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False)
    (ROOT / "web" / "data.json").write_text(payload, encoding="utf-8")
    # data.js：以全局变量提供同样的数据，script 标签加载，兼容 file:// 与所有浏览器
    # （fetch 在 file:// 下被 CORS 拦截，导致其他浏览器打开网页无数据）
    (ROOT / "web" / "data.js").write_text(
        "window.__IPTV_DATA__=" + payload + ";\n", encoding="utf-8")


def export_editable(groups: list[dict]) -> None:
    import csv
    ed = ROOT / "editable"
    ed.mkdir(exist_ok=True)
    headers = ["分组", "频道名称-维护", "频道名称-源名", "线路数", "存活", "失效", "官方", "最佳线路", "ID", "UID"]
    for g in groups:
        with (ed / f"{g['name']}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for c in g["channels"]:
                w.writerow([g["name"], c["name"], c.get("name_source", ""), len(c["streams"]),
                            c.get("alive", 0), c.get("dead", 0), c.get("official", 0),
                            c.get("best", ""), c.get("id", ""), c.get("uid", "")])


def main():
    started = time.time()
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    # 网页手动添加的源、自动发现并校验通过的源，统一并入本次全链条
    extra = load_dynamic_sources(cfg)
    ov_path = ROOT / "config" / "manual_overrides.json"
    removed = set()
    if ov_path.exists():
        try:
            removed = set(json.loads(ov_path.read_text(encoding="utf-8")).get("source_removals") or [])
        except Exception:
            pass
    cfg["sources"] = [s for s in cfg["sources"] if s.get("name") not in removed] + extra
    sources = cfg["sources"]
    print(f"[配置] 源 {len(sources)} 个（动态新增 {len(extra)}）", flush=True)

    items, health = fetch_all(cfg)
    print(f"[抓取] 原始条目 {len(items)}", flush=True)

    raw = json.loads((ROOT / "channels.raw.json").read_text(encoding="utf-8"))
    name_map, city_map = rg.build_name_maps(raw)
    agg = aggregate(items, cfg, name_map, city_map)
    groups = agg["groups"]
    groups, manual = apply_manual_overrides(groups, name_map, city_map)
    print(f"[人工维护] 改名 {manual['renamed']} / 调组 {manual['moved']}", flush=True)
    print(f"[聚合] 频道 {sum(len(g['channels']) for g in groups)} / 线路 "
          f"{sum(len(c['streams']) for g in groups for c in g['channels'])}", flush=True)

    live = refresh_liveness(groups, cfg)
    print(f"[检活] 复检 {live['rechecked']} / 总 {live['total']}", flush=True)
    status = apply_liveness_and_order(groups, live["results"], cfg)

    final = {
        "schema": 4,
        "updated": now_cn(),
        "source": "config/sources.yaml 全部源（含 SparkTV 11 地址 + channels.json 内置库）",
        "grouping": [g["name"] for g in groups],
        "ordering": "官方/白名单 > 存活 > 延迟升序；央视 CCTV1-17，省级按行政区，非行政区归网络；网页人工维护优先",
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
            "dynamic_sources": len(extra),
            "manual_renamed": manual.get("renamed", 0),
            "manual_moved": manual.get("moved", 0),
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
