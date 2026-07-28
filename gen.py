#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宝妈勇闯自媒体 - 每日创作内容生成器
- 抓取抖音/微博/知乎/头条/60s 热榜
- 调用 DeepSeek 改写 -> 10 选题灵感 + 10 二创角度 + 10 图片文案 + 英语(单词/语法/跟读)
- 本地生成速算练习题
- 推送至公开 GitHub Gist（网页默认读取）

环境变量（建议在 GitHub Secrets 配置）：
  AI_API_KEY    DeepSeek 密钥
  AI_BASE_URL   https://api.deepseek.com/v1
  AI_MODEL      deepseek-chat
  MAMA_PAT      具有 gist 权限的 GitHub 个人令牌
  GIST_ID       目标 Gist 的 ID
  WX_ALBUM_URL  可选：微信专辑/文章列表接口（留空则本地生成速算题）
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


# ---------------- 1. 抓取热榜 ----------------
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
            log(f"热榜[{name}] 取到 {len(out[name])} 条")
        except Exception as e:
            out[name] = []
            log(f"热榜[{name}] 失败: {e}")
    return out


# ---------------- 2. 调用大模型 ----------------
SYSTEM = (
    "你是一位深耕「宝妈勇闯自媒体」赛道的爆款内容策划与文案高手，"
    "非常熟悉抖音上 5000-50000 粉丝量级的宝妈类账号写法，尤其是类似 ayanddq、88007612422 这类账号："
    "擅长把明星发言、热门歌曲、社会热点改写成宝妈视角的金句图文；"
    "文案要有『通透感』『金句感』『情绪共鸣』，像一位真诚、有阅历的宝妈在跟朋友掏心窝子；"
    "善用排比、反问、对比，敢于谈钱、谈低谷、谈坚持、谈自我成长；"
    "你必须且只能输出一个 JSON 对象，不要任何解释、不要 markdown 代码块、不要多余文字。"
)


