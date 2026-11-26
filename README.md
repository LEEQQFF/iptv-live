# IPTV 直播源自动维护（GitHub Actions + Pages）

自动抓取央视 / 卫视 / 各省市地方台的公开直播源，聚合多个社区长期维护项目，
经 **归一化 → 分类 → 去重 → 测活 → 编排** 后生成干净的 m3u 直播清单与 XMLTV 格式 EPG 节目单，
每小时滚动更新一次，并通过 GitHub Pages 输出**公网订阅地址**，全程免费、无需服务器。

## 一、产出文件

| 文件 | 说明 |
| --- | --- |
| `output/live.m3u` | 主订阅清单（含台标、tvg-id、分组），播放器直接订阅 |
| `output/live.txt` | TVBox / 影视壳用 TXT 格式（`分类,#genre#`） |
| `output/e.xml` | XMLTV 节目单（保留未来 3 天，按清单频道过滤） |
| `output/status.json` | 每次更新的时间、频道数、各源健康状态 |

分组规则：`央视频道`（CCTV / CGTN / CETV）→ `卫视频道`（38 个上星频道）→ `地方·<省>`（按省归类）。
同一频道多接口按「官方 CDN 域名优先 + 测活延迟」排序，最多保留 5 条；失效接口自动剔除。

## 二、部署步骤（约 5 分钟）

1. **创建仓库**：登录 GitHub → New repository，名称如 `iptv-live`（Public），创建后把本目录全部文件上传（可直接拖拽，注意保留 `.github/workflows/update.yml` 的目录结构）。
2. **开启工作流写权限**：仓库 `Settings → Actions → General → Workflow permissions`，选 **Read and write permissions**，保存。
3. **开启 Pages**：仓库 `Settings → Pages → Build and deployment → Source`，选 **GitHub Actions**。
4. **首次运行**：仓库 `Actions` 页 → 左侧「更新直播源与EPG」→ `Run workflow`。约 5–15 分钟跑完。
5. **获取订阅地址**（把 `<用户名>` 和 `<仓库名>` 换成你的）：

   ```
   直播清单：https://<用户名>.github.io/<仓库名>/live.m3u
   节目单：  https://<用户名>.github.io/<仓库名>/e.xml
   TXT格式： https://<用户名>.github.io/<仓库名>/live.txt
   ```

   备用（Raw 地址，部分播放器更兼容）：
   `https://raw.githubusercontent.com/<用户名>/<仓库名>/main/output/live.m3u`

6. **播放器使用**：TiviMate / TVBox / Kodi / VLC / mytv 等，添加上面的 m3u 地址为订阅，EPG 填 `e.xml` 地址（m3u 头部已内置相对 EPG 指向，多数播放器会自动识别）。

此后每小时自动更新，无需任何人工干预。仓库 60 天无活动会自动暂停定时任务，届时到 Actions 页点一下恢复即可（有提交更新时不会触发）。

## 三、国内访问提示

- `github.io` / `raw.githubusercontent.com` 在部分网络下不稳定，可在订阅地址前加 GitHub 加速前缀（如 `https://ghgo.xyz/` 等公共镜像，时效性自行验证）。
- 清单内的直播流本身多为国内 CDN，播放不受 GitHub 访问影响；只有「拉取订阅」这一步依赖 GitHub 连通性。

## 四、自定义配置（config/sources.yaml）

- `sources`：增删聚合源，每个源可配多个镜像 URL，按序回退。
- `settings.max_urls_per_channel`：每频道保留接口数。
- `settings.include_other`：设为 `true` 可保留港澳台 / 海外中文等未归类频道。
- `settings.exclude_keywords`：频道名黑名单。
- `settings.official_domains`：官方 CDN 域名白名单（排序优先）。
- `settings.epg.urls`：EPG 镜像列表；`keep_days` 节目单天数。
- `official-fixed` 源：手动追加已验证长期稳定的官方固定 HLS 直链。

**关于官方网页直抓的说明**：央视（tv.cctv.com / 央视频）及多数卫视官网直播页的流地址带动态鉴权 token，分钟级失效，无法作为长期订阅源直抓。本方案的策略是：聚合持续跟踪这些官方流的社区维护项目（vbskycn、fanmingming、iptv-org、Guovin/iptv-api 等），并对官方 CDN 域名的接口优先编排；同时预留 `official-fixed` 配置位收录稳定的官方固定流（如部分省台官网 HLS）。

