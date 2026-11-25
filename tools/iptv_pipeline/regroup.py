#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-group the merged library:
- CCTV channels sorted by CCTV1..CCTV17
- province-level administrative groups (34 divisions)
- everything outside a province -> 网络
- CHC / CCTV-affiliated channels -> 央视系列
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"

PROVINCE_ORDER = [
    "北京", "天津", "河北", "山西", "内蒙古",
    "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南",
    "广东", "广西", "海南",
    "重庆", "四川", "贵州", "云南", "西藏",
    "陕西", "甘肃", "青海", "宁夏", "新疆",
    "香港", "澳门", "台湾",
]

# Prefecture-level city -> province (covers the names appearing in public Chinese IPTV lists).
SIMPLIFY = str.maketrans({
    "陽": "阳", "撫": "抚", "縣": "县", "頻": "频", "衛": "卫", "視": "视", "東": "东",
    "購": "购", "綜": "综", "藝": "艺", "紀": "纪", "錄": "录", "國": "国", "際": "际",
    "華": "华", "語": "语", "劇": "剧", "場": "场", "導": "导", "員": "员", "灣": "湾",
    "臺": "台", "時": "时", "體": "体", "聞": "闻", "飛": "飞", "龍": "龙", "鳳": "凤",
    "黃": "黄", "點": "点", "聲": "声", "電": "电", "網": "网", "絡": "络", "線": "线",
    "節": "节", "島": "岛", "亞": "亚", "馬": "马", "麗": "丽", "財": "财", "經": "经",
    "濟": "济", "會": "会", "議": "议", "術": "术", "倉": "仓", "庫": "库", "興": "兴",
    "衛": "卫", "數": "数", "腦": "脑", "視": "视", "覺": "觉", "戰": "战", "劇": "剧",
})


def simplify(s: str) -> str:
    return str(s or "").translate(SIMPLIFY)