def build_user_prompt(hot):
    titles = []
    for name, items in hot.items():
        for it in items:
            t = it.get("title", "").strip()
            if t:
                titles.append(t)
    titles = titles[:90]
    titles_text = "\n".join(f"- {t}" for t in titles)

    return f"""今天是 {datetime.date.today().isoformat()}。以下是今日热榜 / 新闻（来源：抖音、微博、知乎、头条、60s 早报）：

{titles_text}

请基于以上热点，产出一份 JSON，结构必须如下（数组长度务必准确，不得省略）：

{{
  "topic_inspirations": [   // 10 条：宝妈勇闯自媒体-每日灵感 / 人生感悟
    {{
      "title": "标题，16-24 字（含标点），带钩子感，像爆款封面标题",
      "tag": "标签，如 #宝妈逆袭 #带娃搞钱 #婚姻真相 #女性成长",
      "desc": "说明，关联宝妈勇闯自媒体的真实痛点或爽点，80-140 字，有细节、有共鸣",
      "platform": "douyin 或 bili 或 xhs（该选题最合适的主推平台）",
      "type": "热点二创 / 搞钱结果 / 情绪共鸣 / 成长记录（四选一，必须准确）"
    }}
  ],
  "remix_angles": [   // 10 条：爆款热点 / 新闻 / 歌曲 / 明星发言 的二创
    {{
      "hot": "挑选的热点原文 / 标题 / 明星发言 / 歌词，必须真实可引用",
      "type": "热点 或 新闻 或 歌曲 或 明星发言",
      "angle": "改编角度：如何与宝妈自媒体关联、能怎么拍，60-120 字，具体可操作",
      "copywriting": "学习爆火文案：拆解它为什么火、用了什么情绪/结构/金句，40-80 字",
      "imitate": "深度模仿：给出 2-3 个可直接套用的开头句式 / 文案框架，用 | 分隔"
    }}
  ],
  "image_copywriting": [   // 10 条：用于图片上的文字（重点！）
    {{
      "hook": "第一句 14-20 字（含标点），大标题钩子。风格参考：'原来当妈后，人真的会脱胎换骨' / '谁懂啊？我的娃靠自己赚到了钱' / '稀里糊涂挣到钱，真的太意外了' / '真正厉害的人，都跳过情绪行动'。用身份认同、反差、悬念、数字、热点名",
      "hot_source": "这条文案借用的热点/明星/歌曲/名言来源，10-25 字，如'周星驰《功夫女足》'、'杨紫获奖感言'、'孙颖莎夺冠发言'、'热门歌曲《吹吹山顶的风》'",
      "quote": "金句 = 原文：直接给出可引用的真实原句（热点原话、歌词、名言或网友神评），15-40 字，不要加 '原文：' 前缀，必须真实",
      "interpretation": "宝妈视角的深度解读，4-8 行短句，80-150 字。要求：像真人宝妈口播，用排比/反问/对比，写出通透感；要敢于谈钱、谈低谷、谈坚持、谈自我成长；每行 10-20 字，整体有节奏感",
      "reflection": "感悟，40-80 字，扎心、有共鸣，让普通妈妈觉得'被说中了'",
      "cta": "行动号召，10-20 字，如'去拍吧，下一个火的就是你' / '坚持下去，天亮后会很美' / '别小看自己，你也值得被看见'",
      "title": "图片下方延续性标题，15-20 字，带钩子",
      "body": "图片下方延续性正文，关联宝妈勇闯自媒体，60-120 字，有金句、有洞察"
    }}
  ],
  "english": {{
    "words": [
      {{"word": "简单高频词(英文)", "phonetic": "音标", "meaning": "中文释义", "example": "英文例句"}}
    ],   // 5 个，面向成年人零基础，最简单高频
    "grammar": "一条最基础语法（如 主谓宾 / be 动词 / 人称代词），30 字以内",
    "shadow": "一句适合影子跟读的极简单句，8-12 个词，生活化"
  }}
}}

写作要求（重点）：
1. 全部内容紧扣「宝妈勇闯自媒体」赛道，让普通妈妈有共鸣、想点击、想转发。
2. image_copywriting 要模仿目标账号风格：顶部大标题抓眼，中间金句+通透解读，底部感悟+行动号召；整体像一位真实宝妈在分享心得。
3. image_copywriting 的 hook 尽量写到 14-20 字（含标点），可借助热点名/数字/反问/反差制造钩子。
4. image_copywriting 的 quote 字段直接给原文句子，不要带 '原文：' 前缀；必须是真实可引用的原话。
5. image_copywriting 的 interpretation 要多用短句、排比、反问，写出『通透感』和『扎心感』，拒绝鸡汤空话。
6. topic_inspirations 的 type 必须准确四选一，desc 要有具体场景或细节，不要泛泛而谈。
7. remix_angles 的 imitate 要给出真正能直接套用的 2-3 个开头句式，用 | 分隔。
8. 所有字段值必须是合法 JSON 字符串；如果需要换行（如 interpretation 的多行解读），请使用 \\n 转义，不要输出真实换行符。
9. 不要省略任何字段，不要输出 markdown 代码块，只输出 JSON 对象。"""


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
    """字数统计：去掉空白后按字符计（含标点，与中文'字数'口径一致）。"""
    return len(re.sub(r"\s", "", s or ""))


# ---------------- 钩子字数强制合规（程序化兜底，保证 14-20 字）----------------
FILLERS = [
    "，你中了几条",          # 6
    "，你们也这样吗",        # 7
    "，原来大家都一样",      # 8
    "，我才终于明白了",      # 8
    "，当妈后才懂的痛",      # 8
    "，这件事戳中我了",      # 8
    "，说出来也不丢人",      # 8
    "，我憋在心里好久",      # 8
    "，真的不是在矫情",      # 8
    "，只有当过妈的才懂",    # 9
]