## 五、本地运行（可选）

```bash
pip install -r requirements.txt
python scripts/main.py --config config/sources.yaml --out output
# 网络受限环境可跳过测活：
python scripts/main.py --no-probe
```

## 六、免责声明

本项目仅聚合互联网上公开可访问的直播流地址，不存储、不转播任何音视频内容。
部分社区源可能未经版权方授权，请在当地法律允许的范围内个人使用，勿用于商业传播；
如有版权问题请联系删除。直播源可用性受上游与网络环境影响，不做稳定性保证。

## 七、人工可编辑频道库（2026-11-25 新增）

本轮按「聚合 → 去重 → 归类 → 严格检活 → 官方源置顶」生成了一套可直接人工修改的频道库。基线为附件 `SparkTV/app/src/main/assets/channels.json`（2026-11-17，473 频道 / 1402 线路）+ `SparkTV-默认订阅地址清单.md`（11 个订阅地址）。

**分组规则**：央视按 CCTV1~CCTV17 序号排序；CHC 系列、CETV / CGTN / 央视付费频道归入「央视系列」；卫视独立；其余按全国 34 个省级行政区归类（香港/澳门/台湾单列），不属于任何省级行政区的（影视点播、游戏竞技、境外/网络频道等）归入「网络」。

| 文件 | 说明 |
| --- | --- |
| `channels.json` | 权威数据：1690 频道 / 4371 条线路 / 3950 条唯一 URL；含每条线路的分组、检活状态与排序 |
| `channels.raw.json` | 本轮基线原始频道库（附件 assets 版），供复现脚本读取 |
| `iptv-live-汇总.xlsx` | 44 个 sheet：央视/央视系列/卫视/34 省/网络各有独立 sheet，另有汇总、频道总表、官方源置顶、失效源、订阅地址、使用说明；可改单元格、可整行拖拽 |
| `iptv-live-频道清单.md` | Markdown 文字清单，⭐官方源 / ✅存活 / ❌失效 |
| `editable/*.csv` | 38 个分组各一个纯文本表格，可直接改字或拖拽排序 |
| `SparkTV-默认订阅地址清单.md` | 本轮使用的 11 个唯一订阅地址及来源说明 |
| `README-直播源清单.md` | 该频道库的独立说明 |
| `tools/iptv_pipeline/` | 复现脚本：parse_merge.py / regroup.py / check_liveness.py / finalize_export.py（行政区映射数据见 `tools/cache/`） |

严格检活口径：逐条真实 HTTP GET，仅 2xx/3xx 且返回 M3U/TS 媒体字节判定存活；本轮线路存活 1333 / 失效 3038，官方源 12 条置顶。排序为官方源 → 存活 → 延迟升序。上述文件由人工维护，不会被 `output/` 下的自动更新流程覆盖；若手工修改后需生效，请同步修改 `channels.json`。

### 更新后的订阅地址（2026-11-26）

本轮人工维护频道库对应的订阅地址如下，复制到 TiviMate / TVBox / VLC / mytv 的「订阅地址」即可：

| 用途 | 订阅地址 |
| --- | --- |
| **主订阅（推荐·CDN 通道）**：仅存活线路，每频道最多 5 条、规范短名称 | `https://fastly.jsdelivr.net/gh/LEEQQFF/iptv-live@main/iptv-live.m3u` |
| 主订阅（Pages 通道） | `https://leeqqff.github.io/iptv-live/manual-live.m3u` |
| 主订阅（raw 备用） | `https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/iptv-live.m3u` |
| 全量备用（含失效，CDN） | `https://fastly.jsdelivr.net/gh/LEEQQFF/iptv-live@main/iptv-live-all.m3u` |
| EPG 节目单 | `https://leeqqff.github.io/iptv-live/e.xml`（备用 `https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/output/e.xml`） |
| **图形化管理台** | `https://leeqqff.github.io/iptv-live/web/` |

