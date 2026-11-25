# SparkTV 默认嵌入直播源订阅地址清单

- 整理日期：2026-11-25
- 适用版本：SparkTV v2.6.0（versionCode 20）
- 数据来源：`SparkTV/app/src/main/java/com/spark/tv/data/ChannelRepository.kt`
- 说明：以下均为社区公开维护的 M3U/M3U8 清单；App 不内置任何账号密码、登录墙或付费源。

## 一、在线更新默认订阅源（DEFAULT_SOURCES，9 个）

用于设置页「更新直播源」时并发拉取，持续刷新频道库。

| 序号 | 名称 | 地址 |
|---|---|---|
| 1 | 央视·卫视·地方（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_all_status.m3u8 |
| 2 | 卫视频道（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_province_status.m3u8 |
| 3 | 央视频道（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_cctv_status.m3u8 |
| 4 | 综合源 · YanG | https://raw.githubusercontent.com/yanG-1989/m3u/main/Gather.m3u |
| 5 | 综合源 · suxuang | https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u |
| 6 | 综合源 · vbskycn | https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u |
| 7 | iptv-org 中国大陆 | https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u |
| 8 | iptv-org 中国分类 | https://iptv-org.github.io/iptv/countries/cn.m3u |
| 9 | 综合源 · ssili126 | https://raw.githubusercontent.com/ssili126/tv/main/itvlist.m3u |

## 二、实时抓取源（OFFICIAL_SOURCES，6 个）

用于后台按可调间隔抓取，抓到的线路打「实」标记并归类进各频道源列表。

| 序号 | 名称 | 地址 |
|---|---|---|
| 1 | 央视·卫视·各省（iptv-api 存活校验） | https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u |
| 2 | 央视·卫视·港澳台（bestK 合集） | https://raw.githubusercontent.com/bestK/iptv/main/iptv.m3u |
| 3 | 央视频道（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_cctv_status.m3u8 |
| 4 | 卫视频道（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_province_status.m3u8 |
| 5 | 全国地方频道（每日存活校验） | https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_all_status.m3u8 |
| 6 | iptv-org 中国频道 | https://iptv-org.github.io/iptv/countries/cn.m3u |

## 三、去重后的纯地址列表（11 个，可直接复制）

```text
https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_all_status.m3u8
https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_province_status.m3u8
https://raw.githubusercontent.com/best-fan/iptv-sources/master/cn_cctv_status.m3u8
https://raw.githubusercontent.com/yanG-1989/m3u/main/Gather.m3u
https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u
https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u
https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u
https://iptv-org.github.io/iptv/countries/cn.m3u
https://raw.githubusercontent.com/ssili126/tv/main/itvlist.m3u
https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u
https://raw.githubusercontent.com/bestK/iptv/main/iptv.m3u
```

> 两组清单有 4 个重复地址（best-fan 三条 + iptv-org 中国分类），合并去重后为 11 个唯一地址。上方代码块按出现顺序去重列出，共 11 条。

## 四、用户自填项（默认空，App 不预置）

| 配置项 | SharedPreferences 键 | 默认值 | 位置 |
|---|---|---|---|
| 订阅源地址 | `sub_url` | 空 | 设置页「订阅源地址」输入框 |
| 订阅账号 | `sub_user` | 空 | 设置页 |
| 订阅密码 | `sub_pass` | 空 | 设置页，仅存本机 |
| 自建 M3U 托管前缀 | `m3u_base` | 空 | 设置页，导出 `<前缀>/live.m3u8` |
| 粘贴订阅内容 | `local_m3u` | 空 | 设置页 |

离线频道库：`assets/channels.json`，随安装包发布，不依赖订阅地址。

## 五、备注

- 上述地址为公开社区清单， availability 取决于维护者，可能随时失效。
- 官方电视台网页（央视网、芒果TV、各卫视官网）的流多已 CDRM 加扰或需鉴权，App 仅将其作为频道身份/归类参考，不作为流来源。
- 修改内置地址需改 `ChannelRepository.kt` 并重新构建 APK；用户自有订阅地址可在设置页直接填写，无需改代码。