CITY_PROVINCE = {}
_CITY_BLOCKS = {
    "河北": "石家庄 唐山 秦皇岛 邯郸 邢台 保定 张家口 承德 沧州 廊坊 衡水 雄安",
    "山西": "太原 大同 阳泉 长治 晋城 朔州 晋中 运城 忻州 临汾 吕梁",
    "内蒙古": "呼和浩特 包头 乌海 赤峰 通辽 鄂尔多斯 呼伦贝尔 巴彦淖尔 乌兰察布 兴安 锡林郭勒 阿拉善 满洲里",
    "辽宁": "沈阳 大连 鞍山 抚顺 本溪 丹东 锦州 营口 阜新 辽阳 盘锦 铁岭 朝阳 葫芦岛",
    "吉林": "长春 吉林市 四平 辽源 通化 白山 松原 白城 延边 延吉 珲春 敦化 龙井 图们 和龙 汪清 安图 蛟河 桦甸 舒兰 磐石",
    "黑龙江": "哈尔滨 齐齐哈尔 鸡西 鹤岗 双鸭山 大庆 伊春 佳木斯 七台河 牡丹江 黑河 绥化 大兴安岭 阿城 双城 尚志 五常 绥芬河",
    "江苏": "南京 无锡 徐州 常州 苏州 南通 连云港 淮安 盐城 扬州 镇江 泰州 宿迁 江阴 宜兴 昆山 常熟 张家港 太仓 吴江",
    "浙江": "杭州 宁波 温州 嘉兴 湖州 绍兴 金华 衢州 舟山 台州 丽水 余姚 慈溪 义乌 诸暨 上虞 余杭 兰溪 乐清 瑞安 温岭 临海",
    "安徽": "合肥 芜湖 蚌埠 淮南 马鞍山 淮北 铜陵 安庆 黄山 滁州 阜阳 宿州 六安 亳州 池州 宣城 天长 宁国 桐城",
    "福建": "福州 厦门 莆田 三明 泉州 漳州 南平 龙岩 宁德 福清 晋江 石狮 南安 永安 邵武 武夷山 漳平 福安 福鼎",
    "江西": "南昌 景德镇 萍乡 九江 新余 鹰潭 赣州 吉安 宜春 抚州 上饶 吉州 井冈山 瑞金 南康 丰城 樟树 高安",
    "山东": "济南 青岛 淄博 枣庄 东营 烟台 潍坊 济宁 泰安 威海 日照 临沂 德州 聊城 滨州 菏泽 胶州 即墨 诸城 寿光 龙口 蓬莱 招远 莱州",
    "河南": "郑州 开封 洛阳 平顶山 安阳 鹤壁 新乡 焦作 濮阳 许昌 漯河 三门峡 南阳 商丘 信阳 周口 驻马店 济源 偃师 巩义 荥阳 新郑 登封 卫辉 辉县 内黄 兰考 叶县 临颍 义马",
    "湖北": "武汉 黄石 十堰 宜昌 襄阳 鄂州 荆门 孝感 荆州 黄冈 咸宁 随州 恩施 仙桃 潜江 天门 神农架 利川 当阳 枝江 宜都 大冶",
    "湖南": "长沙 株洲 湘潭 衡阳 邵阳 岳阳 常德 张家界 益阳 郴州 永州 怀化 娄底 湘西 浏阳 醴陵 湘乡 韶山 耒阳 常宁 津市 汨罗 临湘 武冈",
    "广东": "广州 韶关 深圳 珠海 汕头 佛山 江门 湛江 茂名 肇庆 惠州 梅州 汕尾 河源 阳江 清远 东莞 中山 潮州 揭阳 云浮 顺德 南海 番禺 花都 增城 从化 台山 开平 鹤山 恩平 高要 四会 普宁 陆丰 南雄",
    "广西": "南宁 柳州 桂林 梧州 北海 防城港 钦州 贵港 玉林 百色 贺州 河池 来宾 崇左 凭祥 北流 桂平 岑溪 东兴",
    "海南": "海口 三亚 三沙 儋州 五指山 琼海 文昌 万宁 东方 定安 屯昌 澄迈 临高 白沙 昌江 乐东 陵水 保亭 琼中",
    "重庆": "万州 涪陵 渝中 大渡口 江北 沙坪坝 九龙坡 南岸 北碚 渝北 巴南 黔江 长寿 江津 合川 永川 南川 綦江 大足 璧山 铜梁 潼南 荣昌 开州 梁平 武隆 丰都 垫江 忠县 云阳 奉节 巫山 巫溪 石柱 秀山 酉阳 彭水",
    "四川": "成都 自贡 攀枝花 泸州 德阳 绵阳 广元 遂宁 内江 乐山 南充 眉山 宜宾 广安 达州 雅安 巴中 资阳 阿坝 甘孜 凉山 西昌 叙州 简阳 都江堰 彭州 邛崃 崇州 江油 广汉 什邡 绵竹 阆中 华蓥 万源 峨眉山",
    "贵州": "贵阳 六盘水 遵义 安顺 毕节 铜仁 黔西南 黔东南 黔南 兴义 凯里 都匀 福泉 仁怀 赤水 清镇",
    "云南": "昆明 曲靖 玉溪 保山 昭通 丽江 普洱 临沧 楚雄 红河 文山 西双版纳 大理 德宏 怒江 迪庆 安宁 宣威 个旧 开远 蒙自 弥勒 景洪 瑞丽 芒市 泸西 楚雄州",
    "西藏": "拉萨 日喀则 昌都 林芝 山南 那曲 阿里 江孜 亚东",
    "陕西": "西安 铜川 宝鸡 咸阳 渭南 延安 汉中 榆林 安康 商洛 杨凌 兴平 华阴 韩城 神木",
    "甘肃": "兰州 嘉峪关 金昌 白银 天水 武威 张掖 平凉 酒泉 庆阳 定西 陇南 临夏 甘南 敦煌 华亭 玉门 敦煌市 合作 临夏市",
    "青海": "西宁 海东 海北 黄南 果洛 玉树 海西 格尔木 德令哈 同仁 共和",
    "宁夏": "银川 石嘴山 吴忠 固原 中卫 青铜峡 灵武",
    "新疆": "乌鲁木齐 克拉玛依 吐鲁番 哈密 昌吉 博尔塔拉 巴音郭楞 阿克苏 克孜勒苏 喀什 和田 伊犁 塔城 阿勒泰 石河子 库尔勒 伊宁 奎屯 阿图什 博乐 昌吉市",
    "香港": "香港 新界 九龙",
    "澳门": "澳门 氹仔 路氹",
    "台湾": "台北 高雄 台中 台南 新北 桃园 台东 花莲 屏东 宜兰 基隆 新竹 苗栗 彰化 南投 嘉义 云林 埔里 新竹市",
}
for _prov, _cities in _CITY_BLOCKS.items():
    for _c in _cities.split():
        CITY_PROVINCE[_c] = _prov
