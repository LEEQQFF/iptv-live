#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""频道/直播源名称规范化模块。

目标：把上游订阅源千差万别的 raw 名称（英文、拼音、繁体、画质标记、
地区标记、时长标记、噪声文案）统一翻译/修正为国内规范频道名称，
确保同一频道在不同源中 converges 到同一个规范名，避免重复频道与乱码名。

对外主函数：
    canonical(raw, item=None) -> str   规范频道名
    validate(name) -> bool             是否是规范/可接受的名称
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 繁简
_SIMPLIFY = str.maketrans({
    "陽": "阳", "撫": "抚", "縣": "县", "頻": "频", "衛": "卫", "視": "视", "東": "东",
    "購": "购", "綜": "综", "藝": "艺", "紀": "纪", "錄": "录", "國": "国", "際": "际",
    "華": "华", "語": "语", "劇": "剧", "場": "场", "導": "导", "員": "员", "灣": "湾",
    "臺": "台", "時": "时", "體": "体", "聞": "闻", "飛": "飞", "龍": "龙", "鳳": "凤",
    "黃": "黄", "點": "点", "聲": "声", "電": "电", "網": "网", "絡": "络", "線": "线",
    "節": "节", "島": "岛", "亞": "亚", "馬": "马", "麗": "丽", "財": "财", "經": "经",
    "濟": "济", "會": "会", "議": "议", "術": "术", "倉": "仓", "庫": "库", "興": "兴",
    "數": "数", "腦": "脑", "覺": "觉", "戰": "战", "壘": "垒", "聯": "联", "賽": "赛",
    "遼": "辽", "寧": "宁", "長": "长", "闊": "阔", "闌": "阑", "壓": "压", "縮": "缩",
    "橫": "横",
})
_MULTI_SIMPLIFY = [
    ("黑龍", "黑龙"), ("頻道", "频道"), ("電視", "电视"), ("新聞", "新闻"),
    ("娛樂", "娱乐"), ("體育", "体育"), ("動畫", "动画"), ("少兒", "少儿"),
    ("財經", "财经"), ("電影", "电影"), ("劇場", "剧场"), ("影視", "影视"),
    ("綜藝", "综艺"), ("少數", "少数"), ("衛視", "卫视"), ("中國", "中国"),
    ("環球", "环球"), ("發現", "发现"), ("綜合", "综合"), ("高清", "高清"),
]

def simplify(s: str) -> str:
    s = str(s or "").translate(_SIMPLIFY)
    # 多字词组的简繁/异体统一
    for a, b in _MULTI_SIMPLIFY:
        s = s.replace(a, b)
    return s

# ---------------------------------------------------------------- 噪声清理
# 画质 / 分辨率 / 时长 / 地区 / 来源标记，均不是频道名的一部分
_NOISE_PATTERNS = [
    r"\[[^\]]*\]", r"【[^】]*】", r"（[^）]*）", r"\([^)]*\)",
    r"〔[^〕]*〕", r"\{[^\}]*\}", r"<[^>]*>",
    r"\b(?:4K|8K|UHD|FHD|HD|SD|HQ|2160[pP]?|1080[pPiI]?|720[pPiI]?|540[pP]?|480[pP]?|360[pP]?|288[pP]?)\b",
    r"(?:高清版|完整版|纯净版|无水印)",
    r"(?:Not24\s*/?\s*7|Non24\s*/?\s*7|24h|24小时)",
    r"(?:Geo-?blocked|Locked|Offline|备用|测试|临时)",
    r"(?:线路[一二三四五六七八九十\d]*|频道\d*|频道[一二三四五六七八九十]+|直播\d*)",
    r"^\s*[-+·•—_\s]+\s*", r"\s*[-+·•—_\s]+\s*$",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.I)

# 无意义噪声整条丢弃
_JUNK_RE = re.compile(
    r"(?:免费订阅|请勿贩卖|公告说明|暂无|待更新|测试频道|News?\s*Live\s*Test|"
    r"^\d{4}-\d\d-\d\d\d\d:\d\d:\d\d$|^\d+$)", re.I)

