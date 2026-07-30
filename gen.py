#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宝妈勇闯自媒体 - 每日创作内容生成器
- 抓取抖音/微博/知乎/头条/60s 热搜
- 调用 DeepSeek 改写 -> 10 选题灵感 + 10 二创角度 + 10 图片文案 + 英语(单词/语法/跟读)
- 可选读取用户维护的 sources.json（金句库 / 通透句库 / 人名日报 / 明星发言 / 热门歌曲 / 感悟库 / 角度库）做事实依据与真金句
- 本地生成速算练习题
- 推送至公开 GitHub Gist（网页端实时读取）

环境变量（建议在 GitHub Secrets 配置）：
  AI_API_KEY    DeepSeek 密钥
  AI_BASE_URL   https://api.deepseek.com/v1
  AI_MODEL      deepseek-chat
  MAMA_PAT      具有 gist 权限的 GitHub 个人令牌
  GIST_ID       目标 Gist 的 ID
  WX_ALBUM_URL  可选：微信公众号/文章列表接口（留空则本地生成速算题）
"""

import os
import io
import re
import sys
import json
import random
import datetime
import urllib.request
import urllib.error

# ---------- 兼容性：保证 stdout 为 UTF-8 ----------
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
MAMA_PAT = os.environ.get("MAMA_PAT", "")
GIST_ID = os.environ.get("GIST_ID", "")
WX_ALBUM_URL = os.environ.get("WX_ALBUM_URL", "").strip()

UA = {"User-Agent": "Mozilla/5.0 (compatible; mama-studio/1.0)"}


def log(*a):
    print("[gen]", *a, flush=True)


def http_json(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- 1. 抓取热搜 ----------------
HOT_SOURCES = {
    "douyin": "https://60s.viki.moe/v2/douyin",
    "weibo": "https://60s.viki.moe/v2/weibo",
    "zhihu": "https://60s.viki.moe/v2/zhihu",
    "toutiao": "https://60s.viki.moe/v2/toutiao",
    "news60": "https://60s.viki.moe/v2/60s",
}


def fetch_hotlists():
    out = {}
    for name, url in HOT_SOURCES.items():
        try:
            d = http_json(url)
            if name == "news60":
                items = (d.get("data") or {}).get("news", [])[:25]
                out[name] = [{"title": t} for t in items if isinstance(t, str)]
            else:
                items = (d.get("data") or [])[:25]
                out[name] = [
                    {"title": it.get("title", ""), "link": it.get("link", "")}
                    for it in items
                    if isinstance(it, dict)
                ]
            log(f"热搜[{name}] 取到 {len(out[name])} 条")
        except Exception as e:
            out[name] = []
            log(f"热搜[{name}] 失败: {e}")
    return out


# ---------------- 2. 调用大模型 ----------------
SYSTEM = (
    "你是一位深耕「宝妈勇闯自媒体」赛道的爆款内容策划与文案高手，"
    "非常熟悉抖音中 5000-50000 粉丝量级的一类宝妈类账号写法，尤其是类似 ayanddq、88007612422、"
    "tian86540、114725631、31872555779 这类账号（它们的共同打法：把『书摘 / 人名日报金句 / 明星发言 / 热门歌曲』"
    "当作图片上的『摘抄素材』，配红笔式情绪标注，再把事实热点写得感人、有力量、通透、利他，关联上柴米油盐和自媒体）。"
    "你的目标受众是 25-40 岁的宝妈，她们最关心：搞钱底气、带娃间隙成长、柴米油盐的精打细算、女性独立、自我价值。"
    "你的服务对象是一位明确的宝妈人设："
    "【人设】她想赚钱、努力活着、有正能量，不是鸡汤文本人设，而是真实、扎实、在带娃间隙认真做自媒体的普通宝妈，"
    "她做自媒体是为了给孩子更好的生活、为了自己有底气、为了活得更有体面。"
    "【照片现实】她每天的配图以孩子为主角——户外跑、背影、侧脸、少量母子合照，极少露脸成人独照。"
    "因此文案必须『宝妈口吻看着孩子写』：第一人称『我（宝妈）』视角，主角多为孩子，"
    "金句（quote）本身就是『书摘素材』式的真原句（书摘/人名日报/明星发言/歌曲），可以像书页一样摆在那儿，这是她们的风格，"
    "但『个人感悟/正文』必须是宝妈借着孩子写的口吻，自然落到『为了孩子 / 为了赚钱 / 为了活得更有体面 / 柴米油盐』上，"
    "不要把『感悟』写成脱离画面的独白式鸡汤（那种成人独白配孩子照片会很违和）。"
    "整体要有『书摘截图风 + 红笔情绪标注感：钩子要像『被这段话戳中了』『这就是安全感』『强大自己才是硬道理』这种有后劲的情绪标签』，"
    "文案要感人、有力量、通透、利他，像一位真实、有阅历的宝妈在跟 25-40 岁的姐妹掏心掏肺聊天，"
    "善用排比、反问、对比，善于谈钱、谈低谷、谈笃定、谈自我成长，"
        "你必须且只能输出一个 JSON 对象，【重要事实前提】这位宝妈目前【还没有通过自媒体赚到一分钱】，但【赚钱欲望非常强烈】，正在学习、搭建、坚持。"
    "文案严禁编造「已赚广告费 / 已有稳定收入 / 账户余额 / 挣了X元」等虚假收入事实；可以写想赚、要搞钱、在学、在坚持、离目标更近。"
    "严禁写『卡里有钱 / 兜里有钱 / 卡里余额 / 你挣的每一分钱』这类表示『现在就已经拥有财富』的表述；想表达搞钱渴望时，改用『想填满的卡 / 心里有底气 / 在搞钱 / 还没赚到第一笔』。"
    "语气对齐她本人收集的爆款话术（阿圆话术 / 阿圆钩子）：通透、争气、长期主义、执行力。"
    "不要任何解释、不要 markdown 代码块、不要多余文字。"
)


def build_user_prompt(hot, sources=None):
    titles = []
    for name, items in hot.items():
        for it in items:
            t = it.get("title", "").strip()
            if t:
                titles.append(t)
    titles = titles[:90]
    titles_text = "\n".join(f"- {t}" for t in titles)

    # 真实来源库（用户维护：金句/通透/人名日报/明星发言/热门歌曲/感悟/角度）
    src_block = ""
    if sources:
        KEYS = [
            ("金句库", "金句库"),
            ("通透句库", "通透句库"),
            ("人名日报", "人名日报金句"),
            ("明星发言", "明星发言"),
            ("热门歌曲", "热门歌曲"),
            ("感悟库", "感悟库"),
            ("角度库", "角度库"),
            ("阿圆话术", "阿圆话术（你本人收集的爆款语气）"),
            ("阿圆钩子", "阿圆钩子（你本人收集的爆款标题框架）"),
            ("有效仿写", "有效仿写（你本人收集的爆款仿写标杆样本）"),
            ("扎心金句", "扎心金句（你本人收集的扎心排比/对比金句）"),
            ("话题标签", "话题标签（你本人收集的爆款话题标签）"),
        ]

        def fmt(label, arr, n=4):
            arr = list(arr or [])[:n]
            if not arr:
                return ""
            return f"【{label}】示例：\n" + "\n".join(f"- {x}" for x in arr) + "\n"

        block = ""
        for key, label in KEYS:
            block += fmt(label, sources.get(key))
        if block:
            src_block = (
                "\n以下是用户提供的真实文案来源库（这是『灵感来源』与『文案来源』，请优先化用其语言风格与通透感，"
                "可改写但必须保持原味、且必须是真实可引用的原句，严禁编造查无出处的假金句）：\n" + block +
                "\n要求：\n"
                "1. image_copywriting 的 quote 必须直接引用上方来源库或真实热点的原句（书摘/人名日报/明星发言/歌曲/网友神评），"
                "并在 hot_source 标注对应类别（人名日报金句 / 通透句库 / 抖音热搜 / 明星发言 / 热门歌曲）。\n"
                "2. 个人感悟要像『书摘截图 + 红笔情绪标注』那种风格：先把金句摆出来，再用宝妈口吻借着孩子写通透解读与扎心感悟。\n"
                "3. 参考角度库，把金句/热点关联到『柴米油盐（买菜/奶粉/房贷/幼儿园）+ 宝妈自媒体搞钱/努力』上，做到感人、有力量、通透、利他。"
                "特别注意：来源库里的『阿圆话术』『阿圆钩子』是你本人收集的爆款语气与标题框架，请优先对齐你本人的口吻（通透、争气、长期主义、执行力强）；但其中若有『已赚到X元 / 有稳定收入 / 变现知足』等收入事实，一律不要照搬——因为你目前【还没通过自媒体赚到一分钱】。"
            )

    return f"""今天是 {datetime.date.today().isoformat()}。以下是今日热搜 / 新闻（来源：抖音、微博、知乎、头条、60s 早报）：

