#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陕西网络广播电视台（SNRTV）官方直播流解析。
官方直播页流地址每日动态变化：从 toutiao.cnwest.com/static/v1/stream.js
提取 AES-128-CBC 加密的 sTV 变量并解密，得到各频道实时 m3u8 地址。
"""
import base64
import json
import re

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

STREAM_JS = "http://toutiao.cnwest.com/static/v1/stream.js"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 内部频道 ID -> 规范频道名（2025 年频道调整后的现行名称）
NAME_MAP = {
    "1": "陕西新闻资讯",
    "2": "陕西都市青春",
    "3": "陕西银龄",
    "4": "陕西西部电影",
    "5": "陕西秦腔",
    "7": "陕西体育休闲",
    "11": "陕西移动电视",
}


def fetch_snrtv():
    """返回 [{"name": 频道名, "url": m3u8地址}, ...]"""
    t = requests.get(STREAM_JS, headers=UA, timeout=25).text
    s_tv = re.search(r'sTV="(.*?)";', t).group(1)
    s_radio = re.search(r'sRadio="(.*?)";', t).group(1)
    key = s_tv[:16].encode()
    iv = s_radio[:16].encode()
    ct = base64.b64decode(s_tv[16:])
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = (dec.update(ct) + dec.finalize()).rstrip(b"\x00")
    data = pt.split(b"}}")[0] + b"}}"
    j = json.loads(data)
    entries = []
    for k, v in j.items():
        if not isinstance(v, dict):
            continue
        url = (v.get("m3u8") or "").strip()
        if not url:
            continue
        name = NAME_MAP.get(k) or v.get("name") or k
        entries.append({"name": name, "url": url})
    return entries


if __name__ == "__main__":
    for e in fetch_snrtv():
        print(e["name"], e["url"])