# ---------------------------------------------------------------- 映射表
# 央视主频道后缀（规范显示名）
CCTV_SUFFIX = {
    1: "综合", 2: "财经", 3: "综艺", 4: "中文国际", 5: "体育", 6: "电影",
    7: "国防军事", 8: "电视剧", 9: "纪录", 10: "科教", 11: "戏曲", 12: "社会与法",
    13: "新闻", 14: "少儿", 15: "音乐", 16: "奥林匹克", 17: "农业农村",
}
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
          "十五": 15, "十六": 16, "十七": 17}

# 央视付费/系列频道英文 -> 国内规范名
CCTV_EN = {
    "billiards": "台球", "snooker": "台球", "golf&tennis": "高尔夫网球",
    "golfandtennis": "高尔夫网球", "golf": "高尔夫网球", "tennis": "高尔夫网球",
    "health": "卫生健康", " nostalgiatheater": "怀旧剧场", "nostalgiatheater": "怀旧剧场",
    "thefirsttheater": "第一剧场", "firsttheater": "第一剧场",
    "stormfootball": "风云足球", "stormmusic": "风云音乐", "stormtheater": "风云剧场",
    "weapon&technology": "兵器科技", "weaponandtechnology": "兵器科技", "weapon": "兵器科技",
    "women'sfashion": "女性时尚", "womensfashion": "女性时尚", "womenfashion": "女性时尚",
    "worldgeography": "世界地理", "cultureofquality": "文化精品", "culture": "文化精品",
    "discovery": "发现之旅", "travel": "旅游", "drama": "电视剧", "cartoon": "卡通",
    "sports": "体育", "news": "新闻", "film": "电影", "music": "音乐",
}
# 央视系列中文别名 -> 规范名
CCTV_CN_ALIAS = {
    "央视怀旧剧场": "怀旧剧场", "央视文化精品": "文化精品", "央视第一剧场": "第一剧场",
    "央视风云剧场": "风云剧场", "央视风云足球": "风云足球", "央视风云音乐": "风云音乐",
    "央视世界地理": "世界地理", "央视台球": "台球", "央视高尔夫网球": "高尔夫网球",
    "央视兵器科技": "兵器科技", "央视女性时尚": "女性时尚", "央视卫生健康": "卫生健康",
    "cctv怀旧剧场": "怀旧剧场", "cctv文化精品": "文化精品", "cctv第一剧场": "第一剧场",
    "cctv世界地理": "世界地理", "cctv卫生健康": "卫生健康", "cctv女性时尚": "女性时尚",
    "cctv兵器科技": "兵器科技", "cctv台球": "台球",
    "cn卡通": "CN卡通", "cctv卡通": "CN卡通",
    "老故事": "老故事", "重温经典": "重温经典", "电视指南": "电视指南",
    "四海钓鱼": "四海钓鱼", "劲爆体育": "劲爆体育", "魅力足球": "魅力足球",
    "优漫卡通": "优漫卡通", "中学生": "中学生频道", "健康之路": "健康之路",
}
# CGTN 系列语言 -> 规范后缀
CGTN_LANG = {
    "arabic": "阿拉伯语", "الم sturdy": "阿拉伯语", " French": "法语", "french": "法语",
    "français": "法语", "francais": "法语", "spanish": "西班牙语", "español": "西班牙语",
    "espanol": "西班牙语", "russian": "俄语", "русский": "俄语", "documentary": "纪录",
    "globalbiz": "环球商务", "business": "环球商务", "china": "中国",
    "chinese": "中文", "english": "英语", "": "",     "中国国际电视台": "", "chinese": "中文", "china": "中文",
    "俄语频道": "俄语", "法语频道": "法语", "西语": "西班牙语", "阿语": "阿拉伯语",
    "纪录频道": "纪录", "西班牙语频道": "西班牙语", "阿拉伯语频道": "阿拉伯语",
}
# CHC 系列
CHC_EN = {
    "action": "动作电影", "home": "家庭影院", "hometheater": "家庭影院",
    "film": "影迷电影", "movie": "高清电影", "hd": "高清电影", "highdefinition": "高清电影",
    "动作电影": "动作电影", "家庭影院": "家庭影院", "影迷电影": "影迷电影",
    "高清电影": "高清电影", "电影": "高清电影",
}
# 卫视频道英文（iptv-org 命名）-> 规范中文
WEISHI_EN = {
    "beijing": "北京卫视", "tianjin": "天津卫视", "hebei": "河北卫视", "shanxi": "山西卫视",
    "innermongolia": "内蒙古卫视", "neimonggol": "内蒙古卫视", "liaoning": "辽宁卫视",
    "jilin": "吉林卫视", "heilongjiang": "黑龙江卫视", "blackdragon": "黑龙江卫视",
    "dragon": "东方卫视", "shanghai": "东方卫视", "east": "东方卫视", "jiangsu": "江苏卫视",
    "zhejiang": "浙江卫视", "anhui": "安徽卫视", "fujian": "东南卫视", "southeast": "东南卫视",
    "jiangxi": "江西卫视", "shandong": "山东卫视", "henan": "河南卫视", "hubei": "湖北卫视",
    "hunan": "湖南卫视", "mango": "湖南卫视", "guangdong": "广东卫视", "guangxi": "广西卫视",
    "hainan": "海南卫视", "chongqing": "重庆卫视", "sichuan": "四川卫视", "guizhou": "贵州卫视",
    "yunnan": "云南卫视", "tibet": "西藏卫视", "shaanxi": "陕西卫视", "gansu": "甘肃卫视",
    "qinghai": "青海卫视", "ningxia": "宁夏卫视", "xinjiang": "新疆卫视",
    "bingtuan": "兵团卫视", "shenzhen": "深圳卫视", "xiamen": "厦门卫视",
    "kangba": "康巴卫视", "yanbian": "延边卫视", "sansha": "三沙卫视",
    "dawan": "大湾区卫视", "andon": "安多卫视", "nonglin": "农林卫视",
    "phoenix": "凤凰卫视", "hongkong": "香港卫视", "taiwan": "台湾卫视",
}
# 常见境外/网络频道 -> 规范中文名（保留国际通行缩写）
GLOBAL_EN = {
    "bbc": "BBC", "cnn": "CNN", "nbc": "NBC", "abc": "ABC", "cbs": "CBS",
    "fox": "FOX", "sky": "SKY", "skynews": "天空新闻", "dw": "德国之声",
    "dw documentary": "德国之声纪录", "dw esp": "德国之声西班牙语",
    "aljazeera": "半岛电视台", "al jazeera": "半岛电视台", "arirang": "阿里郎",
    "kbs world": "KBS世界", "kbs world": "KBS世界", "kbs korea": "KBS韩国",
    "bloomberg": "彭博", "bloomberg": "彭博", "bloombergasia": "彭博亚洲",
    "cna": "CNA", "channelnewsasia": "亚洲新闻台", "tbs": "TBS", "tastemade": "Tastemade",
    "discovery": "探索频道", "nationalgeographic": "国家地理", "natgeo": "国家地理",
    "love nature": "爱自然", "lovenature": "爱自然", "wild earth": "野性地球",
    "TraceSports": "Trace体育", "tracesports": "Trace体育", "eurosport": "欧洲体育",
    "rt": "今日俄罗斯", "rtnews": "今日俄罗斯新闻", "rtdocumentary": "今日俄罗斯纪录",
    "rtdoc": "今日俄罗斯纪录", "rtfrançais": "今日俄罗斯法语", "rtfrancais": "今日俄罗斯法语",
    "rtespañol": "今日俄罗斯西班牙语", "rtespanol": "今日俄罗斯西班牙语",
    "rtarabic": "今日俄罗斯阿拉伯语", "trtworld": "土耳其广播电视公司世界频道",
    "wion": "WION", "wionnews": "WION新闻", "gbnews": "GB News", "newsmax": "Newsmax",
    "cbn": "CBN", "cbnnews": "CBN新闻", "cbc": "CBC", "cbcnews": "CBC新闻",
    "abcnews": "ABC新闻", "abcnewslive": "ABC新闻直播", "nbcnewsnow": "NBC新闻",
    "ntd": "新唐人", "ntdtv": "新唐人", "voa": "美国之音", "voatvchina": "美国之音",
    "suprememastertv": "无上师电视台", "fashiontv": "时尚电视台", "fashion": "时尚电视台",
    "goldeneagecartoon": "金鹰卡通", "dragontelevisioninternational": "东方卫视国际",
    "dragontvinternational": "东方卫视国际", "neimonggoltv": "内蒙古卫视",
    "neimonggoltv2mongolianculturechannel": "内蒙古卫视蒙语文化",
    "bingtuansatellitetv": "兵团卫视", "guangxi sat": "广西卫视", "tvbs": "TVBS",
    "gtv": "八大电视", "sets": "三立电视", "cti": "中天电视", "ttv": "台视",
    "cts": "华视", "ftv": "民视", "pts": "公视", "sanli": "三立电视", "easttv": "东森电视",
    "nownews": "now新闻", "hoy": "HOY", "viutv": "ViuTV", "rthk": "香港电台",
    "tvb": "TVB翡翠", "tvbjade": "TVB翡翠", "tvbn": "TVB明珠",
    "astroaec": "Astro AEC", "8tv": "八度空间", "trans7": "Trans7",
    "amc": "AMC", "电影": "电影", "goodtv": "GOOD TV", "goodtvch1": "GOOD TV综合台",
    "goodtvch2": "GOOD TV真理台", "fifa": "FIFA+", "fifa+": "FIFA+",
    "thelegokernel": "乐高频道", "thelegochannel": "乐高频道", "lego": "乐高频道",
    "petclubtv": "宠物俱乐部", "homeplus": "家居plus", "shoptv": "购物频道",
    "fashion1": "时尚一台", "fashion2": "时尚二台", "hgtv": "HGTV", "foodnetwork": "美食频道",
    "ion": "ION", "ionplus": "ION Plus", "axios": "AXS TV", "axstvnow": "AXS TV",
    "cinemax": "Cinemax", "hdmovie": "高清电影", "clarity4k": "Clarity 4K",
    "ando": "安多", "andotv": "安多卫视", "angel tv chinese": "天使之声中文",
    "angeltvchinese": "天使之声中文", "beautifullifetv": "美好生活",
    "chinatravel": "中国旅游", "china weather channel": "中国气象频道",
    "chinaweatherchannel": "中国气象频道", "discoveringchina": "发现中国",
    "documentary humanities channel": "人文纪录", "cn film middle school channel": "电影中学",
    "cnd film middle school": "电影中学", "cndfilm": "电影频道",
    "fengshang shopping channel": "风尚购物", "high channel tv": "高清频道",
    "nextup live comedy": "喜剧现场", "geniusgogo": "天才GO", "geniusgogoGo": "天才GO",
    "bread tv": "面包TV", "breadtv": "面包TV", "moviesphere": "电影世界",
    "supreme master tv": "无上师电视台", "wild planet": "野性星球",
    "wildplanet": "野性星球", "stadium": "体育场馆", "pop": "Pop音乐",
    "fight network": "格斗网络", "trace sports": "Trace体育",
    "bilibili": "B站", "douyu": "斗鱼", "huya": "虎牙",
}

