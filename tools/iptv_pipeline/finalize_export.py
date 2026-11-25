#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize the channel library and export Excel / Markdown / CSV deliverables."""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"
TODAY = "2026-11-25"
OFFICIAL_HOSTS = ("cctv.com", "cntv.cn", "bestv.cn")


def official_stream(stream: dict) -> bool:
    if stream.get("official"):
        return True
    u = stream.get("url", "").lower()
    return any(host in u for host in OFFICIAL_HOSTS)


def main():
    merged = json.loads((CACHE / "merged.json").read_text(encoding="utf-8"))
    live = json.loads((CACHE / "liveness.json").read_text(encoding="utf-8"))
    results = live["results"]

    groups = []
    for g in merged["groups"]:
        chans = []
        for ch in g["channels"]:
            for s in ch["streams"]:
                r = results.get(s["url"].strip(), {})
                s["status"] = r.get("status", "unknown")
                s["code"] = r.get("code", 0)
                s["ms"] = r.get("ms", 9999) if s["status"] == "alive" else 9999
                s["reason"] = r.get("reason", "unchecked")
                s["official"] = official_stream(s)
                s.pop("ua", None)
                s.pop("ok", None)
            ch["streams"].sort(key=lambda s: (0 if s["official"] else 1, 0 if s["status"] == "alive" else 1, s["ms"]))
            ch["alive"] = sum(1 for s in ch["streams"] if s["status"] == "alive")
            ch["dead"] = sum(1 for s in ch["streams"] if s["status"] == "dead")
            ch["official"] = sum(1 for s in ch["streams"] if s["official"])
            ch["best"] = next((s["url"] for s in ch["streams"] if s["status"] == "alive"), "")
            ch.pop("_origin", None)
            chans.append(ch)
        groups.append({"name": g["name"], "channels": chans})

    all_streams = [(g["name"], ch, s) for g in groups for ch in g["channels"] for s in ch["streams"]]
    status = Counter(s["status"] for _, _, s in all_streams)
    official_n = sum(1 for _, _, s in all_streams if s["official"])
    final = {
        "schema": 3,
        "updated": TODAY,
        "source": "channels.raw.json + SparkTV 默认订阅地址清单（11 个公开 M3U/M3U8）",
        "grouping": ["央视", "卫视", "地方", "港澳台", "其他"],
        "ordering": "官方源 > 检活存活 > 响应延迟升序",
        "liveness": {
            "checkedAt": live["checkedAt"],
            "method": "逐条真实 HTTP GET，2xx/3xx 且返回 M3U/TS 媒体字节判定存活；其余判定失效",
            "alive": status["alive"],
            "dead": status["dead"],
            "unknown": status["unknown"],
        },
        "stats": {
            "channels": sum(len(g["channels"]) for g in groups),
            "streams": len(all_streams),
            "official_streams": official_n,
            "unique_urls": len({s["url"] for _, _, s in all_streams}),
            **merged["stats"],
        },
        "groups": groups,
    }
    (ROOT / "channels.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")

    # Subscription address table.
    md = (ROOT / "subscription-sources.md").read_text(encoding="utf-8")
    subs = []
    for m in re.finditer(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*(https?://\S+?)\s*\|$", md, re.M):
        subs.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    seen = set()
    subs = [(i, n, u) for i, n, u in subs if not (u in seen or seen.add(u))]

    # Excel.
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    gold = PatternFill("solid", fgColor="FFF2CC")
    green = PatternFill("solid", fgColor="E2EFDA")
    red = PatternFill("solid", fgColor="FCE4E4")
    head_font = Font(color="FFFFFF", bold=True)

    def sheet(title, headers, rows, widths=None, freeze="A2"):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.fill = head_fill
            c.font = head_font
            c.alignment = Alignment(vertical="center")
        for row in rows:
            ws.append(row)
        ws.freeze_panes = freeze
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, ws.max_row)}"
        for i, w in enumerate(widths or [20] * len(headers), 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    sheet("使用说明", ["项目", "说明"], [
        ["数据时间", f"{TODAY} {live['checkedAt']}"],
        ["文件关系", "channels.json 为权威数据；Excel/CSV/Markdown 均为其可编辑视图"],
        ["人工修改", "Excel 中直接改单元格；改完如需回写 JSON，请按 columns 顺序同步修改 channels.json"],
        ["拖拽排序", "Excel 中选整行后拖动行号即可调整顺序；重新运行导出脚本会按官方源>存活>延迟重排"],
        ["检活口径", final["liveness"]["method"]],
        ["置顶规则", final["ordering"]],
        ["URL 来源", "11 个公开订阅地址，见「订阅地址」sheet"],
        ["免责声明", "公开社区源，可用性随维护者变化；不含账号密码、付费墙或绕过鉴权内容"],
    ], [18, 100])

    summary_rows = []
    for g in groups:
        ss = [s for gname, _, s in all_streams if gname == g["name"]]
        summary_rows.append([
            g["name"], len(g["channels"]), len(ss),
            sum(1 for s in ss if s["status"] == "alive"),
            sum(1 for s in ss if s["status"] == "dead"),
            sum(1 for s in ss if s["official"]),
            sum(1 for c in g["channels"] if c["alive"] > 0),
        ])
    summary_rows.append(["合计", final["stats"]["channels"], len(all_streams), status["alive"], status["dead"], official_n,
                         sum(1 for g in groups for c in g["channels"] if c["alive"] > 0)])
    sheet("汇总", ["分组", "频道数", "线路数", "存活线路", "失效线路", "官方源", "有存活线路的频道数"], summary_rows,
          [14, 12, 12, 12, 12, 12, 22])

    stream_headers = ["频道", "分组", "省份", "城市", "序号", "检活", "HTTP", "延迟ms", "官方", "来源", "画质", "标识", "URL"]
    stream_widths = [22, 10, 10, 10, 8, 10, 9, 10, 8, 30, 10, 24, 90]

    def stream_rows(gname):
        rows = []
        for gname_, ch, s in all_streams:
            if gname_ != gname:
                continue
            rows.append([ch["name"], gname_, ch.get("province", ""), ch.get("city", ""), len(rows) + 1,
                         "存活" if s["status"] == "alive" else "失效", s.get("code", 0), s.get("ms", 9999),
                         "是" if s["official"] else "", s.get("src", ""), s.get("quality", ""), s.get("label", ""), s["url"]])
        return rows

    for gname in ["央视", "卫视", "地方", "港澳台", "其他"]:
        rows = stream_rows(gname)
        ws = sheet(gname, stream_headers, rows, stream_widths)
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 9).value == "是":
                ws.cell(r, 9).fill = gold
            ws.cell(r, 6).fill = green if ws.cell(r, 6).value == "存活" else red

    channel_rows = []
    for g in groups:
        for ch in g["channels"]:
            channel_rows.append([ch["name"], g["name"], ch.get("province", ""), ch.get("city", ""),
                                 len(ch["streams"]), ch["alive"], ch["dead"], ch["official"], ch["best"]])
    ws = sheet("频道总表", ["频道名(可改)", "分组", "省份", "城市", "线路数", "存活", "失效", "官方源", "首选URL"], channel_rows,
               [26, 10, 10, 10, 10, 9, 9, 10, 90])

    official_rows = [[g, ch["name"], s["src"], s["quality"], s["label"], s["url"]]
                     for g, ch, s in all_streams if s["official"]]
    sheet("官方源置顶", ["分组", "频道", "来源", "画质", "标识", "URL"], official_rows, [10, 24, 30, 10, 26, 90])

    dead_rows = [[g, ch["name"], s.get("reason", ""), s.get("code", 0), s.get("src", ""), s["url"]]
                 for g, ch, s in all_streams if s["status"] != "alive"]
    sheet("失效源", ["分组", "频道", "原因", "HTTP", "来源", "URL"], dead_rows, [10, 24, 18, 9, 30, 90])

    sheet("订阅地址", ["序号", "名称", "地址", "抓取状态"], [[i, n, u, "成功"] for i, n, u in subs], [8, 42, 96, 12])

    wb.save(ROOT / "iptv-live-汇总.xlsx")

    # Editable CSV views (UTF-8 BOM for Excel double-click).
    edit_dir = ROOT / "editable"
    edit_dir.mkdir(exist_ok=True)
    for gname in ["央视", "卫视", "地方"]:
        with (edit_dir / f"{gname}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(stream_headers)
            w.writerows(stream_rows(gname))

    # Markdown list.
    lines = [
        "# iptv-live 直播源清单",
        "",
        f"- 数据时间：{TODAY} {live['checkedAt']}",
        f"- 频道 {final['stats']['channels']} 个 / 线路 {len(all_streams)} 条 / 唯一 URL {final['stats']['unique_urls']} 条",
        f"- 严格检活：存活 {status['alive']} / 失效 {status['dead']}",
        f"- 排序：{final['ordering']}（⭐=官方源，✅=检活存活，❌=失效）",
        "- 清单为纯文本，可直接修改；同内容的 Excel/CSV 见 iptv-live-汇总.xlsx 与 editable/。",
        "",
    ]
    for g in groups:
        if g["name"] in ("港澳台", "其他"):
            continue
        lines += [f"## {g['name']}（{len(g['channels'])} 频道）", ""]
        for ch in g["channels"]:
            lines.append(f"### {ch['name']}")
            lines.append("")
            for s in ch["streams"]:
                mark = "⭐" if s["official"] else ("✅" if s["status"] == "alive" else "❌")
                lines.append(f"- {mark} [{s.get('quality','未知')} / {s.get('ms',9999)}ms / {s.get('src','')}] {s['url']}")
            lines.append("")
    (ROOT / "iptv-live-频道清单.md").write_text("\n".join(lines), encoding="utf-8")

    # README.
    readme = f"""# iptv-live

聚合 → 去重 → 央视/卫视/地方归类 → 严格检活 → 官方源置顶 的可编辑直播源库。

## 数据
- 更新：{TODAY}（检活 {live['checkedAt']}）
- 频道 {final['stats']['channels']} / 线路 {len(all_streams)} / 唯一 URL {final['stats']['unique_urls']}
- 检活：存活 {status['alive']} / 失效 {status['dead']}；官方源 {official_n} 条
- 订阅源：{len(subs)} 个唯一地址（来自 SparkTV 默认订阅地址清单，见 `subscription-sources.md`）

## 文件
| 文件 | 用途 |
|---|---|
| `channels.json` | 权威数据源（含每条线路的检活状态与排序） |
| `iptv-live-汇总.xlsx` | 多 sheet 可编辑视图：汇总/央视/卫视/地方/港澳台/其他/频道总表/官方源置顶/失效源/订阅地址 |
| `editable/*.csv` | 央视/卫视/地方 的纯文本表格，可直接改字或拖拽排序 |
| `iptv-live-频道清单.md` | Markdown 文字清单，可直接编辑 |
| `tools/` | 复现脚本：parse_merge.py / check_liveness.py / finalize_export.py |

## 口径
1. 聚合：`channels.raw.json` + 11 个公开 M3U/M3U8 订阅地址（{merged['stats']['subscription_rows']} 行，跳过 {merged['stats'].get('subscription_skipped_rows',0)} 行非直播/VOD）。
2. 去重：同一频道内按完整 URL 去重；全局唯一 URL {final['stats']['unique_urls']} 条。
3. 归类：央视 / 卫视 / 地方（主），港澳台 / 其他（附）。
4. 严格检活：逐条真实 HTTP GET，仅 2xx/3xx 且返回 M3U/TS 媒体字节判为存活。
5. 置顶：官方源（央视网/CNTV/北京卫视 BESTV 域名或原库标记）→ 存活 → 延迟升序。

## 人工修改
- Excel：直接改单元格；整行选中拖动可调整顺序。
- CSV/Markdown：任意文本编辑器修改。
- 改完若需让 App 或脚本使用，请同步修改 `channels.json` 中对应字段。

## 合规
仅收录公开社区维护的 M3U/M3U8 地址；不含账号密码、登录墙、付费源或鉴权绕过内容。可用性取决于源维护者。
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps({
        "channels": final["stats"]["channels"], "streams": len(all_streams),
        "unique_urls": final["stats"]["unique_urls"], "alive": status["alive"],
        "dead": status["dead"], "official": official_n, "subs": len(subs),
        "groups": {g["name"]: len(g["channels"]) for g in groups},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
