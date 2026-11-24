#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV 直播源自动聚合流水线
抓取 -> 解析 -> 归一化分类(央视/卫视/地方) -> 去重 -> 测活 -> 生成 m3u / txt / EPG
供 GitHub Actions 定时调用，也可本地运行：
    python scripts/main.py --config config/sources.yaml --out output
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
import yaml

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
CST = timezone(timedelta(hours=8))

# ---------------- 频道名归一化 ----------------

CCTV_SUFFIX = {
    "1": "综合", "2": "财经", "3": "综艺", "4": "中文国际", "5": "体育",
    "6": "电影", "7": "国防军事", "8": "电视剧", "9": "纪录", "10": "科教",
    "11": "戏曲", "12": "社会与法", "13": "新闻", "14": "少儿", "15": "音乐",
    "16": "奥林匹克", "17": "农业农村",
}
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
          "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13,
          "十四": 14, "十五": 15, "十六": 16, "十七": 17}

# 卫视 canonical -> 所属省份
WEISHI = {
    "北京卫视": "北京", "天津卫视": "天津", "河北卫视": "河北", "山西卫视": "山西",
    "内蒙古卫视": "内蒙古", "辽宁卫视": "辽宁", "吉林卫视": "吉林", "黑龙江卫视": "黑龙江",
    "东方卫视": "上海", "江苏卫视": "江苏", "浙江卫视": "浙江", "安徽卫视": "安徽",
    "东南卫视": "福建", "江西卫视": "江西", "山东卫视": "山东", "河南卫视": "河南",
    "湖北卫视": "湖北", "湖南卫视": "湖南", "广东卫视": "广东", "广西卫视": "广西",
    "海南卫视": "海南", "重庆卫视": "重庆", "四川卫视": "四川", "贵州卫视": "贵州",
    "云南卫视": "云南", "西藏卫视": "西藏", "陕西卫视": "陕西", "甘肃卫视": "甘肃",
    "青海卫视": "青海", "宁夏卫视": "宁夏", "新疆卫视": "新疆", "兵团卫视": "新疆",
    "深圳卫视": "广东", "厦门卫视": "福建", "康巴卫视": "四川", "延边卫视": "吉林",
    "三沙卫视": "海南", "大湾区卫视": "广东", "安多卫视": "青海",
}
WEISHI_ALIAS = {
    "上海卫视": "东方卫视", "福建卫视": "东南卫视", "旅游卫视": "海南卫视",
    "湖南卫视高清": "湖南卫视", "芒果台": "湖南卫视", "番茄台": "东方卫视",
    "荔枝台": "江苏卫视", "蓝莓台": "浙江卫视", "北京台": "北京卫视",
}

PROVINCES = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
             "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
             "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
             "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"]
CITY2PROV = {
    "长沙": "湖南", "株洲": "湖南", "湘潭": "湖南", "金鹰": "湖南",
    "广州": "广东", "深圳": "广东", "佛山": "广东", "东莞": "广东", "珠海": "广东", "珠江": "广东",
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "绍兴": "浙江",
    "南京": "江苏", "苏州": "江苏", "无锡": "江苏", "常州": "江苏", "徐州": "江苏",
    "成都": "四川", "绵阳": "四川", "武汉": "湖北", "宜昌": "湖北", "襄阳": "湖北",
    "西安": "陕西", "咸阳": "陕西", "郑州": "河南", "洛阳": "河南",
    "济南": "山东", "青岛": "山东", "烟台": "山东", "潍坊": "山东",
    "福州": "福建", "厦门": "福建", "泉州": "福建", "合肥": "安徽", "芜湖": "安徽",
    "南昌": "江西", "赣州": "江西", "昆明": "云南", "贵阳": "贵州", "遵义": "贵州",
    "南宁": "广西", "柳州": "广西", "桂林": "广西", "海口": "海南", "三亚": "海南",
    "石家庄": "河北", "唐山": "河北", "保定": "河北", "太原": "山西", "大同": "山西",
    "呼和浩特": "内蒙古", "沈阳": "辽宁", "大连": "辽宁", "长春": "吉林",
    "哈尔滨": "黑龙江", "大庆": "黑龙江", "兰州": "甘肃", "西宁": "青海",
    "银川": "宁夏", "乌鲁木齐": "新疆", "拉萨": "西藏", "安顺": "贵州",
    "白城": "吉林", "白山": "吉林", "通化": "吉林", "延吉": "吉林", "敦化": "吉林",
    "南国都市": "广东", "伊犁": "新疆", "喀什": "新疆", "克拉玛依": "新疆",
    "东阳": "浙江", "湘西": "湖南", "延边": "吉林", "雄安": "河北",
}

