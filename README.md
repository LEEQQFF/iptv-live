# IPTV 直播源自动维护（GitHub Actions + Pages）

自动抓取央视 / 卫视 / 各省市地方台的公开直播源，聚合多个社区长期维护项目，
经 **名称规范化 → 聚合 → 去重 → 归类 → 严格检活 → 官方源置顶** 后生成干净的 m3u 直播清单与 XMLTV 格式 EPG 节目单，
每 10 分钟滚动更新一次，并通过 GitHub Pages 输出**极简短的公网订阅地址**，全程免费、无需服务器。

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

### 公网订阅地址（已压缩到极简短链）

| 用途 | 订阅地址 | 长度 |
| --- | --- | --- |
| **极简短链（推荐）** | `https://leeqqff.github.io/iptv-live/l` | 40 字符 |
| **规范订阅（.m3u，兼容性最好）** | `https://leeqqff.github.io/iptv-live/l.m3u` | 42 字符 |
| 全量订阅（含失效线路，排查用） | `https://leeqqff.github.io/iptv-live/a.m3u` | 42 字符 |
| EPG 节目单 | `https://leeqqff.github.io/iptv-live/e.xml` | 42 字符 |
| **图形化管理台** | `https://leeqqff.github.io/iptv-live/` | 41 字符 |
| 较长备用（raw / CDN） | `https://raw.githubusercontent.com/LEEQQFF/iptv-live/main/iptv-live.m3u` 等 | 网页“展开备用地址”中查看 |

> 主订阅仅含严格检活存活线路（每频道≤5条、规范短名称）。短链无扩展名，兼容 SparkTV / VLC / PotPlayer；若播放器强制要求 `.m3u`，请用规范订阅地址。频道名称已统一规范化（英文/拼音翻译为中文、繁简统一、画质/地区/时长噪声清理），M3U 的 `tvg-name` 使用短名，避免名称过长导致解析失败。

### 统一全链条（scripts/pipeline.py）

基础源在 `config/sources.yaml` 登记（28 个：原有 16 个 + SparkTV 11 个 + 内置 `channels.json`），
自动发现源在 `config/auto_sources.json`，网页人工维护在 `config/manual_overrides.json`，三者统一进入流水线：

1. **抓取**：并发拉取全部源，M3U/TXT/官方动态(ysp/snrtv)/固定流/内置库；失败源回退本地缓存，订阅不中断。
2. **名称规范化**（`scripts/names.py`）：把上游千差万别的名称翻译/修正为国内规范频道名——英文/拼音译为中文，繁简统一，画质/地区/时长/来源噪声清理，CCTV/CHC/CGTN/CETV 系列规范名收敛；无效名称直接剔除。
3. **聚合**：统一条目格式，每条线路记录来源源名称及上游原始名（`name_source`）。
4. **去重**：按 URL（忽略动态 token）全局去重，同一线路多源贡献合并来源列表。
5. **人工维护优先**：网页改过的名称/分组/新增源在归类前套用，改名后自动重新归类；`channel.name` 为维护名，`channel.name_source` 保留源名。
6. **归类**：央视（CCTV1-17 序号）、央视系列（CHC/CGTN/CETV 等）、卫视、34 个省级行政区、网络（非行政区），支持网页自定义分组。
7. **严格检活**：真实 HTTP GET，仅 2xx/3xx 且返回 M3U/TS 媒体字节判存活；3 小时内存活线路不重复测，只补测新增/到期。
8. **官方源置顶**：官方域名/白名单 → 存活 → 延迟升序。M3U 的 `tvg-name` 用规范短名、超长 `tvg-logo` 省略。

### 订阅地址自动发现 / 监测修正（`scripts/discover.py`）

- 从现有源、GitHub 公开仓库搜索、公开网页中收集候选 m3u/m3u8/txt 地址。
- 解析订阅地址的**更高层级仓库**（owner/repo），读取 README 与仓库树，寻找同仓库内更正确、更多的订阅文件；失效源自动尝试替代路径。
- 候选地址必须真实抓取并解析出至少 3 条直播线路才启用，最多启用 30 个，防止低质量源拖慢滚动。
- 结果写入 `config/auto_sources.json`，网页“订阅地址清单”显示巡检时间、候选/有效/启用/修正数量。