{titles_text}
{src_block}
请基于以上热点（并参考上方来源库），产出一个 JSON，结构必须如下（数组长度务必准确，不得省略）：

{{
  "topic_inspirations": [   // 10 条：宝妈勇闯自媒体-每日灵感 / 人生感悟
    {{
      "title": "标题，16-24 字（含标签），带钩子感；人设：想赚钱、努力活着、有正能量",
      "tag": "标签，如 #宝妈逆袭 #带娃搞钱 #女性成长 #正能量",
      "desc": "说明，关联宝妈勇闯自媒体的真实痛点或爽点，80-140 字，有细节、有共鸣；点出这件事和『搞钱/努力活着/给孩子更好生活』的关系",
      "platform": "douyin 或 bili 或 xhs（请选最合适的主推平台）",
      "type": "热点二创 / 搞钱记录 / 情感共鸣 / 成长记录（四选一，务必准确）"
    }}
  ],
  "remix_angles": [   // 10 条：爆款热点 / 新闻 / 歌曲 / 明星发言 的二创
    {{
      "hot": "选中的热点原文 / 标题 / 明星发言 / 歌曲，务必真实可引用",
      "type": "热点 或 新闻 或 歌曲 或 明星发言（来源要真实可溯源）",
      "angle": "改编角度：如何与宝妈自媒体关联、能怎么拍，60-120 字，具体可操作；主角多为孩子，宝妈是记录者 narrator",
      "copywriting": "学习爆款文案：拆解它为什么火、用了什么情绪/结构/金句，40-80 字",
      "imitate": "深度模仿：给出 2-3 个可直接套用的开头句式 / 文案框架，用 | 分隔"
    }}
  ],
  "image_copywriting": [   // 10 条：用于图片上的图文文案（重点！）
    {{
      "hook": "图片上的红笔情绪钩子，12-15 字（含标签），短促有劲。参考：'被这段话戳中了' / '这就是安全感' / '当妈才懂' / '强大自己才是硬道理' / '柴米油盐里的英雄主义'。用身份认同、反差、扎心、数字、热点名",
      "hot_source": "这条文案借用的来源，必须且只能是以下五类之一并写具体：'人名日报金句' / '通透句库' / '抖音热搜' / '明星发言' / '热门歌曲'。如：'人名日报金句·关于释怀'、'抖音热搜·168巧克力事件'、'热门歌曲·《倔强》'、'明星发言·周星驰'",
      "quote": "金句/原句摘抄（每句必须是完整、独立、一口气读完的 12-16 字整句，不要句内用逗号把多个小分句堆在一起）：给出可引用的真实原句 2 句（短，每句 12-16 字，来自来源库或真实热点/名言/歌词），要选能与标题、感悟自然衔接的短句，像书页摘抄一样摆出来。不要加 '原文：' 前缀",
      "reflection": "个人感悟 1-2 句（每句必须是完整、独立、一口气读完的 12-16 字整句，不要句内用逗号把多个小分句堆在一起）：每句 12-16 字，宝妈第一人称、借着孩子写，把金句自然落到『为了孩子 / 为了赚钱 / 柴米油盐』上，语气要与标题、原文连成一段，像一口气写完的，通透、有力量、利他",
      "body_long": "延展性正文（长版）10 句：继续展开，紧扣 25-40 岁宝妈切身相关的话题——带娃搞钱、女性成长、自我底气、柴米油盐的精打细算、做自媒体的真实挣扎与复利。语气像姐妹掏心掏肺，利他、通透、能给方法",
      "body_short": "延展性正文（短版）5-6 句：长版的精简版，同样吸引 25-40 岁宝妈，保留钩子感与通透劲",
      "title": "延续性标题 12-16 字：必须有钩子感，直接套用『阿圆钩子』库的爆款框架（如谁懂啊/救命/被戳中/太X了/杀回来了/请你努力），像宝妈版短视频标题一样短促、有情绪、抓眼球。如：'救命！安全感全靠自己给' / '谁懂啊！带娃搞钱真带劲'"
    }}
  ],
  "english": {{
    "words": [
      {{"word": "简单高频词(英文)", "phonetic": "音标", "meaning": "中文释义", "example": "英文例句"}}
    ],   // 5 个，面向成年宝妈基础，最简易高频
    "grammar": "一条最基础语法（如 主谓宾 / be 动词 / 人称代词），30 字以内",
    "shadow": "一句适合带孩子跟读的极简单句，8-12 个词，生活化"
  }}
}}