# iptv-org 英文地名 -> 中文（地方台英文命名，如 Harbin Comprehensive News -> 哈尔滨综合新闻）
EN_CITY = {
    "beijing": "北京", "tianjin": "天津", "shijiazhuang": "石家庄", "tangshan": "唐山",
    "handan": "邯郸", "baoding": "保定", "hengshui": "衡水", "xingtai": "邢台",
    "chengde": "承德", "zhangjiakou": "张家口", "cangzhou": "沧州", "langfang": "廊坊",
    "taiyuan": "太原", "datong": "大同", "jincheng": "晋城", "changzhi": "长治",
    "hohhot": "呼和浩特", "chifeng": "赤峰", "baotou": "包头", "tongliao": "通辽",
    "shenyang": "沈阳", "dalian": "大连", "anshan": "鞍山", "fushun": "抚顺",
    "changchun": "长春", "jilin": "吉林", "tonghua": "通化", "siping": "四平",
    "baicheng": "白城", "yanbian": "延边", "harbin": "哈尔滨", "qiqihar": "齐齐哈尔",
    "mudanjiang": "牡丹江", "daqing": "大庆", "jiamusi": "佳木斯", "qitahe": "七台河",
    "shanghai": "上海", "nanjing": "南京", "suzhou": "苏州", "wuxi": "无锡",
    "xuzhou": "徐州", "changzhou": "常州", "nantong": "南通", "yangzhou": "扬州",
    "yancheng": "盐城", "zhenjiang": "镇江", "taizhou": "泰州", "huaian": "淮安",
    "hangzhou": "杭州", "ningbo": "宁波", "wenzhou": "温州", "jiaxing": "嘉兴",
    "huzhou": "湖州", "shaoxing": "绍兴", "jinhua": "金华", "quzhou": "衢州",
    "zhoushan": "舟山", "linhai": "临海", "yuyao": "余杭", "hefei": "合肥",
    "wuhu": "芜湖", "bengbu": "蚌埠", "huainan": "淮南", "chuzhou": "滁州",
    "fuyang": "阜阳", "suzhouah": "宿州", "liuan": "六安", "xuancheng": "宣城",
    "fuzhou": "福州", "xiamen": "厦门", "putian": "莆田", "quanzhou": "泉州",
    "zhangzhou": "漳州", "nanping": "南平", "longyan": "龙岩", "ningde": "宁德",
    "nanchang": "南昌", "jiujiang": "九江", "ganzhou": "赣州", "ji'an": "吉安",
    "yichun": "宜春", "shangrao": "上饶", "jingdezhen": "景德镇", "pingxiang": "萍乡",
    "jinan": "济南", "qingdao": "青岛", "yantai": "烟台", "weifang": "潍坊",
    "jining": "济宁", "zibo": "淄博", "taian": "泰安", "weihai": "威海",
    "linyi": "临沂", "zhengzhou": "郑州", "kaifeng": "开封", "luoyang": "洛阳",
    "xinxiang": "新乡", "nanyang": "南阳", "jiaozuo": "焦作", "hebi": "鹤壁",
    "xuchang": "许昌", "zhoukou": "周口", "wuhan": "武汉", "yichang": "宜昌",
    "xiangyang": "襄阳", "jingmen": "荆门", "huangshi": "黄石", "shiyan": "十堰",
    "jingzhou": "荆州", "xiaogan": "孝感", "enshi": "恩施", "changsha": "长沙",
    "zhuzhou": "株洲", "xiangtan": "湘潭", "hengyang": "衡阳", "yueyang": "岳阳",
    "changde": "常德", "chenzhou": "郴州", "yongzhou": "永州", "huaihua": "怀化",
    "guangzhou": "广州", "shenzhen": "深圳", "dongguan": "东莞", "foshan": "佛山",
    "zhuhai": "珠海", "shantou": "汕头", "huizhou": "惠州", "zhanjiang": "湛江",
    "jiangmen": "江门", "chaozhou": "潮州", "jieyang": "揭阳", "shanwei": "汕尾",
    "qingyuan": "清远", "meizhou": "梅州", "zhaoqing": "肇庆", "nanning": "南宁",
    "liuzhou": "柳州", "guilin": "桂林", "wuzhou": "梧州", "beihai": "北海",
    "haikou": "海口", "sanya": "三亚", "chongqing": "重庆", "wanzhou": "万州",
    "chengdu": "成都", "mianyang": "绵阳", "deyang": "德阳", "leshan": "乐山",
    "nanchong": "南充", "yibin": "宜宾", "dazhou": "达州", "guangyuan": "广元",
    "liangshan": "凉山", "ganzi": "甘孜", "aba": "阿坝", "guiyang": "贵阳",
    "zunyi": "遵义", "anshun": "安顺", "liupanshui": "六盘水", "bijie": "毕节",
    "kunming": "昆明", "qujing": "曲靖", "yuxi": "玉溪", "baoshan": "保山",
    "zhaotong": "昭通", "lijiang": "丽江", "dali": "大理", "wenshan": "文山",
    "lhasa": "拉萨", "xian": "西安", "baoji": "宝鸡", "xianyang": "咸阳",
    "weinan": "渭南", "yanan": "延安", "hanzhong": "汉中", "lanzhou": "兰州",
    "tianshui": "天水", "jiuquan": "酒泉", "gansu": "甘肃", "xining": "西宁",
    "yinchuan": "银川", "wuzhong": "吴忠", "urumqi": "乌鲁木齐", "kelamayi": "克拉玛依",
    "yili": "伊犁", "korla": "库尔勒", "taipei": "台北", "kaohsiung": "高雄",
    "taichung": "台中", "tainan": "台南", "hongkong": "香港", "macau": "澳门",
}
# 频道类型英文 -> 中文（按 specificity，长词优先）
EN_CATEGORY = [
    ("comprehensive news channel", "综合新闻"), ("comprehensive news", "综合新闻"),
    ("news & general", "新闻综合"), ("news and general", "新闻综合"),
    ("economic life channel", "经济生活"), ("culture & tourism", "文化旅游"),
    ("culture and tourism", "文化旅游"), ("movie channel", "电影"),
    ("public channel", "公共"), ("news channel", "新闻"),
    ("public & news", "公共新闻"), ("comprehensive", "综合"),
    ("silk road channel", "丝路"), ("middle school channel", "中学"),
    ("film discovery channel", "电影Discovery"), ("film", "电影"),
    ("news", "新闻"), ("life", "生活"), ("travel", "旅游"),
    ("tv", ""), ("channel", ""), ("satellite", ""),
]


