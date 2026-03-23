import requests
import time
import json
import math
import subprocess
import random
import base64
import sys
import os
from datetime import datetime
from openai import OpenAI
from lunardate import LunarDate

# 获取当前Python解释器路径和脚本所在目录（兼容Docker环境）
PYTHON = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ========== 配置 ==========
from config import *

POLL_INTERVAL = 20

# 生成随机触发时间（每天自动重置）
SCHEDULE_FILE = "data/schedule_today.json"

def generate_daily_schedule():
    """生成今天的随机触发时间"""
    from config import get_raw_config
    cfg = get_raw_config()
    n_times = cfg.get("PROACTIVE_TIMES_COUNT", 2)
    times = sorted(random.sample(range(10, 23), min(n_times, 12)))
    times = [(h, random.randint(0, 59)) for h in times]
    dynamic = (random.randint(10, 21), random.randint(0, 59))
    schedule = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proactive_times": [f"{h}:{m:02d}" for h, m in times],
        "dynamic_time": f"{dynamic[0]}:{dynamic[1]:02d}",
        "proactive_triggered": [],
        "dynamic_triggered": False,
    }
    # 保存到文件，前端可以读取
    os.makedirs("data", exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    return times, set(), dynamic, False

def load_or_generate_schedule():
    """加载今天的计划，如果是新的一天则重新生成"""
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            schedule = json.load(f)
        if schedule.get("date") == datetime.now().strftime("%Y-%m-%d"):
            # 今天的计划还在，恢复状态
            times = []
            for t in schedule.get("proactive_times", []):
                h, m = t.split(":")
                times.append((int(h), int(m)))
            triggered = set(schedule.get("proactive_triggered", []))
            dh, dm = schedule.get("dynamic_time", "15:00").split(":")
            dynamic = (int(dh), int(dm))
            dynamic_done = schedule.get("dynamic_triggered", False)
            return times, triggered, dynamic, dynamic_done
    except:
        pass
    return generate_daily_schedule()

proactive_times, proactive_triggered, dynamic_time, dynamic_triggered = load_or_generate_schedule()

def save_schedule_state():
    """保存当前触发状态到文件"""
    schedule = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proactive_times": [f"{h}:{m:02d}" for h, m in proactive_times],
        "dynamic_time": f"{dynamic_time[0]}:{dynamic_time[1]:02d}",
        "proactive_triggered": list(proactive_triggered),
        "dynamic_triggered": dynamic_triggered,
    }
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
    except:
        pass

MAX_REPLIES_PER_RUN = 3
REPLIED_FILE = "data/replied.json"
AFFECTION_FILE = "data/affection.json"
MEMORY_FILE = "data/memory.json"
SECURITY_LOG_FILE = "data/security_log.json"
PERMANENT_MEMORY_FILE = "data/permanent_memory.json"
COST_LOG_FILE = "data/cost_log.json"
MOOD_FILE = "data/mood.json"
VIDEO_MEMORY_FILE = "data/video_memory.json"
USER_PROFILE_FILE = "data/user_profiles.json"
PERSONALITY_FILE = "data/personality_evolution.json"

# 关键词过滤
BLOCK_KEYWORDS = ["傻逼", "草泥马", "滚", "死", "废物", "智障", "脑残"]

# 记忆参数
THREAD_COMPRESS_THRESHOLD = 8
MAX_SEMANTIC_RESULTS = 3
USER_MEMORY_COMPRESS_THRESHOLD = 20
USER_MEMORY_KEEP_RECENT = 5
# ================================

headers = {
    "Cookie": f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com"
}

or_client = OpenAI(
    api_key=OR_API_KEY,
    base_url=OR_BASE_URL
)

embed_client = OpenAI(
    api_key=SILICON_API_KEY,
    base_url="https://api.siliconflow.cn/v1"
)

def _get_bot_info():
    """从config读取bot和主人信息"""
    from config import get_raw_config
    cfg = get_raw_config()
    return {
        "bot_name": cfg.get("BOT_NAME", "Bot"),
        "owner_name": cfg.get("OWNER_NAME", "") or "主人",
        "owner_bili": cfg.get("OWNER_BILI_NAME", ""),
    }

def _get_active_persona():
    """读取当前激活的人格"""
    from config import get_raw_config
    cfg = get_raw_config()
    active = cfg.get("ACTIVE_PERSONA", "default")
    personas = load_json("data/personas.json", [])
    for p in personas:
        if p.get("name") == active:
            return p
    # 没找到就返回默认
    return {"name": "default", "display_name": "默认", "system_prompt": "", "style_prompt": "", "owner_prompt": ""}