### 自动维护（24 小时，每 10 分钟滚动）

- `.github/workflows/refresh.yml`：每 10 分钟执行轻量巡检 → `scripts/pipeline.py` → 刷新 `channels.json`、M3U、CSV、管理台数据 → 部署 Pages。
- `.github/workflows/web-edit.yml`：网页提交修改后，自动合并维护配置 → 全量发现（如触发）→ 重跑全链条 → 写回 GitHub → 部署 Pages → Issue 回执。
- `.github/workflows/update.yml`：每小时更新官方动态流与 EPG；使用独立并发组 `iptv-epg`，不与 refresh 相互阻塞。
- 可在 Actions 页手动触发上述 workflow 立即刷新。

### 图形化管理台（需求重整与实现）

管理台地址：`https://leeqqff.github.io/iptv-live/`（等价路径 `/web/`）。按“看得见、改得动、能自动生效、足够快”重新整理需求如下：

| # | 需求 | 实现 |
| --- | --- | --- |
| 1 | 公网订阅地址足够短 | 极简 `.../l`（40 字符），规范 `.../l.m3u`（42 字符）；一键复制在 HTTPS/HTTP/`file://` 均可用 |
| 2 | 订阅地址自动/手动添加并进入全链条 | 手动粘贴订阅地址或单条直播源；自动检索全网并解析上层仓库；写入 `manual_overrides.json` / `auto_sources.json` 后重跑聚合→名称修正→去重→归类→严格检活→官方置顶 |
| 3 | 订阅地址监测与修正 | 解析订阅地址所属 GitHub 仓库 README/仓库树，寻找更正确、更多的订阅文件并校验后启用 |
| 4 | 双列名与 URL 可隐藏 | `频道名称-维护`（规范化后的维护名）、`频道名称-源名`（上游原始名）；URL 默认隐藏，勾选后查阅/逐条复制 |
| 5 | 手动改名后自动归类并发布 | 改名回车后加入待提交队列，提交后自动重跑归类与流水线并更新 GitHub、公网 M3U |
| 6 | 手动分组管理并自动发布 | 新增分组、分组重命名、拖拽频道调整归类，均进入同一待提交队列统一写回 |
| 7 | 24 小时滚动维护 | `refresh.yml` 每 10 分钟触发（GitHub 高峰可能延迟数分钟）；`update.yml` 每小时更新官方流/EPG |

六个视图：①公网订阅地址 ②订阅地址清单 ③直播源清单 ④来源关系 ⑤归类与分组 ⑥检活结果。

**修改如何生效（自动写回）**：页面顶部“GitHub 自动写回”填入自己的 GitHub Token（`public_repo` 或 `repo` 权限，仅存本机浏览器 `localStorage`），点“保存并验证”显示已连接账号后，所有改名、归类、分组、添加源操作先进入“待提交修改”，点「提交到 GitHub 并自动发布」即由 API 直接创建带 `web-edit` 标签的 Issue；`web-edit.yml` 自动合并配置 → 重跑全链条 → 提交 GitHub → 部署 Pages → Issue 回执并关闭，1–3 分钟生效。未配置 Token 时降级为打开预填 Issue 页，需登录 GitHub 手动点 Submit。

**性能处理**：清单按频道分页（默认每页 60 个频道、每频道 1 条最佳线路，可展开全部线路），只渲染当前视图，数据每 10 分钟静默检查版本且在有未提交修改时不打断编辑；不再一次性生成上万行表格，也不再每分钟全量重绘。

数据由 `web/data.js`（全局变量）内嵌加载，其他浏览器以 `file://` 打开也能显示；Pages 下另用 `data.json` 静默检查更新，可点“立即刷新数据”手动更新。

### 为什么此前的地址订阅不到本次更新

1. `SparkTV-默认订阅地址清单.md` 里的 11 个地址是**上游来源**，不是本仓库产出的订阅结果；现已作为源并入 `config/sources.yaml`。
2. `output/live.m3u` 由旧流水线每小时生成，与本轮人工分组的 `channels.json` 无关；现已统一到 `scripts/pipeline.py`。
3. `raw.githubusercontent.com` 在部分国内网络下 TLS 握手失败，改用 Pages 地址或公共加速前缀。