def translate_en_place(name: str) -> str:
    """把 iptv-org 的英文地名频道名翻译成中文，如 Tonghua TV -> 通化综合。"""
    low = name.lower()
    flat = re.sub(r"[\s'\-]+", "", low)  # 无空格/撇号的连写形式
    # 找城市名（长词优先），支持 TonghuaTV 连写
    city = ""; matched_key = ""
    for k in sorted(EN_CITY, key=len, reverse=True):
        if k in flat:
            city = EN_CITY[k]; matched_key = k
            break
    if not city:
        return ""
    rest = flat.replace(matched_key, " ")
    rest = re.sub(r"\s+", " ", rest).strip(" -&")
    rest_flat = re.sub(r"\s+", "", rest)
    cat = ""
    for en, cn in EN_CATEGORY:
        if re.sub(r"\s+", "", en) in rest_flat:
            cat = cn
            break
    return f"{city}{cat}" if cat else city


# 精确别名（中文环境常见）
EXACT_ALIAS = {
    "上海卫视": "东方卫视", "福建卫视": "东南卫视", "旅游卫视": "海南卫视",
    "芒果台": "湖南卫视", "番茄台": "东方卫视", "荔枝台": "江苏卫视",
    "蓝莓台": "浙江卫视", "北京台": "北京卫视", "湖南卫视高清": "湖南卫视",
    "陕西一套": "陕西新闻资讯", "陕西新闻": "陕西新闻资讯", "陕西新闻咨询": "陕西新闻资讯",
    "陕西二套": "陕西都市青春", "陕西都市": "陕西都市青春",
    "陕西三套": "陕西银龄", "陕西生活": "陕西银龄", "陕西五套": "陕西秦腔",
    "陕西公共": "陕西秦腔", "陕西七套": "陕西体育休闲", "陕西体育": "陕西体育休闲",
    "陕西八套": "陕西西部电影", "陕西影视": "陕西西部电影", "陕西农林": "农林卫视",
    "北京卫视高清": "北京卫视", "CCTV5+": "CCTV-5+", "CCTV5": "CCTV-5",
}


