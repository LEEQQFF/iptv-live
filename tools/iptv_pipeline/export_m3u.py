#!/usr/bin/env python3
"""从人工维护的 channels.json 生成标准 M3U 订阅文件。

输出：
- iptv-live.m3u          主订阅：仅存活线路，每组每频道最多 5 条，官方源已置顶
- iptv-live-all.m3u       全量备用：含失效线路，便于人工排查
- output/manual-live.m3u GitHub Pages 版（内容同主订阅）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "channels.json"
EPG_URL = "https://leeqqff.github.io/iptv-live/e.xml"
MAX_PER_CHANNEL = 5


def attr(value: object) -> str:
    """Escape an M3U attribute value."""
    return str(value or "").replace('"', "").replace(",", "，").replace("\n", " ").strip()


def build(only_alive: bool, limit: int) -> tuple[str, int, int]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S+08:00")
    mode = "存活线路版" if only_alive else "全量备用版"
    lines = [
        f'#EXTM3U x-tvg-url="{EPG_URL}" url-tvg="{EPG_URL}"',
        f"# 订阅名称：iptv-live 人工维护频道库（{mode}）",
        f"# 数据来源：channels.json（updated={data.get('updated')}）",
        f"# 生成时间：{now}",
        "# 排序：官方源 → 存活 → 延迟升序；央视按 CCTV-1~17，省级按行政区，非行政区归网络",
        f"# 过滤：{'仅 status=alive' if only_alive else '含失效线路，仅供排查'}；每频道最多 {limit or '不限'} 条",
        "",
    ]
    channels = streams = 0
    for group in data["groups"]:
        lines.append(f"# ===== {group['name']} =====")
        for channel in group["channels"]:
            candidates = list(channel.get("streams") or [])
            if only_alive:
                candidates = [s for s in candidates if s.get("status") == "alive"]
            if limit:
                candidates = candidates[:limit]
            if not candidates:
                continue
            channels += 1
            name = attr(channel.get("name"))
            tid = attr(channel.get("id"))
            tname = attr(channel.get("name", "").split()[0] if channel.get("name") else "")
            logo = channel.get("logo") or ""
            gtitle = attr(group["name"])
            for stream in candidates:
                url = str(stream.get("url") or "").strip()
                if not url:
                    continue
                logo_attr = f' tvg-logo="{attr(logo)}"' if logo else ""
                lines.append(
                    f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{tname}"{logo_attr}'
                    f' group-title="{gtitle}",{name}'
                )
                lines.append(url)
                streams += 1
        lines.append("")
    return "\n".join(lines) + "\n", channels, streams


def main() -> None:
    primary, channels, streams = build(True, MAX_PER_CHANNEL)
    (ROOT / "iptv-live.m3u").write_text(primary, encoding="utf-8")
    pages = ROOT / "output"
    pages.mkdir(exist_ok=True)
    (pages / "manual-live.m3u").write_text(primary, encoding="utf-8")

    full, full_channels, full_streams = build(False, 0)
    (ROOT / "iptv-live-all.m3u").write_text(full, encoding="utf-8")

    print(
        json.dumps(
            {
                "primary": {"channels": channels, "streams": streams, "bytes": len(primary.encode())},
                "full": {"channels": full_channels, "streams": full_streams, "bytes": len(full.encode())},
                "files": ["iptv-live.m3u", "iptv-live-all.m3u", "output/manual-live.m3u"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