# iptv-org 等项目的英文命名卫视映射
EN_WS = {
    "Beijing": "北京卫视", "Tianjin": "天津卫视", "Hebei": "河北卫视",
    "Shanxi": "山西卫视", "InnerMongolia": "内蒙古卫视", "Liaoning": "辽宁卫视",
    "Jilin": "吉林卫视", "Heilongjiang": "黑龙江卫视", "Dragon": "东方卫视",
    "Shanghai": "东方卫视", "Jiangsu": "江苏卫视", "Zhejiang": "浙江卫视",
    "Anhui": "安徽卫视", "Fujian": "东南卫视", "Southeast": "东南卫视",
    "Jiangxi": "江西卫视", "Shandong": "山东卫视", "Henan": "河南卫视",
    "Hubei": "湖北卫视", "Hunan": "湖南卫视", "Guangdong": "广东卫视",
    "Guangxi": "广西卫视", "Hainan": "海南卫视", "Chongqing": "重庆卫视",
    "Sichuan": "四川卫视", "Guizhou": "贵州卫视", "Yunnan": "云南卫视",
    "Tibet": "西藏卫视", "Shaanxi": "陕西卫视", "Gansu": "甘肃卫视",
    "Qinghai": "青海卫视", "Ningxia": "宁夏卫视", "Xinjiang": "新疆卫视",
    "Bingtuan": "兵团卫视", "Shenzhen": "深圳卫视", "Xiamen": "厦门卫视",
    "Kangba": "康巴卫视", "Yanbian": "延边卫视", "Sansha": "三沙卫视",
}


def clean_name(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 去括号备注
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"(高清|超清|蓝光|标清|FHD|HD|SD|UHD|4K|8K|1080[pP]?|720[pP]?|540[pP]?)", "", s, flags=re.I)
    s = s.replace("－", "-").replace("—", "-").replace("·", "")
    return s.strip()


def classify(raw: str):
    """返回 (canonical_key, display_name, group, tvg_id)；无法归类返回 None"""
    s = clean_name(raw)
    if not s or re.fullmatch(r"[\d\-: .]+", s):
        return None
    # 英文命名卫视（iptv-org）
    m = re.match(r"^([A-Za-z]+)SatelliteTV", s)
    if m and m.group(1) in EN_WS:
        canon = EN_WS[m.group(1)]
        return canon, canon, "卫视频道", canon
    # CCTV
    m = re.search(r"CCTV[-_]?(\d{1,2})(\+|PLUS)?", s, re.I)
    if m:
        n = m.group(1)
        if n in CCTV_SUFFIX:
            plus = bool(m.group(2))
            key = f"CCTV{n}+" if plus else f"CCTV{n}"
            disp = f"CCTV-{n}{'+' if plus else ''} {CCTV_SUFFIX[n]}"
            return key, disp, "央视频道", key
    m = re.search(r"央视(?:一套|二套|三套|四套|五套|六套|七套|八套|九套|十套|十一套|十二套|十三套|十四套|十五套|十六套|十七套)", s)
    if m:
        cn = m.group(0)[2:]
        n = str(CN_NUM[cn])
        return f"CCTV{n}", f"CCTV-{n} {CCTV_SUFFIX[n]}", "央视频道", f"CCTV{n}"
    if re.search(r"^CGTN", s, re.I):
        lang = re.sub(r"^CGTN[-_]?", "", s, flags=re.I) or "英语"
        lang = {"英语": "", "英语频道": "", "纪录": "纪录", "法语": "法语", "西班牙语": "西语",
                "阿拉伯语": "阿语", "俄语": "俄语"}.get(lang, lang)
        key = f"CGTN{lang}"
        return key, key, "央视频道", key
    if re.search(r"中国教育[-_]?[1-4一二三四]?", s) or re.search(r"^CETV[-_]?[1-4]?", s, re.I):
        m2 = re.search(r"([1-4一二三四])", s)
        n = str(CN_NUM.get(m2.group(1), m2.group(1))) if m2 else "1"
        return f"CETV{n}", f"CETV-{n}", "央视频道", f"CETV{n}"
    # 卫视
    ws = WEISHI_ALIAS.get(s, s)
    if ws in WEISHI:
        return ws, ws, "卫视频道", ws
    m = re.match(r"^(.{2,4}?)卫视", s)
    if m and m.group(1) in [p for p in PROVINCES]:
        canon = m.group(1) + "卫视"
        return canon, canon, "卫视频道", canon
    # 地方频道：省名前缀 / 城市前缀
    for p in PROVINCES:
        if s.startswith(p):
            return s, s, f"地方·{p}", s
    for city, prov in CITY2PROV.items():
        if s.startswith(city):
            return s, s, f"地方·{prov}", s
    return None