def _clean(s):
    return re.sub(r"\s", "", s or "")


def enforce_hook(hook, idx):
    s = _clean(hook)
    if 14 <= len(s) <= 20:
        return hook
    if len(s) < 14:
        base = re.sub(r"[，。！？、\s]+$", "", hook)
        for k in range(len(FILLERS)):
            suf = FILLERS[(idx + k) % len(FILLERS)]
            if 14 <= len(s) + len(_clean(suf)) <= 20:
                return base + suf
        # 兜底
        return _clean(hook + FILLERS[idx % len(FILLERS)])[:20]
    # 超过 20 字：保留更有力的尾部
    return s[-20:]


def enforce_hooks(items):
    for i, x in enumerate(items):
        x["hook"] = enforce_hook(x.get("hook", ""), i)
    return items


# ---------------- 通用字数兜底 ----------------
TAIL_POOL = {
    "interpretation": [
        "。别小看每天的记录，妈妈的光芒，从来不会被柴米油盐埋没。",
        "。带娃的日子很忙，但只要你还在拍，就有人在默默共鸣。",
        "。普通人最大的武器，就是不肯轻易认输的那口气。",
    ],
    "reflection": [
        "。所以别怕慢，只要还在走，就一定会有回响。",
        "。我们不需要活成别人眼里的完美，只需要活成自己心里的不后悔。",
        "。你现在的坚持，正在悄悄改写以后的故事。",
    ],
    "body": [
        "。你只管出发，答案在路上，平凡妈妈也能活成自己的光。",
        "。别等准备好了才开始，先开始，才会慢慢准备好。",
        "。每天进步一点点，积累起来就是别人追不上的距离。",
    ],
    "title": ["，致每一个不放弃的妈妈", "，写给还在咬牙坚持的你", "，当妈后才懂的真谛"],
    "cta": ["，现在就出发", "，去拍吧，别等了", "，你也可以闪闪发光"],
    "copywriting": [
        "。情绪真实、共鸣强烈、金句密集，是它破圈的关键。",
        "。它用宝妈视角把热点翻译成了生活，让人一看就觉得'说中我了'。",
    ],
    "angle": [
        "。把热点放进宝妈的真实生活里，让观众觉得说的就是自己。",
        "。用具体场景引发共鸣，比空喊口号更容易获得流量。",
    ],
    "desc": [
        "。这个选题没有门槛，普通妈妈照着拍，也能拿到属于自己的流量。",
        "。当你把它和真实生活挂钩时，评论区会自动长出共鸣。",
        "。不需要华丽场景，真诚和真实就是这个赛道最大的流量密码。",
    ],
}


def enforce_text(items, field, min_len, max_len):
    pool = TAIL_POOL.get(field, ["。坚持下去，时间会给你答案。"])
    for x in items:
        s = x.get(field, "")
        L = cn_len(s)
        # 太短：从池子里循环追加，直到达标或耗尽
        tries = 0
        while L < min_len and tries < len(pool):
            s = s + pool[tries % len(pool)]
            L = cn_len(s)
            tries += 1
        # 太长：截断并尽量保持句尾完整
        if L > max_len:
            cleaned = _clean(s)
            trunc = cleaned[:max_len]
            for p in ["，", "。", "！", "？", "；", "、", " "]:
                idx = trunc.rfind(p)
                if idx >= max_len * 0.6:
                    trunc = trunc[:idx + 1]
                    break
            s = trunc
            L = cn_len(s)
        # 若耗尽仍短，用最长兜底再补一次（然后必要时截断）
        if L < min_len:
            s = s + pool[-1]
            if cn_len(s) > max_len:
                s = _clean(s)[:max_len]
        x[field] = s
    return items


# ---------------- 3. 兜底与补齐 ----------------
def pad(arr, n, factory):
    arr = list(arr or [])
    while len(arr) < n:
        arr.append(factory(len(arr)))
    return arr[:n]


