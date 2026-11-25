#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse cached subscription M3U files, merge with the offline channel library,
deduplicate streams, classify channels, and write an intermediate merged.json."""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"

GROUP_ORDER = ["央视", "卫视", "地方", "港澳台", "其他"]

EN2CN = {
    "cctv": "CCTV",
    "anhuitv": "安徽卫视", "beijingtv": "北京卫视", "chongqingtv": "重庆卫视",
    "dragon.tv": "东方卫视", "fujiantv": "东南卫视", "gansutv": "甘肃卫视",
    "guangdongtv": "广东卫视", "guangxi.tv": "广西卫视", "guizhou.tv": "贵州卫视",
    "hainan.tv": "海南卫视", "hebeitv": "河北卫视", "henantv": "河南卫视",
    "heilongjiangtv": "黑龙江卫视", "hubeitv": "湖北卫视", "hunantv": "湖南卫视",
    "jilintv": "吉林卫视", "jiangxutv": "江西卫视", "jiangsu.tv": "江苏卫视",
    "liaoningtv": "辽宁卫视", "neimenggutv": "内蒙古卫视", "ningxiatv": "宁夏卫视",
    "qinghaitv": "青海卫视", "shandongtv": "山东卫视", "shanghaitv": "东方卫视",
    "shanxitv": "山西卫视", "sichuan.tv": "四川卫视", "tianjintv": "天津卫视",
    "xizangtv": "西藏卫视", "xinjiangtv": "新疆卫视", "yunnantv": "云南卫视",
    "zhejiangtv": "浙江卫视", "hk": "香港", "taiwan": "台湾", "macau": "澳门",
}

PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
]

PROVINCE_EN = {
    "anhui": "安徽", "beijing": "北京", "brtv": "北京", " Chongqing": "重庆", "chongqing": "重庆",
    "fujian": "福建", "gansu": "甘肃", "guangdong": "广东", "guangxi": "广西", "guizhou": "贵州",
    "hainan": "海南", "hebei": "河北", "heilongjiang": "黑龙江", "henan": "河南",
    "hubei": "湖北", "hunan": "湖南", "jilin": "吉林", "jiangsu": "江苏", "jiangxi": "江西",
    "liaoning": "辽宁", "neimenggu": "内蒙古", "ningxia": "宁夏", "qinghai": "青海",
    "shaanxi": "陕西", "shandong": "山东", "shanghai": "上海", "shanxi": "山西",
    "sichuan": "四川", "tianjin": "天津", "xizang": "西藏", "xinjiang": "新疆",
    "yunnan": "云南", "zhejiang": "浙江", "harbin": "哈尔滨", "guangzhou": "广州",
    "shenzhen": "深圳", "hebi": "鹤壁", "yanbian": "延边", "ningbo": "宁波",
    "chengdu": "成都", "nanjing": "南京", "wuhan": "武汉", "xian": "西安",
    "changsha": "长沙", "kunming": "昆明", "guiyang": "贵阳", "foshan": "佛山",
    "dongguan": "东莞", "suzhou": "苏州", "qingdao": "青岛", "dalian": "大连",
    "shenyang": "沈阳", "changchun": "长春", "shijiazhuang": "石家庄", "taiyuan": "太原",
    "hefei": "合肥", "nanchang": "南昌", "jinan": "济南", "zhengzhou": "郑州",
    "haikou": "海口", "lanzhou": "兰州", "xining": "西宁", "yinchuan": "银川",
    "hohhot": "呼和浩特", "lhasa": "拉萨", "urumqi": "乌鲁木齐", "hongkong": "香港",
    "taiwan": "台湾", "macau": "澳门",
}

SKIP_RE = re.compile(
    r"春晚|春节联欢|历年|198\d年|199\d年|20[0-2]\d年.*(春晚|晚会)|"
    r"^支持作者$|测试频道|test channel|"
    r"\b(DW|CNN|BBC|Fox|GB News|Global News|ION|FIFA|Fashion TV|ELEVEN|ASTRO|Viu|NOW|Discovery|HBO|Netflix|Amazon|Youtube|Radio|FM\d+)\b",
    re.I,
)

FOREIGN_RE = re.compile(
    r"\b(DW|CNN|BBC|Fox|GB News|Global News|ION|FIFA|Fashion|ELEVEN|ASTRO|Viu|NOW|Discovery|HBO|Netflix|Amazon|Youtube|Fight Network|Eurosport|CNN)\b",
    re.I,
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】", "", s)
    s = re.sub(r"\b(4K|8K|1080[pPiI]?|720[pPiI]?|2160[pPiI]?|HD|SD|UHD|FHD)\b", "", s, flags=re.I)
    s = re.sub(r"高清|标清|超清|蓝光|频道|电视台|直播|线路[一二三四五六七八九十\d]*", "", s)
    s = re.sub(r"[精品⊙Ⓖ\*✔✓◉●·\-—_+,./\\|\[\]（）()\s]+", "", s)
    return s.lower()


def canonical_name(name: str, group: str = "") -> str:
    n = norm(name)
    low = str(name or "").lower()
    for en, cn in EN2CN.items():
        if en in low and len(en) >= 5:
            return cn
    m = re.search(r"cctv\s*[-·]?\s*(\d+)", n)
    if m:
        return f"CCTV-{m.group(1)}"
    if "卫星电视" in str(name) or "satellite tv" in low:
        for en, cn in PROVINCE_EN.items():
            if en in low:
                return f"{cn}卫视"
    for en, cn in sorted(PROVINCE_EN.items(), key=lambda kv: -len(kv[0])):
        if en in low:
            return cn + (str(name).split(en, 1)[-1].split("(")[0].split("[")[0].strip() or "")
    if "央视" in str(name) or "cctv" in n:
        return "央视"
    if "卫视" in str(name):
        return str(name).strip()
    return str(name or "").strip()


def classify(name: str, group: str = "", src: str = "") -> str:
    s = f"{name or ''} {group or ''}"
    low = s.lower()
    if re.search(r"cctv|央视|中央电视", norm(name)) or "央视" in group or "cctv" in group.lower():
        return "央视"
    if re.search(r"香港|澳门|台湾|港澳|港台|hongkong|hong kong|macao|macau|taiwan|tvb|翡翠|明珠|华视|中视|台视", s, re.I):
        return "港澳台"
    if "卫视" in name or "卫视" in group or re.search(r"satellite", low):
        return "卫视"
    if any(p in s for p in PROVINCES) or any(k in group for k in ["地方", "省级", "市级", "县级"]):
        return "地方"
    for en in PROVINCE_EN:
        if en in low:
            return "地方"
    if src and not FOREIGN_RE.search(str(name)) and re.search(
        r"iptv|best-fan|best-fan|suxuang|guovin|bestk|yang|vbskycn|ssili126|bf_|cn_", src, re.I
    ):
        return "地方"
    return "其他"


def parse_extinf(text: str, src: str):
    lines = text.splitlines()
    out = []
    pending = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            if "," in line:
                attrs, display = line.rsplit(",", 1)
            else:
                attrs, display = line, ""
            kv = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
            title = (kv.get("tvg-name") or display or kv.get("tvg-id") or "").strip()
            if re.search(r"\d{4}-\d{2}-\d{2}", title) or "更新时间" in (kv.get("group-title") or ""):
                pending = None
                continue
            if not title:
                pending = None
                continue
            pending = {
                "title": title,
                "display": display.strip(),
                "tvg_name": kv.get("tvg-name", ""),
                "tvg_id": kv.get("tvg-id", ""),
                "group_title": kv.get("group-title", ""),
                "logo": kv.get("tvg-logo", ""),
                "ua": kv.get("http-user-agent", ""),
                "src": src,
            }
        elif pending and not line.startswith("#"):
            if line.startswith("http://") or line.startswith("https://"):
                out.append((pending, line))
            pending = None
    return out


def stream_sort_key(stream: dict):
    return (
        0 if stream.get("official") else 1,
        0 if stream.get("status") == "alive" else 1,
        stream.get("ms") if isinstance(stream.get("ms"), int) and stream["ms"] < 9000 else 9999,
    )


def main():
    raw = json.loads((ROOT / "channels.raw.json").read_text(encoding="utf-8"))
    groups = {g["name"]: g for g in raw["groups"]}
    for g in groups.values():
        for ch in g["channels"]:
            ch["_origin"] = "channels.raw.json"

    # Alias index for matching subscription names to the offline library.
    alias = {}
    for g in groups.values():
        for ch in g["channels"]:
            for key in {norm(ch["name"]), norm(ch.get("id", "")), norm(ch["name"].replace("频道", ""))}:
                if key and key not in alias:
                    alias[key] = ch
            m = re.search(r"cctv\s*[-·]?\s*(\d+)", norm(ch["name"]))
            if m:
                alias.setdefault(f"cctv{m.group(1)}", ch)

    # Collect subscription rows.
    src_names = {
        1: "best-fan 央视卫视地方(每日存活校验)", 2: "best-fan 卫视(每日存活校验)",
        3: "best-fan 央视(每日存活校验)", 4: "YanG Gather", 5: "suxuang ipv4",
        6: "vbskycn iptv4", 7: "iptv-org cn", 8: "iptv-org cn(github.io)",
        9: "ssili126 itvlist", 10: "Guovin iptv-api result(存活校验)",
        11: "bestK iptv",
    }
    rows = []
    for i in range(1, 12):
        f = CACHE / f"sub_{i:02d}.m3u"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for meta, url in parse_extinf(text, src_names.get(i, f"sub_{i:02d}")):
            rows.append((meta, url))

    # Channel map: canonical group/name -> channel dict.
    channel_map = {}
    for gname, g in groups.items():
        for ch in g["channels"]:
            key = (gname, norm(ch["name"]))
            channel_map[key] = ch

    unmatched = 0
    skipped = 0
    for meta, url in rows:
        title = meta["title"]
        if SKIP_RE.search(title) or FOREIGN_RE.search(title):
            skipped += 1
            continue
        cname = canonical_name(title, meta["group_title"])
        grp = classify(title, meta["group_title"], meta["src"])
        ch = None
        # Match CCTV numbers first, then exact normalized names.
        m = re.search(r"cctv\s*[-·]?\s*(\d+)", norm(title))
        if m:
            ch = alias.get(f"cctv{m.group(1)}")
        if ch is None:
            for k in (norm(title), norm(cname), norm(meta["display"]), norm(meta["tvg_id"])):
                if k and k in alias:
                    ch = alias[k]
                    break
        if ch is None:
            # Substring match for names like "BRTV 北京卫视 (1080p)" or "湖南新闻频道".
            n = norm(title)
            for k, v in alias.items():
                if len(k) >= 4 and k in n:
                    ch = v
                    break
        if ch is None:
            key = (grp, norm(cname))
            ch = channel_map.get(key)
        if ch is None:
            unmatched += 1
            existing = next((c for c in channel_map.values() if c["_origin"] != "channels.raw.json" and norm(c["name"]) == norm(cname)), None)
            if existing:
                ch = existing
            else:
                ch = {
                    "id": f"auto_{grp}_{norm(cname)[:24] or 'ch'}",
                    "name": cname,
                    "logo": meta["logo"],
                    "province": "",
                    "city": "",
                    "county": "",
                    "streams": [],
                    "_origin": "subscription",
                }
                channel_map[(grp, norm(cname))] = ch
                groups.setdefault(grp, {"name": grp, "channels": []})["channels"].append(ch)

        existing_urls = {s["url"] for s in ch["streams"]}
        if url in existing_urls:
            continue
        q = "未知"
        if "4K" in meta["title"] or "4K" in meta["tvg_name"]:
            q = "4K"
        elif "1080" in meta["title"]:
            q = "1080P"
        elif "720" in meta["title"]:
            q = "720P"
        ch["streams"].append({
            "url": url,
            "quality": q,
            "src": meta["src"],
            "ms": 9999,
            "v6": False,
            "label": meta["display"] or meta["tvg_name"] or meta["title"],
            "official": False,
            "station": False,
            "ua": meta["ua"],
        })

    # Global URL dedupe statistics + per-stream cleanup.
    all_urls = {}
    for g in groups.values():
        for ch in g["channels"]:
            seen = set()
            keep = []
            for s in ch["streams"]:
                u = s["url"].strip()
                if not u or u in seen:
                    continue
                seen.add(u)
                all_urls.setdefault(u, []).append(f'{g["name"]}/{ch["name"]}')
                keep.append(s)
            ch["streams"] = keep

    # Rebuild groups in the requested order; keep any channel in its current group.
    ordered = []
    for gname in GROUP_ORDER:
        g = groups.get(gname)
        if not g:
            continue
        g["channels"] = sorted(g["channels"], key=lambda c: norm(c["name"]))
        ordered.append({"name": gname, "channels": g["channels"]})

    # Normalize legacy liveness fields.
    for g in ordered:
        for ch in g["channels"]:
            for s in ch["streams"]:
                ok = s.pop("ok", None)
                s.setdefault("status", "alive" if ok is True else ("dead" if ok is False else "unknown"))
                s.pop("ua", None) if not s.get("ua") else None

    merged = {
        "schema": 3,
        "updated": "2026-11-25",
        "source": "channels.raw.json + SparkTV 默认订阅地址清单（11 个公开 M3U/M3U8）",
        "groups": ordered,
        "stats": {
            "subscription_rows": len(rows),
            "subscription_skipped_rows": skipped,
            "subscription_unmatched_rows": unmatched,
            "channels": sum(len(g["channels"]) for g in ordered),
            "streams": sum(len(ch["streams"]) for g in ordered for ch in g["channels"]),
            "unique_urls": len(all_urls),
        },
    }
    out = CACHE / "merged.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(merged["stats"], ensure_ascii=False))
    for g in ordered:
        print(g["name"], len(g["channels"]), sum(len(c["streams"]) for c in g["channels"]))


if __name__ == "__main__":
    main()