# County-level names frequently seen in IPTV lists but absent from the npm dataset.
for _prov, _cities in {
    "吉林": "前郭 九台 农安 双辽 东丰 舒兰 蛟河 桦甸 磐石 大安 洮南 白城",
    "甘肃": "天祝 岷县 华亭 景泰 民勤 古浪 阿克塞 肃北 两当 康县 成县 徽县",
    "河南": "嵩县 新县 温县 滑县 兰考 叶县 临颍 义马 内黄 偃师 卫辉 南陽 南阳 内乡 光山 鹿邑 太康 淮阳",
    "河北": "景县 任丘 兴隆 清河 宁晋 大名 魏县 磁县 武安 沙河 冀州 深州 安平 饶阳",
    "四川": "泸县 叙州 井研 剑阁 万源 天全 名山 荥经 汉源 石棉 芦山 宝兴 乐至 安岳 威远 隆昌",
    "山西": "古县 万荣 交城 文水 汾阳 孝义 介休 灵石 霍州 侯马 河津 永济 芮城 平陆 夏县 闻喜 稷山",
    "江西": "吉州 抚州 南康 瑞金 丰城 樟树 高安 贵溪 余江 彭泽 湖口 都昌 星子 永修 德安",
    "浙江": "云和 乐清 余姚 余杭 上虞 兰溪 义乌 诸暨 慈溪 瑞安 温岭 临海 玉环 三门 天台 仙居",
    "福建": "云霄 东阳 福清 晋江 石狮 南安 永安 邵武 武夷山 漳平 福安 福鼎 龙海 长乐 闽清 永泰",
    "江苏": "东海 句容 吴江 宜兴 江阴 昆山 常熟 张家港 太仓 高邮 仪征 丹阳 扬中 靖江 兴化 姜堰",
    "湖北": "利川 恩施 巴东 建始 宣恩 咸丰 来凤 鹤峰 神农架 广水 安陆 汉川 应城 京山 钟祥",
    "重庆": "北碚 万州 涪陵 黔江 长寿 江津 合川 永川 南川 綦江 大足 璧山 铜梁 潼南 荣昌 开州 梁平 武隆 丰都 垫江 忠县 云阳 奉节 巫山 巫溪 石柱 秀山 酉阳 彭水",
    "新疆": "伊犁 石河子 兵团 奎屯 伊宁 库尔勒 阿图什 博乐 昌吉",
    "内蒙古": "乌兰察布 赤峰 通辽 鄂尔多斯 巴彦淖尔 呼伦贝尔 锡林郭勒 阿拉善 满洲里 二连浩特",
    "安徽": "亳州 六安 天长 宁国 桐城 宁国 巢湖 繁昌 南陵 青阳 石台 东至 望江 岳西 太湖 潜山",
    "山东": "胶州 即墨 诸城 寿光 龙口 蓬莱 招远 莱州 平度 莱西 章丘 邹平 滕州 曲阜 邹城 兖州",
    "湖南": "浏阳 醴陵 湘乡 韶山 耒阳 常宁 津市 汨罗 临湘 武冈 邵东 双峰 新化 涟源 冷水江",
    "广东": "顺德 南海 番禺 花都 增城 从化 台山 开平 鹤山 恩平 高要 四会 普宁 陆丰 南雄 英德 连州 信宜 高州 化州 廉江 雷州 吴川",
    "云南": "安宁 宣威 个旧 开远 蒙自 弥勒 景洪 瑞丽 芒市 楚雄 大理 丽江 文山 曲靖 玉溪",
    "贵州": "兴义 凯里 都匀 福泉 仁怀 赤水 清镇 六枝 盘县 水城 织金 黔西 大方 金沙 纳雍 威宁",
}.items():
    for _c in _cities.split():
        CITY_PROVINCE[_c] = _prov