def _clean(raw: str) -> str:
    # 先保护 CCTV-N+ 的加号，避免被噪声清理当成尾部分隔符删掉
    protected = re.sub(r"(CCTV\s*[-+]?\s*\d{1,2})\s*\+", r"\1PLUSPLUSSIGN", raw, flags=re.I)
    s = simplify(protected)
    s = unicodedata.normalize("NFKC", s)
    # 特殊符号归一
    s = s.replace("－", "-").replace("—", "-").replace("–", "-")
    s = s.replace("•", "").replace("𝟙", "1").replace("𝟚", "2")
    s = s.replace("＋", "+").replace("％", "%")
    # 去噪声
    s = _NOISE_RE.sub("", s)
    s = s.strip(" -·—_+|／/\\")
    # 上游"省份I城市"写法（江苏I连云港综合）-> 保留城市频道名
    s = re.sub(r"^(北京|天津|河北|山西|内蒙古|辽宁|吉林|黑龙江|上海|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|重庆|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆)[I｜|](.+)$", r"\2", s)
    # 尾部 HD / backup 等噪声
    s = re.sub(r"\s*(?:HD|backup|bak|备用)\s*$", "", s, flags=re.I)
    return s.replace("PLUSPLUSSIGN", "+")


def _match_table(key: str, table: dict[str, str], fuzzy: bool = True) -> str:
    """按 key 在表中做精确 + 前缀匹配（长 key 优先）。
    fuzzy=True 时允许 key 是表中词的前缀（应对上游截断名称）。"""
    k = re.sub(r"[\s\-_&]+", "", key.lower())
    if k in table:
        return table[k]
    for src in sorted(table, key=len, reverse=True):
        sk = re.sub(r"[\s\-_&]+", "", src.lower())
        if not sk:
            continue
        if k.startswith(sk) or sk in k:
            return table[src]
        # 上游常被截断到 20 字符：key 是词的前缀且长度足够，也算命中
        if fuzzy and len(k) >= 6 and sk.startswith(k):
            return table[src]
    return ""