# ---------------- 抓取与解析 ----------------

def http_get(url, timeout=25, stream=False):
    return requests.get(url, headers={"User-Agent": UA}, timeout=timeout,
                        stream=stream, allow_redirects=True)


def fetch_source(src):
    """按镜像顺序尝试，返回 (text, used_url) 或 (None, None)"""
    for url in src.get("urls", []):
        try:
            r = http_get(url)
            if r.status_code == 200 and r.text and len(r.text) > 50:
                return r.text, url
        except Exception as e:
            print(f"  [跳过] {url} -> {type(e).__name__}", flush=True)
    return None, None


def parse_m3u(text, source_name):
    """解析 m3u 与 txt 两种格式，返回条目列表"""
    items = []
    if "#EXTM3U" in text[:200] or "#EXTINF" in text:
        attrs = {}
        name = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF"):
                attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
                name = line.rsplit(",", 1)[-1].strip()
            elif line and not line.startswith("#"):
                if name:
                    items.append({
                        "raw_name": attrs.get("tvg-name") or name,
                        "url": line,
                        "tvg_id": attrs.get("tvg-id", ""),
                        "logo": attrs.get("tvg-logo", ""),
                        "source": source_name,
                    })
                name = None
    else:  # txt: 频道名,地址 ；分类,#genre#
        for line in text.splitlines():
            line = line.strip()
            if not line or "#genre#" in line or "," not in line:
                continue
            nm, _, url = line.partition(",")
            url = url.split("$")[0].strip()
            if url.startswith("http"):
                items.append({"raw_name": nm.strip(), "url": url, "tvg_id": "",
                              "logo": "", "source": source_name})
    return items


def url_key(url):
    """去重键：忽略动态 token 等查询参数"""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}".lower()


# ---------------- 测活 ----------------

def probe_one(url, timeout):
    t0 = time.time()
    try:
        r = http_get(url, timeout=timeout, stream=True)
        if r.status_code != 200:
            r.close()
            return url, False, None
        chunk = b""
        for part in r.iter_content(chunk_size=4096):
            chunk += part
            if len(chunk) >= 4096:
                break
        r.close()
        ct = r.headers.get("Content-Type", "").lower()
        ok = (b"#EXTM3U" in chunk or b"#EXT-X-" in chunk
              or "mpegurl" in ct or "octet-stream" in ct
              or chunk[:3] == b"\x47\x40\x11" or len(chunk) >= 4096)
        return url, ok, round(time.time() - t0, 2)
    except Exception:
        return url, False, None


def probe_urls(urls, timeout, workers):
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(probe_one, u, timeout): u for u in urls}
        for f in concurrent.futures.as_completed(futs):
            u, ok, lat = f.result()
            result[u] = (ok, lat)
    return result


# ---------------- EPG ----------------