# Hong Kong / Macau / Taiwan channels carried in the legacy 港澳台 group.
REGION_KEYWORDS = {
    "香港": ["凤凰", "翡翠", "明珠", "无线新闻", "无线星河", "港台电视", "香港", "有线新闻", "HOY", "Viu", "RTHK", "RHK", "TVB", "亚视", "now新闻", "nownews", "星空卫视", "星空国际"],
    "澳门": ["澳视", "澳门", "澳亚", "莲花卫视"],
    "台湾": ["三立", "东森", "中天", "中视", "华视", "台视", "民视", "公视", "年代新闻", "八大", "纬来", "龙华", "靖天", "美亚", "TVBS", "非凡新闻", "人间卫视", "大爱", "台湾", "台视新闻", "华视新闻", "民视新闻", "中视新闻", "寰宇新闻", "高点", "壹电视"],
}

# National administrative division dataset (china-division npm package), cached locally.
ADMIN_NAME_PROVINCE = {}
_PROV_CODE = {}
try:
    _provinces = json.loads((CACHE / "provinces.json").read_text(encoding="utf-8"))
    for _p in _provinces:
        _n = _p["name"]
        for _suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市"):
            if _n.endswith(_suffix):
                _n = _n[:-len(_suffix)]
                break
        _PROV_CODE[_p["code"]] = _n
    for _fn in ("cities.json", "areas.json"):
        _items = json.loads((CACHE / _fn).read_text(encoding="utf-8"))
        for _it in _items:
            _p = _PROV_CODE.get(_it.get("provinceCode", ""))
            if not _p:
                continue
            _nm = re.sub(r"(市$|县$|区$|旗$|盟$|自治县$|自治州$|地区$)", "", simplify(_it["name"]))
            if len(_nm) >= 2:
                ADMIN_NAME_PROVINCE.setdefault(_nm, _p)
except Exception:
    pass