def _cctv_number(s: str) -> str | None:
    """把各种 CCTV 数字写法统一为 CCTV-N / CCTV-N+，返回规范显示名。"""
    m = re.search(r"CCTV\s*[-+]?\s*(\d{1,2})\s*(\+|plus)?", s, re.I)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 17:
            plus = bool(m.group(2))
            disp = f"CCTV-{n}{'+' if plus else ''}"
            suffix = CCTV_SUFFIX.get(n, "")
            return f"{disp} {suffix}" if suffix and not plus else disp
    m = re.search(r"(?:央视|中央)\s*(十[一二三四五六七]|[一二三四五六七八九十])\s*套", s)
    if m:
        n = CN_NUM.get(m.group(1))
        if n and 1 <= n <= 17:
            return f"CCTV-{n} {CCTV_SUFFIX.get(n, '')}".strip()
    return None


def canonical(raw: str, item: dict | None = None) -> str:
    """把上游 raw 名称规范为国内规范频道名称。

    处理顺序：噪声清理 -> 繁简 -> 央视 -> CGTN -> CHC -> CETV ->
    卫视（英文/别名） -> 省级地名保留 -> 常见境外台 -> 通用清洗。
    """
    original = str(raw or "")
    if not original or _JUNK_RE.search(original):
        return ""
    s = _clean(original)
    if not s or len(s) < 2:
        return ""

    # 1. 央视主频道（CCTV1-17）
    cctv = _cctv_number(s)
    if cctv:
        return cctv

    # 2. CGTN 系列（CGTNChinese / CGNTVChinese / CGNTV 等写法统一）
    if re.search(r"CGTN|CGNTV", s, re.I):
        lang_raw = re.sub(r"^CGNTV\s*|^CGTNTV\s*|^CGTN\s*TV\s*|^CGTN\s*[-_·]?\s*", "", s, flags=re.I).strip()
        lc = lang_raw.lower()
        lang = CGTN_LANG.get(lc)
        if not lang:
            lang = _match_table(lang_raw, CGTN_LANG)
        if not lang and lc:
            lang = {"chinese": "中文", "china": "中文"}.get(lc, lang_raw)
        return f"CGTN{lang}".strip() if lang else "CGTN"

    # 3. CHC 系列
    if re.search(r"CHC", s, re.I):
        tail = re.sub(r"^CHC\s*[-_·]?\s*", "", s, flags=re.I).strip()
        cn = _match_table(tail, CHC_EN) or tail
        return f"CHC{cn}" if cn else "CHC高清电影"

    # 4. CETV / 中国教育
    if re.search(r"CETV|中国教育", s, re.I):
        m = re.search(r"([1-4一二三四])", s)
        n = CN_NUM.get(m.group(1), m.group(1)) if m else "1"
        return f"中国教育{n}台"

    # 5. 央视付费/系列（英文或中文别名）
    if re.search(r"CCTV|央视|CHC|中国气象|电视指南|老故事|重温经典|世界地理|第一剧场|怀旧剧场|风云|高尔夫网球|兵器科技|女性时尚|卫生健康|四海钓鱼|劲爆体育|优漫卡通|魅力足球|CN卡通|中央|新影", s, re.I):
        # 英文 CCTV-XXX（付费频道规范名不带 CCTV- 前缀，与中文写法统一）
        if re.match(r"^CCTV\s*[-_·]", s, re.I):
            tail = re.sub(r"^CCTV\s*[-_·]\s*", "", s, flags=re.I).strip()
            cn = _match_table(tail, CCTV_EN)
            if cn:
                return cn
        alias = CCTV_CN_ALIAS.get(s.lower()) or CCTV_CN_ALIAS.get(s)
        if alias:
            return alias
        # 去掉 CCTV/央视前缀后保留中文
        cn_tail = re.sub(r"^(?:CCTV|央视)\s*[-_·]?\s*", "", s, flags=re.I).strip()
        if re.search(r"[\u4e00-\u9fa5]", cn_tail):
            return cn_tail[:20]
        return re.sub(r"\s+", "", s)[:20]

    # 6. 卫视（英文 / 别名）
    ws = _match_table(s, WEISHI_EN)
    if ws:
        return ws
    # 中文 XX卫视：去掉画质噪声后若为规范省份卫视则直接返回
    if "卫视" in s or "衛視" in s:
        t = re.sub(r"\s+", "", s)
        if len(t) <= 12:
            return EXACT_ALIAS.get(t, t)

    # 7. 精确中文别名
    if s in EXACT_ALIAS:
        return EXACT_ALIAS[s]

    # 8. 常见境外/网络频道
    g = _match_table(s, GLOBAL_EN)
    if g:
        return g

    # 8.5 英文地名频道（iptv-org 地方台）：Tonghua TV / Harbin Comprehensive News
    if re.search(r"[A-Za-z]{3}", s) and not re.search(r"[\u4e00-\u9fa5]", s):
        place = translate_en_place(s)
        if place:
            return place

    # 9. 省级地名频道：保留清理后的中文名
    if re.search(r"[\u4e00-\u9fa5]", s):
        t = re.sub(r"\s+", "", s)
        return t[:20]

    # 10. 纯英文未命中：转为 Title Case，避免全大写长串
    t = re.sub(r"\s+", " ", s).strip()
    if re.fullmatch(r"[A-Za-z0-9+&.' ]+", t):
        return t[:24]
    return t[:24] or original[:24]