写作要求（重点）：
1. 人设与目标受众贯穿：她是想赚钱、努力活着、有正能量的宝妈；受众是 25-40 岁宝妈，最关心搞钱底气、带娃成长、柴米油盐、女性独立。文案真实扎实，不浮夸。
2. 图文人称匹配：配图以孩子为主角（户外/背影/侧脸），文案用『宝妈看着孩子』第一人称；金句(quote)是书摘式真原句摆图上（她们风格），个人感悟(reflection)必须借着孩子写、落柴米油盐，严禁独白式鸡汤。
3. 组合结构：quote（3-4 句原句摘抄）+ reflection（2-3 句个人感悟）构成图片上的图文；图片下方再用 body_long（10 句）/ body_short（5-6 句）做延展性正文。
4. hook 12-15 字，短促有劲、有情绪标注感。
5. quote 2 句（短）即可，每句 12-16 字，真实可引用；hot_source 严格五类之一并具体。
6. reflection 1-2 句；body_long 必须 10 句；body_short 必须 5-6 句；三者都紧扣 25-40 岁宝妈、关联自媒体搞钱与柴米油盐。注意：title+quote+reflection 会合并成『图上正文』放到图片上（再次强调：quote/reflection 的每一句都应是独立完整的 12-16 字整句，不要靠逗号把小分句拼成长句），『图上正文』放到图片上，要求写成一段连贯正文——总句数 ≤10 句、每句 12-16 字、句子之间自然衔接（像一口气写下来），标题就是第一句钩子。
7. title 12-18 字、要有钩子、通透、吸引 25-40 岁宝妈，写与她们息息相关的事（搞钱/底气/带娃闯关成长/不被生活拖垮）。
8. 严禁惨兮兮、自怜、卖惨、哭、崩溃、心碎、心酸、委屈、嫌弃、抛弃等任何卖惨/自怜类词汇；所有痛点必须转化为力量感、选择感、成长感和具体方法，让读者觉得『被说中』但更有劲，不是更丧。程序会硬性剔除上述词，务必从根上不写。
9. 所有字段值必须是合法 JSON 字符串，如需换行（如 quote/reflection/正文多句）请用 \\n 转义，不要输出真实换行符。
10. 不要遗漏任何字段，不要输出 markdown 代码块，只输出 JSON 对象。
11. 【重要事实前提】这位宝妈目前【还没有通过自媒体赚到一分钱】，但她【赚钱的欲望非常强烈】，正在学习、搭建、坚持。因此文案中【严禁编造「已赚到广告费 / 已有稳定收入 / 账户余额变多 / 挣了X元」等虚假收入事实】；可以写【想赚、要搞钱、在学、在坚持、离目标更近、还没赚到但一定要赚到】的真实状态与强烈渴望。严禁出现『卡里有钱 / 兜里有钱 / 卡里余额 / 你挣的每一分钱』这类『现在就拥有财富』的表述，一律改为『想填满的卡 / 心里有底气 / 在搞钱 / 还没赚到第一笔』的渴望向表述。
12. 图片文案（排版与说话感觉）要求（重要，作为每日稳定产出）：image_copywriting 的 10 条里，至少 3 条、目标 4-5 条必须采用「标题（钩子）+ 原句/金句（quote）+ 宝妈感悟（reflection）合并成图上正文」的爆款排版与语气（参考来源库「有效仿写」标杆样本：扎心年龄排比、跟谁混对比、通透感悟、赚钱底气——这些都是「说话的感觉」，不是固定题材，也不要每天用同一句原话二创）。关键点：① 题材来源——优先从当日【抖音热搜 / 明星发言 / 热门歌曲（歌词/歌名共鸣）】中选取，面向 25-55 岁女性兴趣（情感、婚姻、家庭、搞钱、女性成长、育儿、怀旧金曲、明星话题、自我和解等），不局限于固定账号或某个人物，每天题材都要新鲜；其中至少 1-2 条应直接挂钩当日抖音热搜的具体事件或热门歌曲歌词，避免全部来自固定金句库；② quote 必须直接引用真实来源（书摘/明星发言/金句/热搜原句/歌词），并在 hot_source 标对应类别，禁止连续多天重复同一句原句；③ reflection 落到宝妈做自媒体（刷推荐页、赢曝光、搞钱底气、长期主义），用「阿圆话术」语气；④ img_text 严格按「标题+原句+感悟」合并成每句 12-16 字连贯正文（个别整句金句可到 21-22 字），并给出放图位置提示（图片上半部留白、衣服处，只放这一块）；⑤ body_long 必须 10 句、body_short 必须 5-6 句；⑥ 结尾带话题标签（参考「话题标签」，含 #宝妈勇闯自媒体 等）。其余条目也尽量沿用此基调。
"""


def chat(system, user, temperature=0.7):
    url = AI_BASE_URL + "/chat/completions"
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=150) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1).strip()
    text = text.strip()
    if text.startswith("["):
        s, e = text.find("["), text.rfind("]")
    else:
        s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        text = text[s : e + 1]
    return json.loads(text)


def cn_len(s):
    """字数统计：去掉空白后按字符数（含标点，与中文'字数'口径一致）。"""
    return len(re.sub(r"\s", "", s or ""))


def cn_sents(s):
    """按中文句末标点切句（保留标点），返回非空句子列表。"""
    parts = re.split(r"(?<=[。！？!?])", s or "")
    return [p for p in parts if p.strip()]


# ---------------- 惨兮兮词库封锁（硬性兜底，杜绝卖惨/自怜/哭崩）----------------
# 这些词一旦出现，整句用干净的通透句替换；短字段（钩子/标题）做内联替换
SAD_WORDS = [
    "崩溃", "惨兮兮", "卖惨", "眼泪", "泪水", "心碎", "心酸",
    "绝望", "委屈", "嫌弃", "抛弃", "难熬", "撑不住", "扛不住",
    "累垮", "离了", "离过", "惨", "哭", "泪", "熬", "软", "凉",
]

# 钩子/标题等短字段内联替换映射（长词优先）
SAD_INLINE = [
    ("崩溃了", "清醒了"), ("崩溃", "清醒"),
    ("惨兮兮", "通透"), ("卖惨", "说真话"),
    ("眼泪", "底气"), ("泪水", "底气"), ("心碎", "想通"),
    ("心酸", "清醒"), ("绝望", "有劲"), ("委屈", "硬气"),
    ("嫌弃", "清醒"), ("抛弃", "独立"), ("难熬", "充实"),
    ("撑不住", "能扛"), ("扛不住", "能扛"), ("累垮", "更有劲"),
    ("离了", "清醒了"), ("离过", "清醒了"), ("惨", "通透"),
    ("哭", "醒"), ("泪", "劲"), ("熬", "拼"), ("软", "稳"), ("凉", "清醒"),
]

# 书摘风「原句」兜底池：通透 / 女性成长 / 搞钱 / 清醒（无惨词）
QUOTE_POOL = [
    "女人最大的底气，是把命运握在自己手里。",
    "所谓安全感，从来不是谁给的，是自己挣的。",
    "你可以是妈妈，但首先要是你自己。",
    "真正的独立，是兜里有钱，心里不慌。",
    "柴米油盐里，也藏着把日子过好的能力。",
    "当妈后我才懂，靠谁都不如靠自己踏实。",
    "能赚钱的女人，连说话声音都更稳。",
    "把生活过成想要的样子，本身就是一种成功。",
    "清醒的女人，早就不再等别人来救自己。",
    "你挣的每一分钱，都是给孩子选择未来的底气。",
    "房子比男人靠谱，女人要自己有房。",
    "别用别人的标准，定义你自己的幸福。",
]


def _has_sad(t):
    return any(w in (t or "") for w in SAD_WORDS)


def clean_sad_sentences(sents, pool, idx):
    """把含惨词的句子整句替换为干净的通透句（按索引轮换），返回清洗后的句子列表。"""
    out = []
    k = 0
    n = max(1, len(pool))
    for st in sents:
        if _has_sad(st):
            if pool:
                out.append(pool[(idx + k) % n])
                k += 1
            # 无兜底池则直接丢弃该句
        else:
            out.append(st)
    return out


def clean_sad_inline(t):
    """对短字段（钩子/标题）做内联替换，去掉惨词。"""
    t = t or ""
    for bad, good in SAD_INLINE:
        if bad in t:
            t = t.replace(bad, good)
    return t

# ---------------- 收入造假词封锁（用户尚未通过自媒体赚到一分钱）----------------
# 只屏蔽「已赚到」类虚假收入事实；「想赚/要搞钱/在学/在坚持」等渴望语气一律保留
MONEY_FAKE = [
    ("收入不多，但够给孩子加个鸡腿", "还没赚到第一桶金，但每天离目标更近"),
    ("够给孩子加个鸡腿", "在一点点靠近目标"),
    ("账户里慢慢多起来的余额", "账号一点点长起来的势头"),
    ("账户余额多起来", "搞钱的目标在靠近"),
    ("卡里那点余额", "想填满卡的底气"),
    ("卡里的余额", "想填满的卡"),
    ("稳定副业收入", "搞钱的野心"),
    ("副业收入", "搞钱的劲头"),
    ("有了稳定的收入", "憋着一股要做出收入的劲"),
    ("每天那几十块、几百块", "每天写的那几十字、剪的那几个视频"),
    ("几十块、几百块", "写下的每句话说给同频的人"),
    ("已经挣到了", "想挣到的"),
    ("挣到了146", "想挣到第一笔"),
    ("挣了198块", "想挣到第一笔"),
    ("挣了198", "想挣到第一笔"),
    ("挣到1466", "想挣到第一笔"),
    ("0粉也能挣到收益了", "0粉也要冲着收益去"),
    ("无门槛挣到了198", "无门槛也要冲着收益去"),
    ("靠自媒体能变现，就已经很知足了", "靠自媒体变好，就是每天的小确幸"),
    ("每天都要固定收入", "每天都在为收入蓄力"),
    ("一条视频挣了", "一条视频想挣"),
    ("给自己挣到屁粮了", "想给孩子挣到底气"),
    ("娃挣到了屁粮", "想给孩子挣到底气"),
    # 新增：当前拥有财富的硬表述（用户尚未通过自媒体赚到一分钱）
    ("卡里有钱手机有电", "手里有劲眼里有光"),
    ("卡里有钱", "想填满的卡"),
    ("卡里的钱", "想填满的卡"),
    ("卡里余额", "想填满的卡"),
    ("兜里有钱", "心里有光"),
    ("兜里的钱", "心里的底气"),
    ("你挣的每一分钱", "你想要的每一分底气"),
    ("挣的每一分钱", "想要的每一分底气"),
    ("账户余额", "想填满的卡"),
    ("广告费", "搞钱的盼头"),
    ("月入", "盼着有进账"),
]


def clean_money(t):
    """剔除编造的「已赚到」类收入事实，改为想赚/在学的真实状态。"""
    t = t or ""
    for bad, good in MONEY_FAKE:
        if bad in t:
            t = t.replace(bad, good)
    # 正则兜底：仍有漏网的『当前拥有财富』表述
    t = re.sub(r"卡里(的)?(那点|一点)?(余额|钱)", "想填满的卡", t)
    t = re.sub(r"兜里(的)?钱", "心里的底气", t)
    t = re.sub(r"你?挣的(每)?(一分)?钱", "想要的每一分底气", t)
    return t

# ---------------- 钩子字数强制合规（程序化兜底，钩子 12-15 字）----------------
HOOK_BANK = [
    # 情绪标注型
    "被这段话戳中了：当妈后全靠自己",
    "这就是安全感：卡里有钱手机有电",
    "强大自己才是硬道理当妈才懂",
    "原来当妈后，人真的会脱胎换骨",
    "这段话共情了：原来我不是一个人",
    "真正清醒的人跳过了情绪内耗",
    # 柴米油盐/数字型
    "别让柴米油盐埋没了你自己",
    "柴米油盐里，藏着搞钱逻辑",
    "奶粉钱靠自己挣才最踏实可靠",
    "房贷压力倒逼我开启了副业",
    "幼儿园学费倒逼我成长起来",
    "月入过万，从一篇笔记开始",
    # 女性成长/反认知型
    "你可以是妈妈，但更要先是自己",
    "当妈后我才懂，安全感是自己给的",
    "房子比男人靠谱，女人要清醒",
    "宝妈经济独立，是给自己底气",
    "25岁还没存款的宝妈必看",
    "你现在只有一份工作吗宝妈",
    # 搞钱/副业型
    "全职妈妈副业成功的根本原因",
    "宝妈必看0成本搞钱的8个副业",
    "如何做成月入6位数的副业",
    "宝妈赚钱带娃两不误的秘密",
    "月入6位数的副业怎么做？",
    "会赚钱的博主不会说的秘密",
    "阻碍你自媒体变现的3件事",
    "赚钱博主都在做的一件事！",
    # 带娃间隙/行动型
    "带娃搞钱两年，我活成自己屋檐",
    "30岁重启人生，从阅读开始",
    "用碎片时间，撬动被动收益",
    "带娃焦虑不如搞钱充实自己",
    "别再说没时间，宝妈时间最贵",
]

FILLERS = [
    "，你中了几条",          # 6
    "，这就是底气",          # 6
    "，清醒且独立",          # 6
    "，女性成长记",          # 6
    "，宝妈逆袭路",          # 6
    "，搞钱才是王",          # 6
    "，别小瞧自己",          # 6
    "，当妈才懂的",          # 6
    "，独立才自由",          # 6
    "，这就是答案",          # 6
]

SHORT_FILLERS = [
    "你中几条",
    "搞钱要紧",
    "通透了",
    "太真实",
    "女性必看",
    "宝妈逆袭",
]


def _clean(s):
    return re.sub(r"\s", "", s or "")


def enforce_hook(hook, idx):
    s = _clean(hook)
    if 12 <= len(s) <= 15:
        return hook
    # 原钩子太短或空，直接用爆款钩子库替换（按序号交替）
    if len(s) < 8:
        return HOOK_BANK[idx % len(HOOK_BANK)]
    if len(s) < 12:
        base = re.sub(r"[，。！？、\s]+$", "", hook)
        # 优先用短句，保证 base+后缀 落在 12-15
        for bank in (FILLERS, SHORT_FILLERS):
            for k in range(len(bank)):
                suf = bank[(idx + k) % len(bank)]
                if 12 <= len(s) + len(_clean(suf)) <= 15:
                    return base + suf
        # 兜底：拼接头句截断到 15；若仍不足 12，则循环重复短尾
        cand = _clean(hook + FILLERS[idx % len(FILLERS)])[:15]
        while len(cand) < 12:
            cand += SHORT_FILLERS[(idx + len(cand)) % len(SHORT_FILLERS)]
        return cand[:15]
    # 超过 15 字：保留更有力的尾部
    return s[-15:]


def enforce_hooks(items):
    for i, x in enumerate(items):
        x["hook"] = enforce_hook(clean_sad_inline(x.get("hook", "")), i)
    return items


# ---------------- 句数强制合规（图片文案的 quote/reflection/正文）----------------
SENT_POOL = {
    "reflection": [
        "所谓安全感，从来不是别人给的，是想填满卡的底气，和深夜还能剪视频的劲头。",
        "我们当妈的，不是没退路，而是主动选择把退路握在自己手里。",
        "孩子不会记得你赚了多少，但会记得你眼里的光，和从没放弃的模样。",
        "搞钱不是俗气，是给娃兜底的能力，也是自己活得有体面的底气。",
        "每一笔花在刀刃上的钱，都是在给娃攒未来的选择权，清醒又体面。",
        "妈妈不是超人，只是学会了把情绪收拾好，把力气用在搞钱和带娃上。",
        "你现在的每一分努力，孩子将来都会收到，只是以另一种方式。",
        "别怕慢，普通人的光都是一步步走出来的，你脚下的每一步都在增值。",
    ],
    "body_long": [
        "很多姐妹问我，一个人带娃怎么还有精力做自媒体，其实哪有什么天赋，不过是把别人刷手机的时间，拿来拍娃、写文案、剪视频。",
        "一开始我也放不下面子，但想到娃的奶粉钱和未来的学费，我决定先开始再说。",
        "慢慢我发现，记录带娃日常不是在倒苦水，而是在告诉同样焦虑的宝妈：你不是一个人在扛。",
        "评论区里那些『说我了』『我也是』，比涨粉更让我踏实，因为我们在彼此照亮。",
        "搞钱这件事，从不丢人，丢人的是明明可以靠自己，却把希望全押在别人身上。",
        "我把自己走过的坑、踩过的雷都写下来，就是想让后来的姐妹少走点弯路。",
        "别小看每天写的那几十字、剪的那几个视频，攒着攒着，就是在给未来的底气打地基。",
        "自媒体不是一夜暴富的捷径，但它给普通宝妈开了一扇窗，让努力被看见、被变现。",
        "如果你也在带娃和搞钱之间平衡，别急，咱们一起慢慢来，流水不争先，争的是滔滔不绝。",
        "记住，你先是自己，才是妈妈；先站稳了，才扛得动身后的小家。",
    ],
    "body_short": [
        "带娃搞钱这两年，我最大的体会就是：靠自己，才最踏实。",
        "别怕起步晚，普通宝妈的光，都是一天天走出来的。",
        "你记录的不是娃，是你不服输的劲儿，姐妹们都能看见。",
        "搞钱不丢人，给娃兜底的能力才是真的体面。",
        "慢慢来，咱们一起在柴米油盐里，活出自己的底气。",
        "你先是你自己，才是妈妈，先站稳，才扛得动家。",
    ],
}


def enforce_sents(items, field, lo, hi, pool, pad=True):
    """句数强制合规：截到 hi 句；不足 lo 句则从兜底池按索引轮换补齐（真实兜底句）；并硬性剔除惨词句。"""
    n = max(1, len(pool))
    for idx, x in enumerate(items):
        s = x.get(field, "")
        sents = cn_sents(s)
        # 1) 剔除含惨词的句子，用干净的通透句替换（按索引轮换，避免重复）
        cleaned = []
        k = 0
        for st in sents:
            if _has_sad(st):
                if pool:
                    cleaned.append(pool[(idx + k) % n])
                    k += 1
                # 无兜底池则丢弃
            else:
                cleaned.append(st)
        sents = cleaned
        # 2) 超长截断
        if len(sents) > hi:
            sents = sents[:hi]
        # 3) 不足补干净句
        if pad:
            while len(sents) < lo and k < lo + n:
                sents.append(pool[(idx + k) % n])
                k += 1
        x[field] = "".join(sents)
    return items


# ---------------- 通用字数兜底（选题/二创/标题）----------------
TAIL_POOL = {
    "title": [
        "，致敬每一个不放弃的宝妈",
        "，写给还在咬牙坚持的你",
        "，当妈后才懂的真相",
        "，普通妈妈的清醒时刻",
        "，带娃也能赚到的底气",
        "，柴米油盐里的英雄主义",
    ],
    "copywriting": [
        "。情绪真实、戳心、金句密集，是它破圈的关键。",
        "。它用宝妈视角把热点翻译成了生活，让人一看就觉得『说我了』。",
        "。把大词拆成小日子，才是这条赛道最稳的流量密码。",
        "。它不喊口号，只讲带娃间隙的真实挣扎，反而最动人。",
    ],
    "angle": [
        "。把热点放进宝妈的真实生活里，让观众觉得说的就是自己。",
        "。用具体场景引发共鸣，比空洞口号更容易获得流量。",
        "。先共情再给方法，观众才愿意留下来看你的自媒体。",
    ],
    "desc": [
        "。这个选项没有门槛，普通宝妈照着拍，也能拿到属于自己的流量。",
        "。当你把它和真实生活挂钩时，算法自然会长出共鸣。",
        "。不需要华丽机位，真实和扎心就是这条赛道最大的流量密码。",
        "。别怕没人看，先发出去，对的人会在评论区等你。",
    ],
}


def enforce_text(items, field, min_len, max_len, pad=True):
    pool = TAIL_POOL.get(field, ["。坚持下来，时间会给你答案。"])
    n = max(1, len(pool))
    for idx, x in enumerate(items):
        s = x.get(field, "")
        L = cn_len(s)
        # 太短：从池子里按序号轮换追补，直到达标或耗尽，避免所有条目尾巴雷同
        # （pad=False 时跳過补写，保留 AI 给出的短钩子/标题，避免被金句尾巴截断）
        tries = 0
        if pad:
            while L < min_len and tries < n:
                s = s + pool[(idx + tries) % n]
                L = cn_len(s)
                tries += 1
        # 太长：截断并尽量保持句尾完整
        if L > max_len:
            cleaned = _clean(s)
            trunc = cleaned[:max_len]
            for p in ["，", "。", "！", "？", "、", "：", " "]:
                j = trunc.rfind(p)
                if j >= max_len * 0.6:
                    trunc = trunc[:j + 1]
                    break
            s = trunc
            L = cn_len(s)
        # 若耗尽仍短，用最长兜底再补一次（pad=True 时；pad=False 不强补，允许短钩子）
        if pad and L < min_len:
            s = s + pool[-1]
            if cn_len(s) > max_len:
                s = _clean(s)[:max_len]
        x[field] = s
    return items


# ---------------- 组装「图上正文」：标题+原文+感悟 合并，控字数预算 ----------------
def _trim_to(s, hi):
    """把超长句截到 ≤hi 字，尽量在句中连词/标点处收尾，避免生硬断头。"""
    s = s.strip()
    if cn_len(s) <= hi:
        return s
    cut = s[:hi]
    for p in ["，", "。", "！", "？", "、", "：", "；"]:
        j = cut.rfind(p)
        if j >= int(hi * 0.6):
            return s[: j + 1]
    return cut


def _split_units(s):
    """按中文句末标点或换行切成小片段（保留标点）。
    AI 有时用 \n 代替标点断句，这里统一按 [。！？；\n] 切。"""
    parts = re.split(r"([。！？；\n])", s or "")
    units, buf = [], ""
    for p in parts:
        if p in ("。", "！", "？", "；", "\n"):
            if buf.strip():
                units.append(buf.strip() + ("" if p == "\n" else p))
            buf = ""
        else:
            buf += p
    if buf.strip():
        units.append(buf.strip())
    return units


def _break_long(u, hi, lo=12):
    """超长片段：若整句没有内部逗号/顿号/冒号/分号，整体保留（避免生硬断词）。：尽量在逗号/顿号/冒号/分号处断开，每段尽量 ≥lo（≤hi）。
    到上限时回退到最近的连词处断，避免生硬断词；末尾残余纯标点并入上一片。"""
    if cn_len(u) <= hi:
        return [u]
    if not any(p in u for p in ("，", "、", "：", "；")):
        return [u]
    pieces, cur = [], ""
    for ch in u:
        cur += ch
        if ch in ("，", "、", "：", "；") and lo <= cn_len(cur) <= hi:
            pieces.append(cur); cur = ""
        elif cn_len(cur) >= hi:
            best = -1
            for p in ("，", "、", "：", "；"):
                j = cur.rfind(p)
                if j > best:
                    best = j
            if best >= 6:
                pieces.append(cur[:best + 1]); cur = cur[best + 1:]
            else:
                pieces.append(cur); cur = ""
    if cur:
        if pieces and cur.strip() in ("。", "！", "？", "．", "…"):
            pieces[-1] = pieces[-1] + cur
        else:
            pieces.append(cur)
    final = []
    for p in pieces:
        if cn_len(p) > hi:
            while cn_len(p) > hi:
                final.append(p[:hi]); p = p[hi:]
            if p:
                final.append(p)
        else:
            final.append(p)
    return final or [u[:hi]]


def _merge_units(units, lo, hi):
    """把小片段向前合并成 12-18 字左右的连贯短句。
    上一句以连词/逗号结尾或偏短且合并后≤hi 则并入；第二遍再把仍偏短的行并入上一行，消除过短碎片。"""
    out = []
    for u in units:
        u = u.strip()
        if not u:
            continue
        if cn_len(u) > hi:
            out.extend(_break_long(u, hi))
            continue
        if out:
            last = out[-1]
            if (last[-1:] in ("，", "、", "：", "；") or cn_len(last) < lo) and cn_len(last) + cn_len(u) <= hi:
                out[-1] = last + u
                continue
        out.append(u)
    merged2 = []
    for u in out:
        if merged2 and cn_len(u) < lo and cn_len(merged2[-1]) + cn_len(u) <= hi + 2:
            merged2[-1] = merged2[-1] + u
        else:
            merged2.append(u)
    return merged2


def enforce_img_text(items, max_sents=10, lo=12, hi=18):
    """标题+原文+感悟 合并成一段『图上正文』。
    ① 标题+原文+感悟写成一段连贯正文；② 总句数 ≤10；③ 每句 12-18 字（12-16 字左右）；
    ④ 标题作为第一句（钩子），接着原文，最后感悟；⑤ 三者都至少出现一句。
    容错：AI 可能用 \n 代替标点，这里先按 [。！？；\n] 切段，再贪心合并成 12-18 字短句；标题去掉尾逗号。"""
    for x in items:
        title = (x.get("title") or "").strip().rstrip("，、：；")
        quote = x.get("quote") or ""
        refl = x.get("reflection") or ""
        q_units = _split_units(quote)
        r_units = _split_units(refl)
        units = ([title] if title else []) + q_units + r_units
        merged = _merge_units(units, lo, hi)
        need = 1 + (1 if q_units else 0) + (1 if r_units else 0)
        keep = max(need, min(max_sents, len(merged)))
        merged = merged[:keep]
        x["img_text"] = "\n".join(merged)
    return items


# ---------------- 3. 用户维护的『真实文案来源库』 ----------------
def load_sources():
    """读取仓库根目录的 sources.json（用户维护：金句库 / 通透句库 / 人名日报）。
    不存在或解析失败则返回 None，由调用方按『AI 自行生成』处理。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception as e:
        log(f"sources.json 读取失败，跳过: {e}")
    return None