EN_PROVINCE = {
    "beijing": "北京", "brtv": "北京", "京视": "北京", "tianjin": "天津", "shanghai": "上海", "上视": "上海", "五星体育": "上海", "chongqing": "重庆",
    "hebei": "河北", "shijiazhuang": "河北", "tangshan": "河北", "hengshui": "河北", "handan": "河北",
    "shanxi": "山西", "taiyuan": "山西", "datong": "山西", "jincheng": "山西",
    "neimenggu": "内蒙古", "nei monggol": "内蒙古", "内蒙": "内蒙古", "hohhot": "内蒙古", "chifeng": "内蒙古", "wulanchabu": "内蒙古", "ordos": "内蒙古",
    "liaoning": "辽宁", "shenyang": "辽宁", "dalian": "辽宁", "yingkou": "辽宁", "jinzhou": "辽宁",
    "jilin": "吉林", "changchun": "吉林", "baicheng": "吉林", "siping": "吉林", "tonghua": "吉林", "yanbian": "吉林",
    "heilongjiang": "黑龙江", "harbin": "黑龙江", "qitahe": "黑龙江", "qi台河": "黑龙江", "mudanjiang": "黑龙江", "daqing": "黑龙江", "shuangyashan": "黑龙江",
    "jiangsu": "江苏", "nanjing": "江苏", "suzhou": "江苏", "wuxi": "江苏", "xuzhou": "江苏", "changzhou": "江苏", "nantong": "江苏", "yixing": "江苏",
    "zhejiang": "浙江", "hangzhou": "浙江", "华数": "浙江", "ningbo": "浙江", "wenzhou": "浙江", "jiaxing": "浙江", "huzhou": "浙江", "shaoxing": "浙江", "jinhua": "浙江", "taizhou": "浙江", "lixin": "浙江",
    "anhui": "安徽", "hefei": "安徽", "wuhu": "安徽", "bengbu": "安徽", "huainan": "安徽", "chuzhou": "安徽", "liuan": "安徽", "bozhou": "安徽", "xuancheng": "安徽",
    "fujian": "福建", "fuzhou": "福建", "xiamen": "福建", "quanzhou": "福建", "putian": "福建", "sanming": "福建", "zhangzhou": "福建", "nanping": "福建", "longyan": "福建", "ningde": "福建",
    "jiangxi": "江西", "nanchang": "江西", "jiujiang": "江西", "ganzhou": "江西", "ji'an": "江西", "yichun": "江西", "shangrao": "江西", "jingdezhen": "江西",
    "shandong": "山东", "jinan": "山东", "qingdao": "山东", "yantai": "山东", "weifang": "山东", "jining": "山东", "taian": "山东", "weihai": "山东", "linyi": "山东", "zibo": "山东", "qtv": "山东",
    "henan": "河南", "zhengzhou": "河南", "luoyang": "河南", "kaifeng": "河南", "nanyang": "河南", "xinxiang": "河南", "jiaozuo": "河南", "xuchang": "河南", "zhoukou": "河南", "hebi": "河南", "luhe": "河南",
    "hubei": "湖北", "wuhan": "湖北", "yichang": "湖北", "xiangyang": "湖北", "jingmen": "湖北", "huangshi": "湖北", "shiyan": "湖北", "jingzhou": "湖北", "xiaogan": "湖北", "enshi": "湖北",
    "hunan": "湖南", "changsha": "湖南", "zhuzhou": "湖南", "xiangtan": "湖南", "hengyang": "湖南", "yueyang": "湖南", "changde": "湖南", "chenzhou": "湖南", "yongzhou": "湖南", "huaihua": "湖南",
    "guangdong": "广东", "guangzhou": "广东", "shenzhen": "广东", "dongguan": "广东", "foshan": "广东", "zhuhai": "广东", "shantou": "广东", "huizhou": "广东", "zhanjiang": "广东", "jiangmen": "广东", "chaozhou": "广东", "jieyang": "广东", "shanwei": "广东", "yunfu": "广东", "qingyuan": "广东", "meizhou": "广东", "heyuan": "广东", "yangjiang": "广东", "zhaoqing": "广东", "maoming": "广东",
    "guangxi": "广西", "nanning": "广西", "liuzhou": "广西", "guilin": "广西", "wuzhou": "广西", "beihai": "广西", "qinzhou": "广西", "yulin": "广西", "baise": "广西", "hezhou": "广西", "hechi": "广西", "laibin": "广西", "chongzuo": "广西",
    "hainan": "海南", "haikou": "海南", "sanya": "海南", "danzhou": "海南", "qionghai": "海南", "wenchang": "海南",
    "sichuan": "四川", "chengdu": "四川", "mianyang": "四川", "deyang": "四川", "leshan": "四川", "nanchong": "四川", "yibin": "四川", "dazhou": "四川", "guangyuan": "四川", "suining": "四川", "neijiang": "四川", "liangshan": "四川", "ganzi": "四川", "aba": "四川", "panzhihua": "四川", "luzhou": "四川", "meishan": "四川", "yaan": "四川", "bazhong": "四川", "ziyang": "四川", "xichang": "四川",
    "guizhou": "贵州", "guiyang": "贵州", "zunyi": "贵州", "anshun": "贵州", "liupanshui": "贵州", "bijie": "贵州", "tongren": "贵州", "qianxinan": "贵州", "qian东南": "贵州", "qiannan": "贵州", "kaili": "贵州", "duyun": "贵州",
    "yunnan": "云南", "kunming": "云南", "qujing": "云南", "yuxi": "云南", "baoshan": "云南", "zhaotong": "云南", "lijiang": "云南", "puer": "云南", "lincang": "云南", "chuxiong": "云南", "honghe": "云南", "wenshan": "云南", "xishuangbanna": "云南", "dali": "云南", "dehong": "云南", "nujiang": "云南", "diqing": "云南",
    "xizang": "西藏", "tibet": "西藏", "lhasa": "西藏", "rikaze": "西藏", "changdu": "西藏", "nyingchi": "西藏", "shannan": "西藏", "nagqu": "西藏", "ngari": "西藏",
    "shaanxi": "陕西", "xian": "陕西", "xi'an": "陕西", "baoji": "陕西", "xianyang": "陕西", "weinan": "陕西", "yanan": "陕西", "hanzhong": "陕西", "yulin": "陕西", "ankang": "陕西", "shangluo": "陕西", "tongchuan": "陕西",
    "gansu": "甘肃", "lanzhou": "甘肃", "tianshui": "甘肃", "baiyin": "甘肃", "jiayuguan": "甘肃", "jinchang": "甘肃", "wuwei": "甘肃", "zhangye": "甘肃", "pingliang": "甘肃", "jiuquan": "甘肃", "qingyang": "甘肃", "dingxi": "甘肃", "longnan": "甘肃", "linxia": "甘肃", "gannan": "甘肃", "dunhuang": "甘肃", "hezheng": "甘肃",
    "qinghai": "青海", "xining": "青海", "haidong": "青海", "haibei": "青海", "huangnan": "青海", "golmud": "青海", "yushu": "青海", "haixi": "青海",
    "ningxia": "宁夏", "yinchuan": "宁夏", "shizuishan": "宁夏", "wuzhong": "宁夏", "guyuan": "宁夏", "zhongwei": "宁夏",
    "xinjiang": "新疆", "urumqi": "新疆", "kelamayi": "新疆", "turpan": "新疆", "hami": "新疆", "changji": "新疆", "korla": "新疆", "yining": "新疆", "kashi": "新疆", "hotan": "新疆", "yili": "新疆", "tacheng": "新疆", "aletai": "新疆", "shihezi": "新疆",
    "hongkong": "香港", "hong kong": "香港", "hk": "香港", "rthk": "香港", "tvb": "香港", "hoy": "香港", "hoi": "香港", "viutv": "香港", "now tv": "香港", "nownews": "香港",
    "macau": "澳门", "macao": "澳门", "澳视": "澳门", "tdm": "澳门",
    "taiwan": "台湾", "taipei": "台湾", "kaohsiung": "台湾", "taichung": "台湾", "tainan": "台湾", "taoyuan": "台湾", "hualien": "台湾", "pingtung": "台湾", "yilan": "台湾", "keelung": "台湾", "hsinchu": "台湾", "miaoli": "台湾", "changhua": "台湾", "nantou": "台湾", "chiayi": "台湾", "yunlin": "台湾", "cti": "台湾", "cts": "台湾", "ttv": "台湾", "ftv": "台湾", "sanli": "台湾", "sets": "台湾", "east": "台湾", "gtv": "台湾", "good tv": "台湾", "电视剧": "台湾",
}