def validate(name: str) -> bool:
    """校验是否是可接受的规范名称：非空、非纯噪声、长度合理。"""
    if not name or not isinstance(name, str):
        return False
    if _JUNK_RE.search(name):
        return False
    if len(name) > 30 or len(name) < 2:
        return False
    if re.fullmatch(r"[\d\s\-_:+.]+", name):
        return False
    return True


if __name__ == "__main__":
    tests = [
        "CCTV-1 综合", "CCTV-NostalgiaTheater(1080p)", "CCTV-Golf&Tennis(1080p)",
        "CGTNSpanish(576p)", "CGTN西班牙语", "CHCHomeTheater(1080p)", "CHC动作电影",
        "CETV-1(576p)", "东方卫视[1080][S]", "北京衛視(1080p)[Geo-blocked]",
        "AnhuiTV(1080p)", "BingtuanSatelliteTV(540p)[Not24/7]", "NeiMonggolTV2MongolianCultureChannel",
        "BBC", "CNA", "KBSworld", "莒縣電視一套(576p)", "2026-11-2620:10:38",
        "免费订阅：请勿贩卖...", "东方卫视", "CCTV-5+", "中央一套", "中国教育1台",
    ]
    for t in tests:
        out = canonical(t)
        print(f"{t!r:60} -> {out!r}  valid={validate(out)}")