def build_epg(cfg, wanted_ids, out_path):
    import xml.etree.ElementTree as ET
    keep_days = cfg.get("keep_days", 3)
    now = datetime.now(CST)
    lo = now.strftime("%Y%m%d")
    hi = (now + timedelta(days=keep_days)).strftime("%Y%m%d")
    raw = None
    for url in cfg.get("urls", []):
        try:
            print(f"[EPG] 尝试 {url}", flush=True)
            r = http_get(url, timeout=60)
            if r.status_code == 200 and "<tv" in r.text[:2000]:
                raw = r.content
                print(f"[EPG] 成功，{len(raw)/1e6:.1f} MB", flush=True)
                break
        except Exception as e:
            print(f"[EPG] 失败 {type(e).__name__}", flush=True)
    if raw is None:
        if os.path.exists(out_path) and os.path.getsize(out_path) > 200:
            print("[EPG] 全部镜像失败，保留上一版 e.xml", flush=True)
            return "kept-previous"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="iptv-auto"></tv>\n')
        return "empty"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # 截断容错：补闭合
        try:
            root = ET.fromstring(raw + b"</tv>")
        except Exception:
            return "parse-error"
    wanted = set(wanted_ids)
    kept_channels, kept_progs = [], 0
    out = ET.Element("tv", {"generator-info-name": "iptv-auto"})
    for ch in root.findall("channel"):
        cid = ch.get("id", "")
        names = [d.text or "" for d in ch.findall("display-name")]
        if cid in wanted or any(n in wanted for n in names):
            out.append(ch)
            kept_channels.append(cid)
    kc = set(kept_channels)
    for pr in root.findall("programme"):
        cid = pr.get("channel", "")
        start = pr.get("start", "")[:8]
        if cid in kc and lo <= start <= hi:
            out.append(pr)
            kept_progs += 1
    ET.ElementTree(out).write(out_path, encoding="UTF-8", xml_declaration=True)
    print(f"[EPG] 保留 {len(kept_channels)} 个频道 / {kept_progs} 条节目", flush=True)
    return "ok"


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--out", default="output")
    ap.add_argument("--no-probe", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    st = cfg["settings"]
    os.makedirs(args.out, exist_ok=True)

    # 1. 抓取
    all_items, source_health = [], {}
    for src in cfg["sources"]:
        if src.get("type") == "fixed":
            for e in src.get("entries", []):
                all_items.append({"raw_name": e["name"], "url": e["url"],
                                  "tvg_id": "", "logo": "", "source": src["name"]})
            source_health[src["name"]] = "fixed"
            continue
        text, used = fetch_source(src)
        if text:
            items = parse_m3u(text, src["name"])
            all_items.extend(items)
            source_health[src["name"]] = f"ok ({len(items)}条, {used})"
            print(f"[源] {src['name']}: {len(items)} 条", flush=True)
        else:
            source_health[src["name"]] = "failed"
            print(f"[源] {src['name']}: 全部镜像失败", flush=True)
    print(f"[汇总] 原始条目 {len(all_items)}", flush=True)

    # 2. 归一化 + 分类 + 去重
    exclude = st.get("exclude_keywords", [])
    official = tuple(st.get("official_domains", []))
    channels = {}   # key -> dict
    seen = set()
    dropped = 0
    for it in all_items:
        if any(k in it["raw_name"] for k in exclude):
            continue
        c = classify(it["raw_name"])
        if c is None:
            if st.get("include_other"):
                key = clean_name(it["raw_name"])
                c = (key, key, "其他频道", it["tvg_id"] or key)
            else:
                dropped += 1
                continue
        key, disp, group, tid = c
        uk = url_key(it["url"])
        dk = (key, uk)
        if dk in seen:
            continue
        seen.add(dk)
        host = urlparse(it["url"]).netloc.lower()
        is_official = any(host == d or host.endswith("." + d) for d in official)
        ch = channels.setdefault(key, {"display": disp, "group": group,
                                       "tvg_id": tid, "logo": it["logo"], "urls": []})
        ch["urls"].append({"url": it["url"], "official": is_official,
                           "source": it["source"], "alive": None, "lat": None})
    print(f"[分类] 频道 {len(channels)} 个，未归类剔除 {dropped} 条", flush=True)

    # 3. 测活（每频道限量送测）
    pcfg = st.get("probe", {})
    probe_enabled = pcfg.get("enabled", True) and not args.no_probe
    if probe_enabled:
        max_pc = pcfg.get("max_per_channel", 8)
        to_probe = []
        for ch in channels.values():
            ch["urls"].sort(key=lambda x: (not x["official"], x["source"]))
            for u in ch["urls"][:max_pc]:
                to_probe.append(u["url"])
        to_probe = list(dict.fromkeys(to_probe))
        print(f"[测活] {len(to_probe)} 个接口，并发 {pcfg.get('workers', 32)}", flush=True)
        res = probe_urls(to_probe, pcfg.get("timeout", 8), pcfg.get("workers", 32))
        alive = sum(1 for ok, _ in res.values() if ok)
        ratio = alive / max(1, len(res))
        print(f"[测活] 存活 {alive}/{len(res)} ({ratio:.1%})", flush=True)
        if ratio < pcfg.get("min_alive_ratio", 0.05):
            print("[测活] 存活率过低，判定环境网络受限：跳过过滤，仅排序", flush=True)
            probe_enabled = False
        else:
            for ch in channels.values():
                for u in ch["urls"]:
                    if u["url"] in res:
                        u["alive"], u["lat"] = res[u["url"]]

    # 4. 排序筛选 + 生成 m3u / txt
    max_urls = st.get("max_urls_per_channel", 5)
    logo_tpl = st.get("logo_template", "")
    group_order = {"央视频道": 0, "卫视频道": 1}
    def gsort(g):
        return (group_order.get(g, 2), g)
    ordered = sorted(channels.values(), key=lambda c: (gsort(c["group"]), c["display"]))

    m3u_lines = ['#EXTM3U x-tvg-url="e.xml" url-tvg="e.xml"']
    txt_lines = []
    final_channels, final_urls = 0, 0
    cur_group = None
    for ch in ordered:
        urls = ch["urls"]
        if probe_enabled:
            alive_urls = [u for u in urls if u["alive"]]
            if not alive_urls:
                continue
            alive_urls.sort(key=lambda u: (not u["official"], u["lat"] or 999))
            urls = alive_urls
        else:
            urls.sort(key=lambda u: (not u["official"], u["source"]))
        urls = urls[:max_urls]
        if not urls:
            continue
        if ch["group"] != cur_group:
            cur_group = ch["group"]
            txt_lines.append(f"{cur_group},#genre#")
        logo = ch["logo"] or (logo_tpl.format(id=ch["tvg_id"]) if logo_tpl else "")
        for u in urls:
            m3u_lines.append(
                f'#EXTINF:-1 tvg-id="{ch["tvg_id"]}" tvg-name="{ch["tvg_id"]}" '
                f'tvg-logo="{logo}" group-title="{ch["group"]}",{ch["display"]}')
            m3u_lines.append(u["url"])
            txt_lines.append(f'{ch["display"]},{u["url"]}')
            final_urls += 1
        final_channels += 1

    with open(os.path.join(args.out, "live.m3u"), "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines) + "\n")
    with open(os.path.join(args.out, "live.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines) + "\n")

    # 5. EPG
    wanted = {ch["tvg_id"] for ch in ordered} | {ch["display"] for ch in ordered}
    epg_status = build_epg(st.get("epg", {}), wanted, os.path.join(args.out, "e.xml"))

    # 6. 状态报告
    status = {
        "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "channels": final_channels,
        "urls": final_urls,
        "probe": "filtered" if probe_enabled else "skipped",
        "epg": epg_status,
        "sources": source_health,
    }
    with open(os.path.join(args.out, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"[完成] 频道 {final_channels} / 接口 {final_urls} / EPG {epg_status}", flush=True)
    if final_channels == 0:
        print("[警告] 无可用频道，请检查网络或源配置", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