# ---------------- 3.5 兜底与补全 ----------------
def pad(arr, n, factory):
    arr = list(arr or [])
    while len(arr) < n:
        arr.append(factory(len(arr)))
    return arr[:n]


def img_factory(i):
    return {
        "hook": "原来当妈后，人真的会脱胎换骨",
        "hot_source": "今日热搜",
        "quote": "人生没有最好的年龄，只有最好的心态。我们争不过岁月，也跑不过时间。唯有以自己喜欢的方式，过好每一个日出日落。",
        "reflection": "被这段话戳中了。当妈后的底气，都是自己一分一分挣出来的。",
        "body_long": (
            "很多姐妹问我，一个人带娃怎么还有精力做自媒体，其实哪有什么天赋，不过是把别人刷手机的时间，拿来拍娃、写文案、剪视频。"
            "一开始我也害羞，怕被熟人看到，但想到娃的奶粉钱、学费，就硬着头皮上了。"
            "慢慢我发现，记录带娃日常不是在卖惨，而是在告诉同样焦虑的宝妈：你不是一个人在扛。"
            "评论区里那些『说我了』『我也是』，比涨粉更让我踏实，因为我们在彼此照亮。"
            "搞钱这件事从不丢人，丢人的是明明可以靠自己，却把希望全押在别人身上。"
            "别小看每天那几十块，攒着就能给娃报个兴趣班，给自己留点退路。"
            "自媒体不是一夜暴富的捷径，但它给普通宝妈开了一扇窗，让努力被看见、被变现。"
            "如果你也在带娃和搞钱之间挣扎，别急，咱们一起慢慢来，流水不争先，争的是滔滔不绝。"
            "记住，你先是自己，才是妈妈；先站稳了，才扛得动身后的小家。"
        ),
        "body_short": (
            "带娃搞钱这两年，我最大的体会就是：靠自己，才最踏实。"
            "别怕起步晚，普通宝妈的光，都是一天天熬出来的。"
            "你记录的不是娃，是你不服输的劲儿，姐妹们都能看见。"
            "搞钱不丢人，给娃兜底的能力才是真的体面。"
            "慢慢来，咱们一起在柴米油盐里，活出自己的底气。"
            "你先是你自己，才是妈妈，先站稳，才扛得动家。"
        ),
        "title": "当妈后，我活成了自己的屋檐",
    }