CCTV_SERIES_RE = re.compile(
    r"CHC|央视|CCTV|CGTN|CETV|中国教育|中国气象|电视指南|老故事|重温经典|发现之旅|"
    r"世界地理|第一剧场|怀旧剧场|风云剧场|风云足球|风云音乐|高尔夫网球|兵器科技|"
    r"女性时尚|卫生健康|四海钓鱼|劲爆体育|优漫卡通|魅力足球|健康之路|中学生|"
    r"CN卡通|中央|新影| cctv", re.I
)
CCTV_MAIN_RE = re.compile(r"^CCTV\s*[-+]?\s*\d", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】", "", s)
    s = re.sub(r"\b(4K|8K|1080[pPiI]?|720[pPiI]?|2160[pPiI]?|HD|SD|UHD|FHD)\b", "", s, flags=re.I)
    s = re.sub(r"高清|标清|超清|蓝光|频道|电视台|直播|线路[一二三四五六七八九十\d]*", "", s)
    s = re.sub(r"[\s\-_·—+,./\\|\[\]（）()\s]+", "", s)
    return s.lower()


def build_name_maps(raw):
    name_map, city_map = {}, {}
    for g in raw["groups"]:
        p = g["name"] if g["name"] in PROVINCE_ORDER else ""
        for ch in g["channels"]:
            pp = ch.get("province") or p
            if pp in PROVINCE_ORDER:
                name_map[norm(ch["name"])] = pp
            if ch.get("city") in PROVINCE_ORDER:
                city_map[norm(ch["city"])] = ch["city"]
    return name_map, city_map


def infer_province(name: str, ch: dict, name_map: dict, city_map: dict) -> str:
    if ch.get("province") in PROVINCE_ORDER:
        return ch["province"]
    if ch.get("city") in PROVINCE_ORDER:
        return ch["city"]
    if ch.get("city"):
        p = CITY_PROVINCE.get(str(ch["city"]).strip())
        if p:
            return p
    n = norm(name)
    s = simplify(str(name))
    for region, keys in REGION_KEYWORDS.items():
        if any(k.lower() in s.lower() for k in keys):
            return region
    for p in PROVINCE_ORDER:
        if p in s and p not in ("香港", "澳门", "台湾"):
            return p
    # English / pinyin hints, longest first.
    for key in sorted(EN_PROVINCE, key=len, reverse=True):
        if key in n:
            return EN_PROVINCE[key]
    # National administrative division names (prefectures and counties).
    for k, v in sorted(ADMIN_NAME_PROVINCE.items(), key=lambda kv: -len(kv[0])):
        if len(k) >= 2 and k in s:
            return v
    # Known channel names from the raw library.
    for k, v in sorted(name_map.items(), key=lambda kv: -len(kv[0])):
        if len(k) >= 3 and k in n:
            return v
    # Prefecture-level city names, longest first.
    for k, v in sorted(CITY_PROVINCE.items(), key=lambda kv: -len(kv[0])):
        if len(k) >= 2 and k in s:
            return v
    return ""


def cctv_key(name: str):
    s = str(name)
    # CCTV+1 / CCTV+2 / CCTV+3 are extra channels, listed after CCTV1..CCTV17.
    m = re.search(r"CCTV\s*\+\s*(\d+)", s, re.I)
    if m:
        return (1, int(m.group(1)), 0)
    m = re.search(r"CCTV\s*[-·]?\s*(\d+)", s, re.I)
    if m:
        num = int(m.group(1))
        plus = 1 if "+" in s[m.end():m.end() + 2] else 0
        return (0, num, plus)
    return (2, 999, 0)


def main():
    merged = json.loads((CACHE / "merged.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "channels.raw.json").read_text(encoding="utf-8"))
    name_map, city_map = build_name_maps(raw)

    buckets = {}
    for g in merged["groups"]:
        for ch in g["channels"]:
            name = ch["name"]
            src_group = g["name"]
            if src_group == "央视" and CCTV_MAIN_RE.match(name):
                target = "央视"
            elif CCTV_SERIES_RE.search(name):
                target = "央视系列"
            elif src_group == "卫视":
                target = "卫视"
            else:
                p = infer_province(name, ch, name_map, city_map)
                target = p if p else "网络"
            if target == "央视" and not CCTV_MAIN_RE.match(name):
                target = "央视系列"
            if target not in ("央视", "央视系列", "卫视", "网络") and target not in PROVINCE_ORDER:
                target = "网络"
            ch["group"] = target
            if target in PROVINCE_ORDER:
                ch["province"] = target
            buckets.setdefault(target, []).append(ch)

    ordered_names = ["央视", "央视系列", "卫视"] + PROVINCE_ORDER + ["网络"]
    ordered = []
    for gname in ordered_names:
        if gname not in buckets:
            continue
        chans = buckets[gname]
        if gname == "央视":
            chans.sort(key=lambda c: (cctv_key(c["name"]), norm(c["name"])))
        else:
            chans.sort(key=lambda c: norm(c["name"]))
        ordered.append({"name": gname, "channels": chans})

    out = dict(merged)
    out["grouping"] = ordered_names
    out["groups"] = ordered
    out["stats"] = dict(merged["stats"])
    out["stats"]["province_groups"] = len([g for g in ordered if g["name"] in PROVINCE_ORDER])
    (CACHE / "regrouped.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({g["name"]: len(g["channels"]) for g in ordered}, ensure_ascii=False))
    print("网络 sample:", [c["name"] for c in buckets.get("网络", [])[:30]])


if __name__ == "__main__":
    main()