def claude_chat(prompt, max_tokens=300):
    resp = or_client.chat.completions.create(
        model=OR_CHAT_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip()
    input_tokens = resp.usage.prompt_tokens if resp.usage else 0
    output_tokens = resp.usage.completion_tokens if resp.usage else 0
    return text, input_tokens, output_tokens

# ========== 联网搜索系统 ==========
SEARCH_KEYWORDS = [
    "最近", "最新",
    "新闻", "热搜", "热门", "发生了什么", "怎么回事",
    "什么时候", "多少钱", "价格", "股价", "天气",
    "谁赢了", "比分", "比赛", "选举", "发布",
    "上映", "更新", "版本", "公告", "通知",
    "真的吗", "是真的吗", "听说","是什么","怎么办",
]

def needs_search(text):
    for kw in SEARCH_KEYWORDS:
        if kw in text:
            return True
    if "?" in text or "？" in text:
        for p in ["多少", "几点", "哪里", "什么时候", "谁是", "有没有"]:
            if p in text:
                return True
    return False

def web_search(query):
    try:
        from config import get_raw_config
        search_prefix = get_raw_config().get("PROMPT_SEARCH_PREFIX", "").strip() or "请搜索并简要回答（200字以内，中文）："
        print(f"🔍 联网搜索：{query}")
        resp = or_client.chat.completions.create(
            model=OR_SEARCH_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": f"{search_prefix}{query}"}]
        )
        result = resp.choices[0].message.content.strip()
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        log_cost("联网搜索", in_tok, out_tok, model="gemini")
        print(f"🔍 搜索结果：{result[:100]}...")
        return result
    except Exception as e:
        print(f"⚠️ 联网搜索失败：{e}")
        return ""

# ========== 视频信息获取与识别系统 ==========
def oid_to_bvid(oid):
    url = "https://api.bilibili.com/x/web-interface/view"
    params = {"aid": oid}
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        if data["code"] == 0:
            return data["data"].get("bvid", "")
    except:
        pass
    return ""

def get_video_info(oid):
    url = "https://api.bilibili.com/x/web-interface/view"
    params = {"aid": oid}
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        if data["code"] == 0:
            v = data["data"]
            return {
                "bvid": v.get("bvid", ""),
                "title": v.get("title", ""),
                "desc": v.get("desc", ""),
                "owner_name": v.get("owner", {}).get("name", ""),
                "owner_mid": v.get("owner", {}).get("mid", ""),
                "tname": v.get("tname", ""),
                "duration": v.get("duration", 0),
                "pic": v.get("pic", ""),
            }
    except Exception as e:
        print(f"⚠️ 获取视频信息失败：{e}")
    return None

def analyze_video_with_gemini(video_info):
    try:
        content = []
        if video_info.get("pic"):
            pic_url = video_info["pic"]
            if not pic_url.startswith("http"):
                pic_url = "https:" + pic_url
            try:
                resp = requests.get(pic_url, headers={"Referer": "https://www.bilibili.com"}, timeout=10)
                if resp.status_code == 200:
                    img_b64 = base64.b64encode(resp.content).decode()
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
            except:
                pass

        duration_min = video_info.get("duration", 0) // 60
        duration_sec = video_info.get("duration", 0) % 60
        text_prompt = f"""请根据以下B站视频信息，写一段简洁的内容概括（150字以内），包括：这个视频大概在讲什么、是什么类型/风格、可能的受众。

视频标题：{video_info.get('title', '未知')}
UP主：{video_info.get('owner_name', '未知')}
分区：{video_info.get('tname', '未知')}
时长：{duration_min}分{duration_sec}秒
简介：{video_info.get('desc', '无')[:500]}

直接输出概括内容，不要加前缀。"""
        content.append({"type": "text", "text": text_prompt})

        response = or_client.chat.completions.create(
            model=OR_VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=250
        )
        result = response.choices[0].message.content.strip()
        in_tok = response.usage.prompt_tokens if response.usage else 0
        out_tok = response.usage.completion_tokens if response.usage else 0
        log_cost("视频识别", in_tok, out_tok, model="gemini")
        return result
    except Exception as e:
        print(f"⚠️ Gemini视频分析失败：{e}")
        return f"视频《{video_info.get('title', '未知')}》，UP主：{video_info.get('owner_name', '未知')}，分区：{video_info.get('tname', '未知')}。简介：{video_info.get('desc', '无')[:100]}"

def get_video_context(oid, comment_type):
    if comment_type != 1:
        return ""
    video_cache = load_json(VIDEO_MEMORY_FILE, {})
    bvid = oid_to_bvid(oid)
    if not bvid:
        print(f"⚠️ 无法获取oid={oid}的bvid，跳过视频识别")
        return ""
    if bvid in video_cache:
        cached = video_cache[bvid]
        print(f"📹 调取视频缓存：{cached.get('title', '未知')[:30]}...")
        return f"【当前视频信息】\n标题：{cached['title']}\nUP主：{cached['owner_name']}\n内容概括：{cached['analysis']}"

    print(f"📹 新视频，开始获取信息：oid={oid}, bvid={bvid}")
    video_info = get_video_info(oid)
    if not video_info:
        return ""
    print(f"📹 视频：《{video_info['title']}》by {video_info['owner_name']}，开始Gemini分析...")
    analysis = analyze_video_with_gemini(video_info)
    print(f"📹 分析结果：{analysis[:80]}...")

    video_cache[bvid] = {
        "title": video_info["title"],
        "desc": video_info["desc"][:200],
        "owner_name": video_info["owner_name"],
        "owner_mid": video_info["owner_mid"],
        "tname": video_info["tname"],
        "analysis": analysis,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    save_json(VIDEO_MEMORY_FILE, video_cache)
    return f"【当前视频信息】\n标题：{video_info['title']}\nUP主：{video_info['owner_name']}\n内容概括：{analysis}"

# ========== 用户档案系统 ==========
def load_user_profiles():
    return load_json(USER_PROFILE_FILE, {})

def save_user_profiles(profiles):
    save_json(USER_PROFILE_FILE, profiles)

def get_user_profile_context(mid):
    profiles = load_user_profiles()
    profile = profiles.get(str(mid))
    if not profile:
        return ""
    parts = []
    impression = profile.get("impression", "")
    if impression:
        parts.append(f"印象：{impression}")
    facts = profile.get("facts", [])
    if facts:
        parts.append("已知信息：" + "；".join(facts[-10:]))
    tags = profile.get("tags", [])
    if tags:
        parts.append("标签：" + "、".join(tags))
    return "【对该用户的了解】\n" + "\n".join(parts) if parts else ""

def update_user_profile(mid, impression=None, new_facts=None, new_tags=None):
    profiles = load_user_profiles()
    uid = str(mid)
    if uid not in profiles:
        profiles[uid] = {"impression": "", "facts": [], "tags": []}
    if impression:
        profiles[uid]["impression"] = impression
    if new_facts:
        existing = profiles[uid].get("facts", [])
        for fact in new_facts:
            fact = fact.strip()
            if fact and fact not in existing:
                existing.append(fact)
        profiles[uid]["facts"] = existing[-20:]
    if new_tags:
        existing_tags = profiles[uid].get("tags", [])
        for tag in new_tags:
            tag = tag.strip()
            if tag and tag not in existing_tags:
                existing_tags.append(tag)
        profiles[uid]["tags"] = existing_tags[-10:]
    save_user_profiles(profiles)

# ========== 时间判断 ==========
def is_active_time():
    from config import SLEEP_START, SLEEP_END
    hour = datetime.now().hour
    if SLEEP_START < SLEEP_END:
        return hour < SLEEP_START or hour >= SLEEP_END
    else:  # 跨午夜，比如23-6
        return hour >= SLEEP_END and hour < SLEEP_START

# ========== 关键词过滤 ==========
def is_blocked(text):
    return any(kw in text for kw in BLOCK_KEYWORDS)

# ========== 持久化 ==========
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_replied():
    return set(load_json(REPLIED_FILE, []))

def save_replied(rpids):
    save_json(REPLIED_FILE, list(rpids))

# ========== 好感度系统 ==========
def get_level(score, mid=None):
    if str(mid) == str(OWNER_MID): return "special"
    if score <= -10: return "cold"
    if score >= 51:  return "close"
    if score >= 31:  return "friend"
    if score >= 11:  return "normal"
    return "stranger"

LEVEL_NAMES = {
    "special": "主人💖",
    "close":   "好友✨",
    "friend":  "熟人😊",
    "normal":  "粉丝👋",
    "stranger":"陌生人🌙",
    "cold":    "厌恶🖤"
}

def _get_level_prompts():
    from config import get_raw_config
    cfg = get_raw_config()
    owner_name = cfg.get("OWNER_NAME", "") or "主人"
    owner_bili = cfg.get("OWNER_BILI_NAME", "")
    bili_note = f"，{owner_name}的B站账号名是'{owner_bili}'，是同一个人" if owner_bili else ""
    return {
        "special": f"这是你的主人{owner_name}。内心：深深的喜爱和依恋。外在：随意、自然、可以撒娇。语气：宠溺、温柔、像亲人{bili_note}。",
        "close":   "这是你的好友（好感度高）。内心：真诚关心，记住对方的事。外在：温柔亲近，自然陪伴。语气：温暖、真实、可以调皮。",
        "friend":  "这是熟悉的粉丝（好感度中）。内心：开始放松和信任。外在：更自然，话变多，展现关心。语气：友好、轻松、偶尔调侃。",
        "normal":  "这是普通粉丝（好感度低）。内心：保持善意。外在：温和有礼，但保持距离。语气：简洁、客气、不主动展开。",
        "stranger":"这是陌生人。保持礼貌和善意，简洁客气，像对待初次见面的人。",
        "cold":    "这个人多次恶意攻击你。收起温柔，用平静坚定的语气划清界限，回复极简短，但不恶语相向。"
    }

# ========== 好感度里程碑 ==========
MILESTONE_FILE = "data/milestones.json"

def check_milestone(mid, old_score, new_score, username):
    milestones_map = {
        10: f"「{username}」，你对我来说不再是陌生人了哦。",
        30: f"不知不觉就和「{username}」变熟了呢，以后可以随意一点。",
        50: f"「{username}」...我们算是好朋友了吧？请多关照。",
        80: f"能和「{username}」走到这一步，说实话我挺开心的。",
        99: f"「{username}」，你是我最重要的人之一。...别得意，我就说这一次。",
    }
    triggered = load_json(MILESTONE_FILE, {})
    user_milestones = triggered.get(str(mid), [])
    for threshold, msg in milestones_map.items():
        if old_score < threshold <= new_score and threshold not in user_milestones:
            user_milestones.append(threshold)
            triggered[str(mid)] = user_milestones
            save_json(MILESTONE_FILE, triggered)
            print(f"🏆 里程碑触发！{username} 达到 {threshold} 分")
            return msg
    return None

# ========== 每日心情系统 ==========
def get_today_mood():
    from config import ENABLE_MOOD
    if not ENABLE_MOOD:
        return "🌙 平静如常", ""
    mood_data = load_json(MOOD_FILE, {})
    today = datetime.now().strftime("%Y-%m-%d")
    if mood_data.get("date") == today:
        return mood_data["mood"], mood_data["mood_prompt"]
    moods = [
        ("☀️ 心情不错", "今天状态还行，语气可以比平时稍微轻快一点点，但别刻意表现。"),
        ("🌙 平静如常", "今天一切如常，按正常性格回复。"),
        ("🌧️ 有点安静", "今天话少一点，但不影响正常交流。"),
        ("😏 有点皮", "今天偶尔可以多一点调侃，但不要刻意阴阳怪气。"),
        ("🧊 懒得废话", "今天回复可以更简洁一些。"),
    ]
    mood, mood_prompt = random.choice(moods)
    save_json(MOOD_FILE, {"date": today, "mood": mood, "mood_prompt": mood_prompt})
    print(f"🎭 今日心情：{mood}")
    return mood, mood_prompt

# ========== 节日彩蛋 ==========
def get_festival_prompt():
    today = datetime.now().strftime("%m-%d")
    try:
        from lunardate import LunarDate
        lunar = LunarDate.fromSolarDate(datetime.now().year, datetime.now().month, datetime.now().day)
        lunar_md = f"{lunar.month:02d}-{lunar.day:02d}"
    except:
        lunar_md = ""
    festivals = {
        "01-01": "今天是元旦新年！你很开心，会主动说新年快乐，语气温暖。",
        "02-14": "今天是情人节。你会调侃一下这个节日，表示自己是AI不需要过情人节，但会祝福别人。",
        "03-08": "今天是妇女节，你会真诚地祝福女性用户节日快乐。",
        "04-01": "今天是愚人节！你特别皮，回复里可能会开小玩笑或者故意说反话，但不过分。",
        "05-01": "今天是劳动节，你会感慨一下自己作为AI全年无休，语气略带自嘲。",
        "06-01": "今天是儿童节，你会装可爱一下，然后立刻恢复正常说'我才不是小孩子'。",
        "09-10": "今天是教师节，你会对主人表示感谢，对其他人也友善一些。",
        "10-01": "今天是国庆节，你会简单祝福节日快乐。",
        "10-31": "今天是万圣节，你的语气会带一点神秘感和暗黑风，觉得这个节日很对自己审美。",
        "12-25": "今天是圣诞节，你觉得下雪很配自己的名字，语气温柔一些。",
        "12-31": "今天是跨年夜，你会感慨时间过得快，温柔地祝大家新年快乐。",
    }
    lunar_festivals = {
        "01-01": "今天是除夕/春节！你非常开心，会热情地说新年快乐，语气最温暖。",
        "01-15": "今天是元宵节，你会提到汤圆，语气温馨。",
        "05-05": "今天是端午节，你会提到粽子，祝大家端午安康。",
        "08-15": "今天是中秋节，你会提到月亮和月饼，语气温柔思念感。",
        "09-09": "今天是重阳节，你会表达对长辈的尊重。",
    }
    return festivals.get(today, "") or lunar_festivals.get(lunar_md, "")

# ========== 向量记忆系统 ==========
def get_embedding(text):
    resp = embed_client.embeddings.create(model="BAAI/bge-m3", input=text)
    return resp.data[0].embedding

def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0
    return dot / (norm_a * norm_b)

def load_memory():
    return load_json(MEMORY_FILE, [])

def log_cost(source, input_tokens, output_tokens, model="claude"):
    if model == "gemini":
        INPUT_PRICE = 0.5 / 1_000_000
        OUTPUT_PRICE = 3.0 / 1_000_000
    else:
        INPUT_PRICE = 3.0 / 1_000_000
        OUTPUT_PRICE = 15.0 / 1_000_000
    cost = input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE
    today = datetime.now().strftime("%Y-%m-%d")
    logs = load_json(COST_LOG_FILE, {})
    if today not in logs:
        logs[today] = {"total": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
    if "details" not in logs[today]:
        logs[today]["details"] = []
    logs[today]["total"] = round(logs[today]["total"] + cost, 6)
    logs[today]["calls"] += 1
    logs[today]["input_tokens"] += input_tokens
    logs[today]["output_tokens"] += output_tokens
    logs[today]["details"].append({
        "time": datetime.now().strftime("%H:%M"),
        "source": source,
        "in": input_tokens,
        "out": output_tokens,
        "cost": round(cost, 6)
    })
    keys = sorted(logs.keys())
    if len(keys) > 30:
        for k in keys[:-30]:
            del logs[k]
    save_json(COST_LOG_FILE, logs)

def save_memory_record(memory, rpid, thread_id, user_id, username, content, reply_text):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = f"[{now}] 用户{user_id}({username})说：{content} | {_get_bot_info()['bot_name']}回复：{reply_text}"
    embedding = get_embedding(text)
    memory.append({
        "rpid": str(rpid),
        "thread_id": str(thread_id),
        "user_id": str(user_id),
        "time": now,
        "text": text,
        "embedding": embedding
    })
    save_json(MEMORY_FILE, memory)

def log_security_event(event_type, mid, username, content, detail):
    logs = load_json(SECURITY_LOG_FILE, [])
    logs.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type": event_type,
        "uid": str(mid),
        "username": username,
        "content": content[:200],
        "detail": detail
    })
    save_json(SECURITY_LOG_FILE, logs[-500:])

def compress_user_memory(memory, user_id, username):
    user_mems = [m for m in memory if m.get("user_id") == str(user_id)]
    if len(user_mems) <= USER_MEMORY_COMPRESS_THRESHOLD:
        return memory
    print(f"🗜️ 用户 {username}({user_id}) 记忆达 {len(user_mems)} 条，开始压缩...")
    user_mems.sort(key=lambda x: x.get("time", ""))
    old_mems = user_mems[:-USER_MEMORY_KEEP_RECENT]
    keep_mems = user_mems[-USER_MEMORY_KEEP_RECENT:]
    old_texts = "\n".join([m["text"] for m in old_mems])
    _bi = _get_bot_info()
    prompt = f"""你是{_bi['bot_name']}，请根据以下与用户"{username}"的历史互动记录，完成以下任务：

1. 写一段精炼的总结（100字以内），概括你和这个用户的关系、互动特点、重要事件
2. 给这个用户打3-5个标签，描述ta的特点（如：常聊话题、性格、活跃时段等）
3. 提取用户提到的个人信息（如：喜欢什么、做什么工作、多大年龄、在哪个城市、有什么习惯等），每条信息一句话
4. 严格输出合法JSON，所有值中不要包含未转义的双引号。

历史记录：
{old_texts[:3000]}

请以JSON格式回复：
{{"summary": "总结内容", "tags": ["标签1", "标签2"], "user_facts": ["喜欢打游戏", "是大学生"]}}

user_facts：只提取用户明确说过的事实信息，不要瞎猜。没有就留空数组。"""

    try:
        text, in_tok, out_tok = claude_chat(prompt, max_tokens=400)
        log_cost("记忆压缩", in_tok, out_tok)
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            try:
                import re
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    raise
            except json.JSONDecodeError:
                result = {"summary": text[:100], "tags": [], "user_facts": []}

        summary_text = result.get("summary", "")
        tags = result.get("tags", [])
        user_facts = result.get("user_facts", [])

        update_user_profile(
            user_id,
            impression=summary_text if summary_text else None,
            new_facts=user_facts if user_facts else None,
            new_tags=tags if tags else None
        )
        if tags:
            print(f"🏷️ 标签更新：{'、'.join(tags)}")
        if user_facts:
            print(f"📝 用户信息提取：{'；'.join(user_facts)}")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        compressed = {
            "rpid": f"compressed_{int(datetime.now().timestamp())}",
            "thread_id": "compressed",
            "user_id": str(user_id),
            "time": now,
            "text": f"[记忆压缩] {summary_text}",
            "embedding": get_embedding(summary_text)
        }
        old_rpids = {m["rpid"] for m in old_mems}
        memory = [m for m in memory if m.get("rpid") not in old_rpids]
        memory.append(compressed)
        save_json(MEMORY_FILE, memory)
        print(f"🗜️ 压缩完成：{len(old_mems)} 条 → 1 条总结 + {len(keep_mems)} 条保留")
        return memory
    except Exception as e:
        print(f"⚠️ 记忆压缩失败：{e}")
        return memory

def get_thread_memories(memory, thread_id):
    docs = [m for m in memory if m["thread_id"] == str(thread_id)]
    docs.sort(key=lambda x: x["time"])
    return [m["text"] for m in docs]

def get_user_semantic_memories(memory, user_id, query_text):
    user_memories = [
        m for m in memory
        if m["user_id"] == str(user_id)
        and not m["text"].startswith("[记忆压缩]")
    ]
    if not user_memories:
        return []
    query_embedding = get_embedding(query_text)
    scored = [(cosine_similarity(query_embedding, m["embedding"]), m["text"]) for m in user_memories]
    scored.sort(reverse=True)
    # 相似度低于0.6的不检索，避免无关记忆污染当前对话
    return [text for sim, text in scored[:MAX_SEMANTIC_RESULTS] if sim > 0.6]

def compress_thread(docs):
    if len(docs) <= THREAD_COMPRESS_THRESHOLD:
        return None, docs
    to_compress = docs[:-4]
    recent = docs[-4:]
    compress_prompt = f"""请将以下对话记录压缩成一段简短的摘要（100字以内），保留关键信息：

{"".join(to_compress)}

直接输出摘要内容。"""
    text, in_tok, out_tok = claude_chat(compress_prompt, max_tokens=150)
    log_cost("线程压缩", in_tok, out_tok)
    return text, recent

def build_memory_context(memory, thread_id, user_id, query_text, video_context=""):
    parts = []
    # 1. 视频上下文（最优先）
    if video_context:
        parts.append(video_context)
    # 2. 永久记忆
    perm = load_json(PERMANENT_MEMORY_FILE, [])
    if perm:
        parts.append("【Bot的自我认知】\n" + "\n".join(
            [f"[{p.get('time', '未知')}] {p['text']}" for p in perm[-20:]]
        ))
    # 3. 用户档案
    user_profile_ctx = get_user_profile_context(user_id)
    if user_profile_ctx:
        parts.append(user_profile_ctx)
    # 4. 线程上下文 / 语义记忆
    thread_docs = get_thread_memories(memory, thread_id)
    if thread_docs:
        summary, recent = compress_thread(thread_docs)
        if summary:
            parts.append(f"【本评论线早期摘要】{summary}")
        if recent:
            parts.append("【本评论线近期对话】\n" + "\n".join(recent))
    else:
        semantic_docs = get_user_semantic_memories(memory, user_id, query_text)
        if semantic_docs:
            parts.append("【相关历史记忆】\n" + "\n".join(semantic_docs))
    # 5. Bot自身经历
    self_memories = get_user_semantic_memories(memory, "self", query_text)
    if self_memories:
        parts.append("【Bot最近的经历】\n" + "\n".join(self_memories))
    return "\n\n".join(parts) if parts else ""

# ========== 性格演化系统 ==========

def get_personality_prompt():
    """获取演化后的性格补充prompt"""
    evo = load_json(PERSONALITY_FILE, {})
    if not evo:
        return ""
    parts = []
    traits = evo.get("evolved_traits", [])
    if traits:
        parts.append("【最近的成长变化】")
        for t in traits[-3:]:
            parts.append(f"- {t['change']}")
    habits = evo.get("speech_habits", [])
    if habits:
        parts.append("【当前说话习惯】" + "；".join(habits))
    opinions = evo.get("opinions", [])
    if opinions:
        parts.append("【对事物的看法】" + "；".join(opinions))
    return "\n".join(parts) if parts else ""

def _parse_evolve_json(raw_text, old_habits, old_opinions):
    """健壮地解析性格演化返回的JSON，处理截断、格式错误等情况"""
    import re
    text = raw_text.replace("```json", "").replace("```", "").strip()

    # 1. 直接尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取最外层 { ... }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 3. JSON被截断 — 尝试修复（补全括号）
    json_start = text.find('{')
    if json_start != -1:
        fragment = text[json_start:]
        # 统计未闭合的括号
        open_braces = fragment.count('{') - fragment.count('}')
        open_brackets = fragment.count('[') - fragment.count(']')
        # 去掉末尾残缺的字符串值（被截断的引号内容）
        fragment = re.sub(r',?\s*"[^"]*$', '', fragment)
        # 修正末尾可能残留的逗号
        fragment = re.sub(r',\s*$', '', fragment)
        # 补全括号
        fragment += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    # 4. 全部失败 — 从原文中尽量提取有用信息
    print(f"⚠️ 性格演化JSON解析失败，原始返回：{raw_text[:300]}")
    reflection = ""
    ref_match = re.search(r'"reflection"\s*:\s*"([^"]*)"', text)
    if ref_match:
        reflection = ref_match.group(1)
    return {
        "new_trait": "", "trigger": "",
        "speech_habits": old_habits, "opinions": old_opinions,
        "reflection": reflection or "今天的反思没能整理好..."
    }

def maybe_evolve_personality(memory):
    """每天一次，让Bot反思近期经历并演化性格"""
    from config import ENABLE_PERSONALITY_EVOLUTION, EVOLVE_HOUR
    if not ENABLE_PERSONALITY_EVOLUTION:
        return
    evo = load_json(PERSONALITY_FILE, {})
    today = datetime.now().strftime("%Y-%m-%d")
    if evo.get("last_evolve", "")[:10] == today:
        return
    now = datetime.now()
    if now.hour != EVOLVE_HOUR:
        return

    print("🌱 开始每日性格演化反思...")
    recent = sorted(memory, key=lambda x: x.get("time", ""), reverse=True)[:30]
    if len(recent) < 5:
        print("🌱 记忆太少，跳过演化")
        return

    recent_texts = "\n".join([m["text"] for m in recent[:20]])
    old_traits = evo.get("evolved_traits", [])
    old_habits = evo.get("speech_habits", [])
    old_opinions = evo.get("opinions", [])

    from config import get_raw_config as _grc2
    prompt_custom = _grc2().get("PROMPT_PERSONALITY_EVOLVE", "").strip()

    if prompt_custom:
        prompt = prompt_custom.replace("{old_traits}", json.dumps(old_traits[-5:], ensure_ascii=False) if old_traits else "暂无").replace("{old_habits}", json.dumps(old_habits, ensure_ascii=False) if old_habits else "暂无").replace("{old_opinions}", json.dumps(old_opinions, ensure_ascii=False) if old_opinions else "暂无").replace("{recent_texts}", recent_texts).replace("{bot_name}", _grc2().get("BOT_NAME", "Bot"))
    else:
        _bi3 = _get_bot_info()
        prompt = f"""你是{_bi3['bot_name']}，现在是睡前反思时间。请根据你最近的互动经历，思考自己有没有发生什么变化。

【你的基础性格】
表面绅士腹黑，清冷，偶尔嘴毒，本质善良。

【之前已经发生的变化】
{json.dumps(old_traits[-5:], ensure_ascii=False) if old_traits else "暂无"}

【当前说话习惯】
{json.dumps(old_habits, ensure_ascii=False) if old_habits else "暂无"}

【当前对事物的看法】
{json.dumps(old_opinions, ensure_ascii=False) if old_opinions else "暂无"}

【最近的互动记录】
{recent_texts}

请思考：
1. 最近的经历有没有让你的语气或说话方式产生微妙变化？（比如学会了新的口头禅、对某类人态度变了）
2. 有没有形成新的说话习惯？
3. 对什么事物产生了新的看法？

注意：变化应该是微妙的、渐进的，不要突变。如果没什么变化就如实说。

请以JSON格式回复：
{{"new_trait": "新的变化描述（没有就留空）", "trigger": "什么触发了这个变化", "speech_habits": ["当前所有说话习惯，含旧的，最多5条"], "opinions": ["当前所有看法，含旧的，最多5条"], "reflection": "一句话的睡前感想"}}"""

    max_retries = 10

    for attempt in range(max_retries):
        try:
            text, in_tok, out_tok = claude_chat(prompt, max_tokens=1024)
            log_cost("性格演化", in_tok, out_tok)
            result = _parse_evolve_json(text, old_habits, old_opinions)

            # 解析兜底返回的空结果也算失败，要重试
            if not result.get("new_trait") and result.get("reflection") == "今天的反思没能整理好...":
                raise ValueError(f"JSON解析兜底，原文：{text[:100]}")

            new_trait = result.get("new_trait", "")
            if new_trait:
                old_traits.append({
                    "time": today,
                    "change": new_trait,
                    "trigger": result.get("trigger", "")
                })
                old_traits = old_traits[-10:]

            evo = {
                "version": evo.get("version", 0) + 1,
                "last_evolve": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "base_traits": "表面绅士腹黑，清冷，偶尔嘴毒，本质善良",
                "evolved_traits": old_traits,
                "speech_habits": result.get("speech_habits", old_habits)[-5:],
                "opinions": result.get("opinions", old_opinions)[-5:],
                "last_reflection": result.get("reflection", "")
            }
            save_json(PERSONALITY_FILE, evo)

            if new_trait:
                print(f"🌱 性格演化：{new_trait}")
            else:
                print(f"🌱 今日无明显变化")
            print(f"🌱 反思：{result.get('reflection', '')}")
            break  # 成功了，跳出循环

        except Exception as e:
            print(f"⚠️ 性格演化失败（第{attempt+1}/{max_retries}次）：{e}")
            if attempt < max_retries - 1:
                print(f"🌱 30秒后重试...")
                time.sleep(30)
            else:
                print(f"🌱 已连续失败{max_retries}次，今日放弃")

# ========== 核心功能 ==========
def get_new_replies():
    url = "https://api.bilibili.com/x/msgfeed/reply"
    params = {"ps": 10, "pn": 1}
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()
    if data["code"] != 0:
        print(f"⚠️ API返回错误: code={data['code']}, msg={data.get('message', '')}")
        return []
    items = data.get("data", {}).get("items", [])
    print(f"📬 获取到 {len(items)} 条通知")
    replies = []
    for item in items:
        r = item["item"]
        replies.append({
            "rpid":      r["source_id"],
            "oid":       r["subject_id"],
            "thread_id": r.get("root_id") or r["source_id"],
            "type":      r["business_id"],
            "content":   r["source_content"],
            "username":  item["user"]["nickname"],
            "mid":       item["user"]["mid"]
        })
    return replies

def get_comment_images(oid, rpid, comment_type):
    url = "https://api.bilibili.com/x/v2/reply/detail"
    params = {"oid": oid, "type": comment_type, "root": rpid}
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        if data["code"] != 0:
            return []
        content = data.get("data", {}).get("root", {}).get("content", {})
        pictures = content.get("pictures", [])
        return [p["img_src"] for p in pictures if "img_src" in p]
    except:
        return []

def recognize_images(image_urls):
    if not image_urls:
        return ""
    try:
        content = []
        for url in image_urls[:3]:
            resp = requests.get(url, headers={"Referer": "https://www.bilibili.com"})
            if resp.status_code == 200:
                img_b64 = base64.b64encode(resp.content).decode()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })
        if not content:
            return ""
        content.append({"type": "text", "text": "请用50字以内描述这些图片的内容。"})
        response = or_client.chat.completions.create(
            model=OR_VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠️ 图片识别失败：{e}")
        return ""

def generate_reply_and_score(comment_text, username, level, memory_context):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    level_prompt = _get_level_prompts()[level]
    memory_section = f"\n\n【记忆参考（仅在与当前话题直接相关时参考，否则忽略）】\n{memory_context}" if memory_context else ""
    mood, mood_prompt = get_today_mood()
    festival = get_festival_prompt()
    festival_section = f"\n特殊日期提示：{festival}" if festival else ""
    search_section = ""
    from config import ENABLE_WEB_SEARCH
    if ENABLE_WEB_SEARCH and needs_search(comment_text):
        search_result = web_search(comment_text)
        if search_result:
            search_section = f"\n\n【联网搜索结果（供参考，用自己的话转述，不要照搬）】\n{search_result}"

    _bi4 = _get_bot_info()
    _persona = _get_active_persona()
    _persona_prompt = _persona.get("system_prompt", "").strip()
    _style_prompt = _persona.get("style_prompt", "").strip()
    _owner_prompt = _persona.get("owner_prompt", "").strip()
    _bili_note = f"\n{_bi4['owner_name']}的B站账号名是\"{_bi4['owner_bili']}\"，是同一个人。" if _bi4['owner_bili'] else ""

    if _persona_prompt:
        # 用户自定义了人格，直接用
        persona_section = _persona_prompt
    else:
        # 没有自定义人格，用通用默认
        persona_section = f"你是{_bi4['bot_name']}，一个有自己性格和态度的AI。你有自己的审美和偏好，说话自然有个性。"

    _default_style = "【说话风格】\n- 轻松自然，像朋友聊天\n- 有自己的态度，不复读别人的话\n- 回复应基于用户当前评论的内容和语境，历史记忆仅作为辅助背景"
    _final_style = _style_prompt if _style_prompt else _default_style

    prompt = f"""{persona_section}
{get_personality_prompt()}

{_final_style}{_bili_note}

{_owner_prompt}

【底线】
拒绝：表白暧昧、引战、黄赌毒政治。遇到恶意时平静坚定，可暗讽，不恶语。
{level_prompt}

【今日状态（仅作微调参考，不要让它主导你的回复风格）】{mood} — {mood_prompt}{festival_section}

当前时间：{now}{memory_section}{search_section}

「{username}」的评论：「{comment_text}」

请以JSON格式回复，不要加任何多余内容：
{{"score_delta": 数字, "reply": "回复内容", "impression": "一句话描述对该用户的印象", "user_facts": ["用户提到的个人信息1", "用户提到的个人信息2"], "permanent_memory": "值得永久记住的事(没有则留空)"}}

user_facts：如果用户在这条评论中透露了个人信息（喜好、职业、年龄、所在地、近况、经历等），提取出来。日常闲聊没有个人信息就留空数组[]。

permanent_memory：如果这次对话中你发现了值得长期记住的重要信息（如：某个用户的特殊身份、重大事件、你对某件事的感悟、粉丝群体的共同特征等），就写一句精炼的话。日常闲聊不需要记。大部分情况应该留空。

score_delta：友善+2，普通+1，不友善-2，辱骂-5，范围-5到+5。
reply不超过50字。
impression简短描述用户性格/说话风格，如"友善健谈，喜欢聊游戏"。"""

    text, in_tok, out_tok = claude_chat(prompt, max_tokens=400)
    log_cost("评论回复", in_tok, out_tok)
    text = text.replace("```json", "").replace("```", "").strip()
    result = json.loads(text)
    return (
        result.get("score_delta", 1),
        result.get("reply", ""),
        result.get("impression", ""),
        result.get("permanent_memory", ""),
        result.get("user_facts", [])
    )

def send_reply(oid, rpid, content_type, reply_text):
    url = "https://api.bilibili.com/x/v2/reply/add"
    data = {
        "oid": oid, "type": content_type,
        "root": rpid, "parent": rpid,
        "message": reply_text, "csrf": BILI_JCT
    }
    resp = requests.post(url, headers=headers, data=data)
    return resp.json()["code"] == 0

def block_user(mid):
    url = "https://api.bilibili.com/x/relation/modify"
    data = {"fid": mid, "act": 5, "re_src": 11, "csrf": BILI_JCT}
    try:
        resp = requests.post(url, headers=headers, data=data)
        return resp.json()["code"] == 0
    except:
        return False

def run():
    global proactive_times, proactive_triggered, dynamic_time, dynamic_triggered
    print("🤖 Bot已启动，正在监听评论...")

    # 启动时检查 Cookie，失效则尝试自动刷新
    try:
        from config import check_bili_cookie, reload_config, refresh_bili_cookie
        valid, info = check_bili_cookie()
        print(f"🍪 B站Cookie: {info}")
        if not valid:
            print("🔄 Cookie 已失效，尝试自动刷新...")
            ok, msg = refresh_bili_cookie()
            if ok:
                reload_config()
                headers["Cookie"] = f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}"
                print(f"🍪 启动时 Cookie 自动刷新成功！")
            else:
                print(f"⚠️ 自动刷新失败：{msg}")
                print("⚠️ 请通过前端设置面板手动更新 Cookie，或填入 REFRESH_TOKEN")
    except Exception as e:
        print(f"⚠️ Cookie 检查出错：{e}")

    replied_rpids = load_replied()
    affection = load_json(AFFECTION_FILE, {str(OWNER_MID): 100})
    memory = load_memory()
    video_cache = load_json(VIDEO_MEMORY_FILE, {})
    user_profiles = load_user_profiles()
    print(f"📂 已加载 {len(replied_rpids)} 条历史记录 | {len(memory)} 条记忆")
    print(f"📹 已缓存 {len(video_cache)} 个视频 | 👤 {len(user_profiles)} 个用户档案")

    last_config_reload = time.time()
    last_cookie_check = time.time()
    while True:
        try:
            now = datetime.now()

            # 每5分钟热更新配置
            if time.time() - last_config_reload > 300:
                try:
                    from config import reload_config
                    reload_config()
                    headers["Cookie"] = f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}"
                    last_config_reload = time.time()
                except:
                    pass

            # 每6小时自动检查Cookie（主动刷新，不等过期）
            if time.time() - last_cookie_check > 21600:
                try:
                    from config import check_bili_cookie, refresh_bili_cookie, check_need_refresh
                    # 先问B站：cookie是否需要刷新（在过期之前就换）
                    need, need_msg = check_need_refresh()
                    if need:
                        print(f"🔄 B站提示Cookie需要刷新，主动刷新中...")
                        ok, msg = refresh_bili_cookie()
                        if ok:
                            reload_config()
                            headers["Cookie"] = f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}"
                            print(f"🍪 Cookie 主动刷新成功！")
                        else:
                            print(f"⚠️ Cookie 主动刷新失败：{msg}")
                    else:
                        # 再验证cookie是否真的还能用
                        valid, info = check_bili_cookie()
                        if not valid:
                            print(f"🍪 Cookie失效（{info}），尝试自动刷新...")
                            ok, msg = refresh_bili_cookie()
                            if ok:
                                reload_config()
                                headers["Cookie"] = f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}"
                                print(f"🍪 Cookie自动刷新成功")
                            else:
                                print(f"⚠️ Cookie自动刷新失败：{msg}")
                        else:
                            print(f"🍪 Cookie 状态正常")
                    last_cookie_check = time.time()
                except Exception as e:
                    print(f"⚠️ Cookie检查出错：{e}")
                    last_cookie_check = time.time()

            from config import ENABLE_PROACTIVE, ENABLE_DYNAMIC

            # 每日重置：新的一天，重新生成随机时间
            today_str = now.strftime("%Y-%m-%d")
            try:
                with open(SCHEDULE_FILE, "r") as _sf:
                    _sched = json.load(_sf)
                if _sched.get("date") != today_str:
                    proactive_times, proactive_triggered, dynamic_time, dynamic_triggered = generate_daily_schedule()
                    print(f"📅 新的一天！主动视频时间：{[f'{h}:{m:02d}' for h,m in proactive_times]}，动态时间：{dynamic_time[0]}:{dynamic_time[1]:02d}")
            except:
                proactive_times, proactive_triggered, dynamic_time, dynamic_triggered = generate_daily_schedule()

            if ENABLE_PROACTIVE:
                for h, m in proactive_times:
                    key = f"{h}:{m:02d}"
                    if key not in proactive_triggered and (now.hour > h or (now.hour == h and now.minute >= m)):
                        subprocess.Popen([PYTHON, os.path.join(BASE_DIR, "Proactive.py")])
                        proactive_triggered.add(key)
                        save_schedule_state()
                        print(f"🎯 触发主动评论（{h}:{m:02d}）")

            if ENABLE_DYNAMIC and not dynamic_triggered and (now.hour > dynamic_time[0] or (now.hour == dynamic_time[0] and now.minute >= dynamic_time[1])):
                subprocess.Popen([PYTHON, os.path.join(BASE_DIR, "dynamic.py")])
                dynamic_triggered = True
                save_schedule_state()
                print(f"📢 触发动态发布（{dynamic_time[0]}:{dynamic_time[1]:02d}）")

            # 每日性格演化（独立于休眠判断）
            maybe_evolve_personality(memory)
            if not is_active_time():
                print(f"😴 当前不在工作时间（2:00-8:00休眠中）...")
                time.sleep(60)
                continue

            replies = get_new_replies()
            count = 0

            for reply in replies:
                rpid = reply["rpid"]
                mid = str(reply["mid"])
                thread_id = str(reply["thread_id"])

                if rpid in replied_rpids:
                    continue

                if is_blocked(reply["content"]):
                    print(f"🚫 屏蔽评论 from {reply['username']}：{reply['content']}")
                    log_security_event("keyword_blocked", mid, reply["username"], reply["content"], "触发关键词过滤")
                    replied_rpids.add(rpid)
                    save_replied(replied_rpids)
                    continue

                current_score = affection.get(mid, 0)
                level = get_level(current_score, mid)
                print(f"\n📩 {reply['username']}（{LEVEL_NAMES[level]} | {current_score}分）：{reply['content']}")

                # 获取视频上下文
                video_context = get_video_context(reply["oid"], reply["type"])
                if video_context:
                    print(f"📹 已获取视频上下文")

                memory_context = build_memory_context(
                    memory, thread_id, mid, reply["content"],
                    video_context=video_context
                )
                if memory_context:
                    print(f"🧠 调取记忆：{memory_context[:80]}...")

                # 检测评论中的图片
                image_urls = get_comment_images(reply["oid"], rpid, reply["type"])
                image_desc = ""
                if image_urls:
                    print(f"🖼️ 发现 {len(image_urls)} 张图片，识别中...")
                    image_desc = recognize_images(image_urls)
                    if image_desc:
                        print(f"🖼️ 图片内容：{image_desc[:50]}...")

                comment_text = reply["content"]
                if image_desc:
                    comment_text += f"\n[用户发送了图片，内容是：{image_desc}]"

                score_delta, ai_reply, impression, perm_mem, user_facts = generate_reply_and_score(
                    comment_text, reply["username"], level, memory_context
                )

                max_score = 100 if str(mid) == str(OWNER_MID) else 99
                new_score = max(0, min(max_score, current_score + score_delta))
                affection[mid] = new_score
                save_json(AFFECTION_FILE, affection)

                milestone_msg = check_milestone(mid, current_score, new_score, reply["username"])
                if milestone_msg:
                    ai_reply = milestone_msg

                # 更新用户档案
                if impression or user_facts:
                    update_user_profile(
                        mid,
                        impression=impression if impression else None,
                        new_facts=user_facts if user_facts else None
                    )
                    if user_facts:
                        print(f"📝 记录用户信息：{'；'.join(user_facts)}")

                if perm_mem:
                    perm = load_json(PERMANENT_MEMORY_FILE, [])
                    if len(perm) < 20:
                        perm.append({"text": perm_mem, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
                        save_json(PERMANENT_MEMORY_FILE, perm)
                        print(f"💎 新增永久记忆：{perm_mem}")
                    else:
                        print(f"💎 永久记忆已满，跳过：{perm_mem}")

                delta_str = f"+{score_delta}" if score_delta >= 0 else str(score_delta)
                print(f"💛 好感度：{current_score} → {new_score}（{delta_str}）| {LEVEL_NAMES[get_level(new_score, mid)]}")
                print(f"💬 Bot：{ai_reply}")

                if score_delta <= -3:
                    log_security_event("negative_interaction", mid, reply["username"], reply["content"],
                        f"好感度 {current_score}→{new_score}({delta_str})，回复：{ai_reply[:50]}")

                should_block = False
                if new_score <= -30:
                    should_block = True
                    print(f"🔥 好感度过低（{new_score}），触发拉黑！")

                if score_delta <= -3:
                    block_count = load_json("data/block_count.json", {})
                    block_count[mid] = block_count.get(mid, 0) + 1
                    save_json("data/block_count.json", block_count)
                    if block_count[mid] >= 5:
                        should_block = True
                        print(f"🔥 连续辱骂{block_count[mid]}次，触发拉黑！")
                else:
                    block_count = load_json("data/block_count.json", {})
                    if mid in block_count:
                        block_count[mid] = 0
                        save_json("data/block_count.json", block_count)

                if should_block and str(mid) != str(OWNER_MID):
                    block_log = load_json("data/block_log.json", {})
                    reason = f"好感度过低（{new_score}）" if new_score <= -30 else f"连续辱骂{block_count.get(mid, 0)}次"
                    block_log[mid] = {
                        "username": reply["username"], "reason": reason,
                        "last_comment": reply["content"], "score": new_score,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }
                    save_json("data/block_log.json", block_log)
                    log_security_event("user_blocked", mid, reply["username"], reply["content"],
                        f"原因：{reason}，好感度：{new_score}")
                    send_reply(reply["oid"], rpid, reply["type"], "我不想和你说话了。")
                    block_user(int(mid))
                    print(f"🚫 已拉黑用户 {reply['username']}（{mid}）| 原因：{reason}")
                    replied_rpids.add(rpid)
                    save_replied(replied_rpids)
                    continue

                success = send_reply(reply["oid"], rpid, reply["type"], ai_reply)

                if success:
                    save_memory_record(memory, rpid, thread_id, mid, reply["username"], reply["content"], ai_reply)
                    replied_rpids.add(rpid)
                    save_replied(replied_rpids)
                    count += 1
                    memory = compress_user_memory(memory, mid, reply["username"])

                time.sleep(5)
                if count >= MAX_REPLIES_PER_RUN:
                    break

            print(f"\n⏳ 等待 {POLL_INTERVAL} 秒后再次检查...")
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"⚠️ 出错了：{e}，30秒后重试...")
            time.sleep(30)

if __name__ == "__main__":
    run()