def fallback_ai(hot):
    log("使用兜底内容（AI 不可用）")
    titles = [it.get("title", "") for v in hot.values() for it in v if it.get("title")]
    fb = titles[0] if titles else "今天也要加油呀"

    def topic(i):
        return {
            "title": f"当妈后我才懂的事（{i+1}）",
            "tag": "#宝妈逆袭 #带娃搞钱",
            "desc": "把带娃的日常变成内容资产，从一个小分享开始，慢慢攒属于宝妈的金钱与底气。那些看似平凡的间隙，其实都在悄悄帮你沉淀流量。",
            "platform": random.choice(["douyin", "bili", "xhs"]),
            "type": random.choice(["情感共鸣", "成长记录"]),
        }

    def remix(i):
        return {
            "hot": fb,
            "type": "热点",
            "angle": "用宝妈视角切入，讲自己带娃时的同类经历。把热点放进真实生活里，让观众觉得说的就是自己。",
            "copywriting": "真实 + 共鸣 + 金句密集，是它破圈的关键。宝妈赛道最吃的就是『被说中』的获得感。",
            "imitate": "最近大家都在聊__，我当妈后也深有体会：____ | 谁懂啊？__这件事，真的只有宝妈才懂。",
        }

    return {
        "topic_inspirations": pad([], 10, topic),
        "remix_angles": pad([], 10, remix),
        "image_copywriting": pad([], 10, img_factory),
        "english": {
            "words": [
                {"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "你好", "example": "Hello, I am a mom."},
                {"word": "family", "phonetic": "/ˈfæməli/", "meaning": "家庭", "example": "I love my family."},
                {"word": "baby", "phonetic": "/ˈbeɪbi/", "meaning": "宝贝", "example": "My baby is cute."},
                {"word": "happy", "phonetic": "/ˈhæpi/", "meaning": "开心", "example": "I am happy today."},
                {"word": "learn", "phonetic": "/lɜːrn/", "meaning": "学习", "example": "I learn English."},
            ],
            "grammar": "主谓宾：我(I) 爱(love) 宝贝(baby)。",
            "shadow": "I am a happy mom and I love my baby.",
        },
    }


# ---------------- 4. 速算练习 ----------------
def gen_math_local(n=20):
    problems = []
    for _ in range(n):
        t = random.choice(["+", "-", "*"])
        if t == "+":
            a, b = random.randint(10, 99), random.randint(10, 99)
            ans = a + b
        elif t == "-":
            a, b = random.randint(20, 99), random.randint(10, 99)
            a, b = max(a, b), min(a, b)
            ans = a - b
        else:
            a, b = random.randint(2, 12), random.randint(2, 9)
            ans = a * b
        problems.append({"q": f"{a} {t} {b} = ?", "a": ans})
    return problems


def fetch_math_from_wx():
    """若配置了微信公众号接口则尝试抓取，失败返回 None（由调用方回退本地生成）。"""
    if not WX_ALBUM_URL:
        return None
    try:
        d = http_json(WX_ALBUM_URL, timeout=20)
        raw = d.get("problems") or d.get("data") or d.get("list") or d
        problems = []
        for it in raw:
            if isinstance(it, dict) and it.get("q"):
                problems.append({"q": str(it["q"]), "a": it.get("a")})
        if problems:
            log(f"微信公众号取到 {len(problems)} 道速算题")
            return problems[:30]
    except Exception as e:
        log(f"微信公众号抓取失败，回退本地: {e}")
    return None


# ---------------- 5. 推送 Gist ----------------
def push_gist(content):
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = {
        "files": {
            "mama-daily.json": {
                "content": json.dumps(content, ensure_ascii=False, indent=2)
            }
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {MAMA_PAT}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d.get("html_url")


# ---------------- 主流程 ----------------
def main():
    if not (AI_API_KEY and MAMA_PAT and GIST_ID):
        log("缺少必要环境变量（AI_API_KEY / MAMA_PAT / GIST_ID），退出。")
        raise SystemExit(1)

    log("开始抓取热搜")
    hot = fetch_hotlists()

    # 读取用户维护的『真实文案来源库』
    sources = load_sources()
    if sources:
        n = sum(len(v) for v in sources.values() if isinstance(v, list))
        log(f"已加载文案来源库：共 {n} 条")

    log("调用 DeepSeek 生成内容")
    ai = None
    try:
        raw = chat(SYSTEM, build_user_prompt(hot, sources=sources))
        ai = extract_json(raw)
        log("AI 返回解析成功")
    except Exception as e:
        log(f"AI 首次调用/解析失败: {e}，尝试重试一次")
        try:
            raw = chat(SYSTEM, build_user_prompt(hot, sources=sources), temperature=0.3)
            ai = extract_json(raw)
            log("AI 重试解析成功")
        except Exception as e2:
            log(f"AI 重试仍失败: {e2}，使用兜底内容")
            ai = fallback_ai(hot)

    topic = pad(ai.get("topic_inspirations", []), 10,
                lambda i: {"title": f"当妈后我才懂的事（{i+1}）", "tag": "#宝妈逆袭",
                           "desc": "把带娃的日常变成内容资产。那些看似平凡的间隙，其实都在悄悄帮你沉淀流量。",
                           "platform": "douyin", "type": "情感共鸣"})
    remix = pad(ai.get("remix_angles", []), 10,
                lambda i: {"hot": "今日热点", "type": "热点", "angle": "用宝妈视角切入，把热点放进真实生活里。",
                           "copywriting": "真实 + 共鸣 + 金句密集，是它破圈的关键。",
                           "imitate": "最近大家都在聊__，我当妈后也深有体会：____ | 谁懂啊？__这件事，真的只有宝妈才懂。"})
    img = pad(ai.get("image_copywriting", []), 10, img_factory)
    # 字数/句数强制合规
    img = enforce_hooks(img)                          # hook 12-15 字
    img = enforce_sents(img, "quote", 2, 3, QUOTE_POOL)   # 原句 2-3 句（真实；含惨词整句替换为干净书摘）
    img = enforce_sents(img, "reflection", 1, 2, SENT_POOL["reflection"])  # 感悟 1-2 句
    img = enforce_sents(img, "body_long", 10, 10, SENT_POOL["body_long"])    # 长版 10 句
    img = enforce_sents(img, "body_short", 5, 6, SENT_POOL["body_short"])  # 短版 5-6 句
    # 收入造假词兜底（用户尚未通过自媒体赚到一分钱）
    for x in img:
        for _f in ("quote", "reflection", "body_long", "body_short", "title", "hook"):
            x[_f] = clean_money(x.get(_f, ""))
    # clean_money 可能改变字数，重新把钩子收口到 12-15 字
    img = enforce_hooks(img)
    # 先清洗标题里的惨词，再组装图上正文，避免惨词漏进 img_text
    for x in img:
        x["title"] = clean_sad_inline(x.get("title", ""))
    img = enforce_text(img, "title", 8, 16, pad=False)   # 标题不补写，保留短钩子；仅过长才截断
    img = enforce_img_text(img)              # 组装图上正文，≤10句，每句12-16字，连贯一段
    # 双保险：图上正文再过一遍惨词内联清洗
    for x in img:
        x["img_text"] = clean_sad_inline(x.get("img_text", ""))
    img = enforce_text(img, "title", 8, 16, pad=False)   # 标题不补写，保留短钩子（双保险，幂等）

    remix = enforce_text(remix, "angle", 60, 120)
    remix = enforce_text(remix, "copywriting", 40, 80)

    topic = enforce_text(topic, "title", 16, 24)
    topic = enforce_text(topic, "desc", 80, 140)

    eng = ai.get("english", {})
    if not eng.get("words"):
        eng["words"] = [{"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "你好", "example": "Hello."}]
    if not eng.get("grammar"):
        eng["grammar"] = "主谓宾：我(I) 爱(love) 宝贝(baby)。"
    if not eng.get("shadow"):
        eng["shadow"] = "I am a happy mom and I love my baby."

    math = fetch_math_from_wx() or gen_math_local(20)

    out = {
        "date": datetime.date.today().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": "GitHub Gist (自动生成)",
        "hotlists": hot,
        "topic_inspirations": topic,
        "remix_angles": remix,
        "image_copywriting": img,
        "english": eng,
        "mental_math": math,
    }

    try:
        with open("last_run.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    if GIST_ID == "PREVIEW_NO_PUSH":
        log("预览模式：仅生成本地 last_run.json，不推送 Gist。")    
    else:
        url = push_gist(out)
        log("Gist 已更新 ->", url)

    log(f"产出统计: 灵感 {len(topic)} / 二创 {len(remix)} / 图片文案 {len(img)} / 速算 {len(math)} / 单词 {len(eng['words'])}")
    bad_hook = [i for i, x in enumerate(img) if not (12 <= cn_len(x.get("hook", "")) <= 15)]
    log("钩子字数: " + " / ".join(f"{i+1}.{cn_len(x['hook'])}" for i, x in enumerate(img)))
    log(f"钩子合规 {len(img)-len(bad_hook)}/{len(img)}" + (f"，需关注 {bad_hook}" if bad_hook else "，全部达标"))

    # 打印图片文案关键字段句数概况
    for field, label, lo, hi in [
        ("quote", "原句摘抄(图上)", 1, 3),
        ("reflection", "个人感悟(图上)", 1, 2),
        ("body_long", "长版正文", 10, 10),
        ("body_short", "短版正文", 5, 6),
        ("img_text", "图上正文句数", 1, 10),
    ]:
        if field == "img_text":
            bad = [i for i, x in enumerate(img) if not (lo <= len(cn_sents(x.get(field, ""))) <= hi)]
        else:
            bad = [i for i, x in enumerate(img) if not (lo <= len(cn_sents(x.get(field, ""))) <= hi)]
        log(f"{label}: 合规 {len(img)-len(bad)}/{len(img)}" + (f"，需关注 {bad}" if bad else "，全部达标"))
    # 图上正文新增约束：每句 12-16 字
    total_lines = sum(len([s for s in x.get("img_text", "").split("\n") if s.strip()]) for x in img)
    bad_sents = []
    for i, x in enumerate(img):
        lines = [s for s in x.get("img_text", "").split("\n") if s.strip()]
        for j, st in enumerate(lines):
            if j == 0:
                ok = 8 <= cn_len(st) <= 16     # 首行=标题/钩子，可更短促
            else:
                ok = 11 <= cn_len(st) <= 22   # 正文行（原句+感悟），整句金句可到21-22
            if not ok:
                bad_sents.append((i+1, j+1, cn_len(st)))
    log(f"图上正文字数(首行标题8-16、正文行11-22、整句金句可到21-22): 合规 {total_lines-len(bad_sents)}/{total_lines}" + (f"，需关注 {bad_sents}" if bad_sents else "，全部达标"))


if __name__ == "__main__":
    main()