> CDN（jsdelivr）通道在国内外均可达，优先使用；raw 通道在部分网络下 TLS 握手失败。CDN 有约 10 分钟缓存，若刚更新未生效可在地址后加 `?t=时间戳`。频道名称已统一规范化（英文/拼音翻译为中文、繁简统一、画质/地区/时长噪声清理）。

### 统一全链条（scripts/pipeline.py）

所有源统一在 `config/sources.yaml` 登记，共 **28 个**：原有 16 个源 + `SparkTV-默认订阅地址清单.md` 的 11 个地址 + `channels.json` 内置频道库。`scripts/pipeline.py` 一次跑完全链条：

1. **抓取**：并发拉取全部源，M3U/TXT/官方动态(ysp/snrtv)/固定流/内置库；失败源回退本地缓存，订阅不中断。
2. **名称规范化**（`scripts/names.py`）：把上游千差万别的名称翻译/修正为国内规范频道名——英文/拼音（AnhuiTV、BingtuanSatelliteTV、Tonghua TV）译为中文，繁简统一，画质/地区/时长/来源噪声（`(1080p)`、`[Not24/7]`、`[Geo-blocked]`、`[1080][S]`）清理，CCTV/CHC/CGTN/CETV 系列规范名收敛；无效名称直接剔除。同一频道跨源 converge 到同一规范名。
3. **聚合**：统一条目格式，每条线路记录来源源名称。
4. **去重**：按 URL（忽略动态 token）全局去重，同一线路多源贡献合并来源列表。
5. **归类**：央视（CCTV1-17 序号）、央视系列（CHC/CGTN/CETV 等）、卫视、34 个省级行政区、网络（非行政区）。
6. **严格检活**：真实 HTTP GET，仅 2xx/3xx 且返回 M3U/TS 媒体字节判存活；3 小时内存活线路不重复测，只补测新增/到期。
7. **官方源置顶**：官方域名/白名单 → 存活 → 延迟升序。M3U 的 `tvg-name` 用规范短名、超长 `tvg-logo` 省略，避免名称过长导致部分播放器解析失败。

### 自动维护（24 小时，每 10 分钟滚动）

- `.github/workflows/refresh.yml`：每 10 分钟执行 `scripts/pipeline.py`，刷新 `channels.json`、M3U 订阅、CSV 与管理台 `web/data.json`，并部署 Pages。
- `.github/workflows/update.yml`：每小时更新官方动态流与 EPG；使用独立并发组 `iptv-epg`，不再与 refresh 相互排队阻塞。
- 可在 Actions 页手动触发 `10分钟滚动维护直播源与管理台` 立即刷新。

### 图形化管理台

打开 `https://leeqqff.github.io/iptv-live/web/`（也可直接用浏览器打开仓库内 `web/index.html`），六个视图：
1. **公网订阅地址**：CDN/Pages/raw/EPG 共 6 个地址，均带「复制」「打开」按钮；复制在 HTTPS、HTTP、file:// 下均可用（自动回退 `execCommand`）。
2. **订阅地址清单**：28 个源的地址、状态、条目数。
3. **直播源清单**：按频道/来源/状态/延迟查看每条线路，支持搜索、状态筛选。
4. **来源关系**：各订阅源贡献的线路占比与多源交叉验证线路。
5. **归类与分组**：38 个分组的频道与线路分布。
6. **检活结果**：总体、按分组、按来源的存活率。

拖拽频道行到左侧分组即可调整归类；点击「导出归类 JSON」下载后上传覆盖 `channels.json`，下一次刷新即按新归类生成订阅。

数据通过 `web/data.js`（全局变量）内嵌加载，因此即使用其他浏览器以 `file://` 直接打开网页也能显示数据；通过 http(s)（Pages）访问时另会用 `fetch` 每 5 分钟拉取最新 `data.json` 实现实时刷新。

### 为什么此前的地址订阅不到本次更新

1. `SparkTV-默认订阅地址清单.md` 里的 11 个地址是**上游来源**，不是本仓库产出的订阅结果；现已作为源并入 `config/sources.yaml`。
2. `output/live.m3u` 由旧流水线每小时生成，与本轮人工分组的 `channels.json` 无关；现已统一到 `scripts/pipeline.py`。
3. `raw.githubusercontent.com` 在部分国内网络下 TLS 握手失败，改用 Pages 地址或公共加速前缀。
