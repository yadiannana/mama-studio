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
    "非常熟悉抖音 / 小红书 / B站 5000-10000 粉丝量级的宝妈类账号写法。"
    "你擅长把全网热点改写成宝妈视角的选题、二创角度与图片文案。"
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
      "title": "标题，15 字以内，带钩子感",
      "tag": "标签，如 #宝妈逆袭 #带娃搞钱 #婚姻真相",
      "desc": "说明，关联宝妈勇闯自媒体的真实痛点或爽点，40-80 字",
      "platform": "douyin 或 bili 或 xhs（该选题最合适的主推平台）"
    }}
  ],
  "remix_angles": [   // 10 条：爆款热点 / 新闻 / 歌曲 / 明星发言 的二创
    {{
      "hot": "挑选的热点原文 / 标题",
      "type": "热点 或 新闻 或 歌曲 或 明星发言",
      "angle": "改编角度：如何与宝妈自媒体关联、能怎么拍",
      "copywriting": "学习爆火文案：拆解它为什么火（1-2 句）",
      "imitate": "深度模仿：可直接套用的文案框架 / 开头句式"
    }}
  ],
  "image_copywriting": [   // 10 条：用于图片上的文字（重点！）
    {{
      "hook": "第一句 12-15 字（含标点），要有钩子（悬念 / 反差 / 身份认同），像真人宝妈主播：用身份(我是个宝妈)、反差、悬念、数字。示例：'当妈后我才敢说出口的真心话'",
      "quote": "金句 = 原文：直接给出可引用的真实原句（热点原话、歌词、名言或网友神评），一句即可，不要加 '原文：' 等前缀，必须是真实可引用的，不要自己编",
      "reflection": "最后写几句感悟，宝妈视角，30-60 字",
      "title": "图片下方延续性标题，15 字以内",
      "body": "图片下方延续性正文，关联宝妈勇闯自媒体，40-80 字"
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

写作要求：
1. 全部内容紧扣「宝妈勇闯自媒体」赛道，让普通妈妈有共鸣、想点击、想转发。
2. image_copywriting 的 hook 要有钩子，尽量写到 12-15 字（含标点）；像真人宝妈主播口播：多用身份认同、反差、悬念、数字。
3. image_copywriting 的 quote 字段直接给原文句子，不要带 '原文：' 前缀；必须是真实可引用的原话。
4. 选题与二创要覆盖抖音 / 微博 / 知乎 / 头条 / 新闻，并尽量关联宝妈生活：带娃、搞钱、婚姻、自我成长、婆媳、职场回归等。
5. 只输出 JSON 对象。"""


def chat(system, user, temperature=0.7):
    url = AI_BASE_URL + "/chat/completions"
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 7000,
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


# ---------------- 钩子字数强制合规（程序化兜底，保证 12-15 字）----------------
FILLERS = [
    "，你们也这样吗", "，我才终于明白", "，这件事戳中我", "，当妈后才懂的",
    "，原来不只我一个", "，说出来不丢人", "，宝妈都懂的痛", "，我憋了好久",
    "，真的不是矫情", "，你中了几条",
]


def _clean(s):
    return re.sub(r"\s", "", s or "")


def enforce_hook(hook, idx):
    s = _clean(hook)
    if 12 <= len(s) <= 15:
        return hook
    if len(s) < 12:
        base = re.sub(r"[，。！？、\s]+$", "", hook)
        for k in range(len(FILLERS)):
            suf = FILLERS[(idx + k) % len(FILLERS)]
            if 12 <= len(s) + len(_clean(suf)) <= 15:
                return base + suf
        # 兜底
        return _clean(hook + FILLERS[idx % len(FILLERS)])[:15]
    # 超过 15 字：保留更有力的尾部
    return s[-15:]


def enforce_hooks(items):
    for i, x in enumerate(items):
        x["hook"] = enforce_hook(x.get("hook", ""), i)
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
            "desc": "把带娃的日常变成内容资产，从一个小分享开始，慢慢积累属于妈妈的舞台。",
            "platform": random.choice(["douyin", "bili", "xhs"]),
        }

    def remix(i):
        return {
            "hot": fb,
            "type": "热点",
            "angle": "用宝妈视角切入，讲自己带娃时的同类经历。",
            "copywriting": "真实 + 情绪共鸣最容易火。",
            "imitate": "最近大家都聊__，我当妈后也深有体会……",
        }

    def img(i):
        return {
            "hook": "带娃第三年我终于敢说这话",
            "quote": fb,
            "reflection": "生活很碎，但每一步都算数，妈妈也可以闪闪发光。",
            "title": "普通妈妈的自媒体日记",
            "body": "别小看每天的记录，坚持下去，你会谢谢现在开始的自己。",
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
        log(f"AI 调用/解析失败: {e}")
        ai = fallback_ai(hot)

    topic = pad(ai.get("topic_inspirations", []), 10,
                 lambda i: {"title": f"当妈后我才懂的事（{i+1}）", "tag": "#宝妈逆袭",
                            "desc": "把带娃日常变成内容资产。", "platform": "douyin"})
    remix = pad(ai.get("remix_angles", []), 10,
                lambda i: {"hot": "今日热点", "type": "热点", "angle": "宝妈视角切入",
                           "copywriting": "真实 + 共鸣最易火。", "imitate": "最近大家聊__，我当妈后也深有体会……"})
    img = pad(ai.get("image_copywriting", []), 10,
              lambda i: {"hook": "带娃第三年我终于敢说这话", "quote": "今天也要加油",
                         "reflection": "妈妈也可以闪闪发光。", "title": "妈妈的自媒体日记",
                         "body": "坚持记录，你会谢谢现在开开始的自己。"})
    # 钩子字数强制合规（保证 12-15 字）
    img = enforce_hooks(img)

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
    bad = [i for i, x in enumerate(img) if not (12 <= cn_len(x.get("hook", "")) <= 15)]
    log("钩子字数: " + " / ".join(f"{i+1}.{cn_len(x['hook'])}" for i, x in enumerate(img)))
    log(f"钩子合格 {len(img)-len(bad)}/{len(img)}" + (f"，需关注 {bad}" if bad else "，全部达标"))


if __name__ == "__main__":
    main()