def fallback_ai(hot):
    log("使用兜底内容（AI 不可用）")
    titles = [it.get("title", "") for v in hot.values() for it in v if it.get("title")]
    fb = titles[0] if titles else "今天也要加油呀"

    def topic(i):
        return {
            "title": f"当妈后我才懂的事（{i+1}）",
            "tag": "#宝妈逆袭 #带娃搞钱",
            "desc": "把带娃的日常变成内容资产，从一个小分享开始，慢慢积累属于妈妈的舞台。那些看似平凡的瞬间，其实都在悄悄帮你沉淀流量。",
            "platform": random.choice(["douyin", "bili", "xhs"]),
            "type": random.choice(["情绪共鸣", "成长记录"]),
        }

    def remix(i):
        return {
            "hot": fb,
            "type": "热点",
            "angle": "用宝妈视角切入，讲自己带娃时的同类经历。把热点放进真实生活里，让观众觉得说的就是自己。",
            "copywriting": "真实 + 情绪共鸣 + 金句密集，是它破圈的关键。宝妈赛道最吃的就是'被说中'的感觉。",
            "imitate": "最近大家都聊__，我当妈后也深有体会…… | 谁懂啊？__这件事，真的只有宝妈才懂。",
        }

    def img(i):
        return {
            "hook": "原来当妈后，人真的会脱胎换骨",
            "hot_source": fb or "今日热榜",
            "quote": "人生没有无用的经历，所以一直走，天一定亮。",
            "interpretation": "带娃的日子很碎，\n但每一步都算数。\n你可能觉得自己没进步，\n其实你在学习耐心、学习取舍、学习在混乱中找秩序。\n这些能力，终会反哺你的内容。\n别怕慢，只要还在走。",
            "reflection": "生活很碎，但每一步都算数，妈妈也可以闪闪发光。",
            "cta": "去记录吧，你的故事也值得被看见",
            "title": "普通妈妈的自媒体日记",
            "body": "别小看每天的记录，坚持下去，你会谢谢现在开始的自己。那些无人问津的日子，都是在为未来的爆发蓄力。",
        }

    return {
        "topic_inspirations": pad([], 10, topic),
        "remix_angles": pad([], 10, remix),
        "image_copywriting": pad([], 10, img),
        "english": {
            "words": [
                {"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "你好", "example": "Hello, I am a mom."},
                {"word": "family", "phonetic": "/ˈfæməli/", "meaning": "家庭", "example": "I love my family."},
                {"word": "baby", "phonetic": "/ˈbeɪbi/", "meaning": "宝宝", "example": "My baby is cute."},
                {"word": "happy", "phonetic": "/ˈhæpi/", "meaning": "开心", "example": "I am happy today."},
                {"word": "learn", "phonetic": "/lɜːrn/", "meaning": "学习", "example": "I learn English."},
            ],
            "grammar": "主谓宾：我(I) 爱(love) 宝宝(baby)。",
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
    """若配置了微信专辑接口则尝试抓取，失败返回 None（由调用方回退本地生成）。"""
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
            log(f"微信专辑取到 {len(problems)} 道速算题")
            return problems[:30]
    except Exception as e:
        log(f"微信专辑抓取失败，回退本地: {e}")
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

    log("开始抓取热榜")
    hot = fetch_hotlists()

    log("调用 DeepSeek 生成内容")
    ai = None
    try:
        raw = chat(SYSTEM, build_user_prompt(hot))
        ai = extract_json(raw)
        log("AI 返回解析成功")
    except Exception as e:
        log(f"AI 首次调用/解析失败: {e}，尝试重试一次")
        try:
            raw = chat(SYSTEM, build_user_prompt(hot), temperature=0.3)
            ai = extract_json(raw)
            log("AI 重试解析成功")
        except Exception as e2:
            log(f"AI 重试仍失败: {e2}，使用兜底内容")
            ai = fallback_ai(hot)

    topic = pad(ai.get("topic_inspirations", []), 10,
                 lambda i: {"title": f"当妈后我才懂的事（{i+1}）", "tag": "#宝妈逆袭",
                            "desc": "把带娃日常变成内容资产。那些看似平凡的瞬间，其实都在悄悄帮你沉淀流量。",
                            "platform": "douyin", "type": "情绪共鸣"})
    remix = pad(ai.get("remix_angles", []), 10,
                lambda i: {"hot": "今日热点", "type": "热点", "angle": "用宝妈视角切入，把热点放进真实生活里。",
                           "copywriting": "真实 + 共鸣 + 金句密集，是它破圈的关键。",
                           "imitate": "最近大家都聊__，我当妈后也深有体会…… | 谁懂啊？__这件事，真的只有宝妈才懂。"})
    img = pad(ai.get("image_copywriting", []), 10,
              lambda i: {"hook": "原来当妈后，人真的会脱胎换骨", "hot_source": "今日热榜",
                         "quote": "人生没有无用的经历，所以一直走，天一定亮。",
                         "interpretation": "带娃的日子很碎，\n但每一步都算数。\n你可能觉得自己没进步，\n其实你在学习耐心、学习取舍。\n别怕慢，只要还在走。",
                         "reflection": "生活很碎，但每一步都算数，妈妈也可以闪闪发光。",
                         "cta": "去记录吧，你的故事也值得被看见",
                         "title": "普通妈妈的自媒体日记",
                         "body": "别小看每天的记录，坚持下去，你会谢谢现在开始的自己。"})

    # 字数强制合规
    img = enforce_hooks(img)
    img = enforce_text(img, "interpretation", 80, 150)
    img = enforce_text(img, "reflection", 40, 80)
    img = enforce_text(img, "cta", 10, 20)
    img = enforce_text(img, "title", 10, 20)
    img = enforce_text(img, "body", 60, 120)

    remix = enforce_text(remix, "angle", 60, 120)
    remix = enforce_text(remix, "copywriting", 40, 80)

    topic = enforce_text(topic, "title", 16, 24)
    topic = enforce_text(topic, "desc", 80, 140)

    eng = ai.get("english", {})
    if not eng.get("words"):
        eng["words"] = [{"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "你好", "example": "Hello."}]
    if not eng.get("grammar"):
        eng["grammar"] = "主谓宾：我(I) 爱(love) 宝宝(baby)。"
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

    url = push_gist(out)
    log("Gist 已更新 ->", url)
    log(f"产出统计: 灵感 {len(topic)} / 二创 {len(remix)} / 图片文案 {len(img)} / 速算 {len(math)} / 单词 {len(eng['words'])}")
    bad_hook = [i for i, x in enumerate(img) if not (14 <= cn_len(x.get("hook", "")) <= 20)]
    log("钩子字数: " + " / ".join(f"{i+1}.{cn_len(x['hook'])}" for i, x in enumerate(img)))
    log(f"钩子合格 {len(img)-len(bad_hook)}/{len(img)}" + (f"，需关注 {bad_hook}" if bad_hook else "，全部达标"))

    # 打印关键字段字数概览
    for field, label, lo, hi in [
        ("interpretation", "图片解读", 80, 150),
        ("reflection", "图片感悟", 40, 80),
        ("body", "图片正文", 60, 120),
        ("desc", "选题说明", 80, 140),
        ("angle", "二创角度", 60, 120),
    ]:
        arr = img if field in ("interpretation", "reflection", "body") else (remix if field in ("angle",) else topic)
        bad = [i for i, x in enumerate(arr) if not (lo <= cn_len(x.get(field, "")) <= hi)]
        log(f"{label}: 合格 {len(arr)-len(bad)}/{len(arr)}" + (f"，需关注 {bad}" if bad else ""))


if __name__ == "__main__":
    main()
