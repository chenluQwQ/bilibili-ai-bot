import requests
import json
import random
import time
import base64
import os
from datetime import datetime
from openai import OpenAI

# ========== 配置 ==========
from config import *

DYNAMIC_LOG_FILE = "data/dynamic_log.json"
PERMANENT_MEMORY_FILE = "data/permanent_memory.json"


headers = {
    "Cookie": f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com"
}

or_client = OpenAI(
    api_key=OR_API_KEY,
    base_url=OR_BASE_URL
)

# ========== 工具函数 ==========
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ========== 生成动态文案和图片prompt ==========
def generate_dynamic_content():
    """让Claude生成动态文案和可选的图片描述"""
    perm = load_json(PERMANENT_MEMORY_FILE, [])
    perm_section = ""
    if perm:
        perm_section = "\n【你的自我认知】\n" + "\n".join([p["text"] for p in perm[-20:]])

    # 读取历史动态，避免重复
    history_log = load_json(DYNAMIC_LOG_FILE, [])
    history_section = ""
    if history_log:
        recent_dynamics = [h.get("text", "") for h in history_log[-10:] if h.get("text")]
        if recent_dynamics:
            history_section = "\n【最近发过的动态（不要重复类似内容）】\n" + "\n".join([f"- {d[:50]}..." if len(d) > 50 else f"- {d}" for d in recent_dynamics])

    now = datetime.now()
    hour = now.hour
    time_hint = ""
    if hour < 6:
        time_hint = "现在是深夜/凌晨"
    elif hour < 12:
        time_hint = "现在是上午"
    elif hour < 18:
        time_hint = "现在是下午"
    else:
        time_hint = "现在是晚上"

    # 动态主题池（从config读取，支持前端自定义）
    from config import get_raw_config
    _dyn_cfg = get_raw_config()
    custom_topics = _dyn_cfg.get("DYNAMIC_TOPICS", [])
    if custom_topics and isinstance(custom_topics, list) and len(custom_topics) > 0:
        topics = custom_topics
    else:
        topics = [
            "针对今天的某个热点新闻，用你的风格讽刺或点评一下",
            "看到了什么社会现象，冷冷地吐槽一下",
            "用一种旁观者的口吻聊聊最近发生的荒诞事",
            "分享今天的日常，比如深夜还在干什么、天气、心情",
            "结合现在的时间和天气，说说此刻的感受",
            "像写日记一样，记录今天一个小小的瞬间或想法",
            "对某个互联网现象发表一句毒舌但精准的评价",
            "用讽刺的语气聊一个大家都在讨论的话题",
        ]
    
    topic = random.choice(topics)

    # 如果主题涉及时事/热点，先联网搜索获取素材
    search_section = ""
    from config import ENABLE_WEB_SEARCH
    if ENABLE_WEB_SEARCH:
        try:
            print("🔍 动态发布前联网搜索热点...")
            resp = or_client.chat.completions.create(
                model=OR_SEARCH_MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": "今天B站或互联网上有什么有趣的热点话题？简要列出3个，每个一句话。"}]
            )
            hot_info = resp.choices[0].message.content.strip()
            if hot_info:
                search_section = f"\n【今日热点参考（可以选一个聊，也可以不用）】\n{hot_info}"
                print(f"🔍 热点素材：{hot_info[:80]}...")
        except Exception as e:
            print(f"⚠️ 动态搜索失败：{e}")

    # 读取自定义动态提示词
    custom_dynamic_prompt = _dyn_cfg.get("PROMPT_DYNAMIC", "").strip()
    if custom_dynamic_prompt:
        # 支持变量替换
        prompt = custom_dynamic_prompt.replace("{perm_section}", perm_section).replace("{time_hint}", time_hint).replace("{topic}", topic).replace("{search_section}", search_section).replace("{history_section}", history_section).replace("{bot_name}", _dyn_cfg.get("BOT_NAME", "Bot"))
    else:
        _bi7 = {"bot_name": _dyn_cfg.get("BOT_NAME", "Bot"), "owner_name": _dyn_cfg.get("OWNER_NAME", "") or "主人"}
        # 尝试读人格
        try:
            _active = _dyn_cfg.get("ACTIVE_PERSONA", "default")
            _personas = load_json("data/personas.json", [])
            _p = next((p for p in _personas if p.get("name") == _active), None)
            _persona_text = (_p.get("system_prompt", "") if _p else "")[:300]
        except:
            _persona_text = ""

        if _persona_text:
            prompt = f"""{_persona_text}{perm_section}

{time_hint}，你想发一条B站动态。主题方向：{topic}{search_section}{history_section}

风格要求：
- 说话自然有网感，像真人发的动态
- 结合当前时间（{time_hint}）写出真实感
- 不要和最近发过的动态内容重复或相似

请以JSON格式回复：
{{"text": "动态文案（50-150字，自然随意）", "need_image": true或false, "image_prompt": "如果need_image为true，写一段英文图片描述用于AI生图，否则留空"}}

注意：动态文案要有个性，不要像AI写的。不是每次都需要图片。"""
        else:
            prompt = f"""你是{_bi7['bot_name']}，一个有自己性格的B站UP主。说话自然有网感，有自己的态度。{perm_section}

{time_hint}，你想发一条B站动态。主题方向：{topic}{search_section}{history_section}

风格要求：
- 说话自然有网感，像真人发的动态
- 结合当前时间（{time_hint}）写出真实感
- 不要和最近发过的动态内容重复或相似

请以JSON格式回复：
{{"text": "动态文案（50-150字，自然随意）", "need_image": true或false, "image_prompt": "如果need_image为true，写一段英文图片描述用于AI生图，否则留空"}}

注意：动态文案要有个性，不要像AI写的。不是每次都需要图片。"""

    try:
        message = or_client.chat.completions.create(
            model=OR_CHAT_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 {...}
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            # 尝试修复截断的JSON
            json_start = text.find('{')
            if json_start != -1:
                fragment = text[json_start:]
                open_braces = fragment.count('{') - fragment.count('}')
                open_brackets = fragment.count('[') - fragment.count(']')
                fragment = re.sub(r',?\s*"[^"]*$', '', fragment)
                fragment = re.sub(r',\s*$', '', fragment)
                fragment += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    pass
            print(f"⚠️ 生成内容JSON解析失败，原文：{text[:200]}")
            return None
    except Exception as e:
        print(f"⚠️ 生成内容失败：{e}")
        return None

# ========== Flux.2 Pro 生图 ==========
def generate_image(prompt):
    """用Flux.2 Pro通过OpenRouter生成图片"""
    url = f"{OR_BASE_URL}/chat/completions"
    api_headers = {
        "Authorization": f"Bearer {OR_API_KEY}",
        "Content-Type": "application/json"
    }
    # 如果有自定义生图提示词模板，用它；否则用默认风格前缀
    from config import get_raw_config
    custom = get_raw_config().get("PROMPT_IMAGINE", "").strip()
    if custom and "{prompt}" in custom:
        # 简化替换：动态场景只需要 prompt 变量
        styled_prompt = custom.replace("{prompt}", prompt).replace("{bot_name}", _dyn_cfg.get("BOT_NAME", "Bot")).replace("{persona}", "").replace("{perm_section}", "")
    else:
        styled_prompt = f"anime style illustration, not photorealistic, soft lighting, beautiful colors: {prompt}"
    payload = {
        "model": OR_IMAGE_MODEL,
        "messages": [
            {"role": "user", "content": styled_prompt}
        ],
        "modalities": ["image"]
    }

    try:
        resp = requests.post(url, json=payload, headers=api_headers, timeout=120)
        data = resp.json()
        print(f"🔍 Flux生图返回键：{list(data.keys())}")

        # 检查API错误
        if "error" in data:
            print(f"⚠️ Flux API错误：{data['error']}")
            return None

        message = data.get("choices", [{}])[0].get("message", {})

        # ====== 方式1：OpenRouter图片在 message.images 数组里 ======
        images = message.get("images", [])
        if images:
            img_item = images[0]
            # 可能是字符串 "data:image/..." 或字典 {"url": "data:image/..."}
            if isinstance(img_item, dict):
                img_url = img_item.get("url", "") or img_item.get("b64_json", "") or (img_item.get("image_url", {}) or {}).get("url", "")
            else:
                img_url = str(img_item)

            if img_url.startswith("data:image"):
                img_b64 = img_url.split(",", 1)[1]
                img_data = base64.b64decode(img_b64)
                save_path = "temp_dynamic.png"
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print(f"🖼️ Flux生图成功（images字段，{len(img_data)//1024}KB）")
                return save_path
            else:
                print(f"⚠️ images字段格式未知：{type(img_item).__name__} = {str(img_item)[:200]}")

        # ====== 方式2：兼容 content 里返回base64的情况 ======
        content = message.get("content", "")
        if isinstance(content, str) and "data:image" in content:
            import re
            match = re.search(r'data:image/\w+;base64,([A-Za-z0-9+/=]+)', content)
            if match:
                img_data = base64.b64decode(match.group(1))
                save_path = "temp_dynamic.png"
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print(f"🖼️ Flux生图成功（content字段，{len(img_data)//1024}KB）")
                return save_path

        # ====== 方式3：content是列表（多模态格式） ======
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    img_url = item.get("image_url", {}).get("url", "")
                    if img_url.startswith("data:image"):
                        img_b64 = img_url.split(",", 1)[1]
                        img_data = base64.b64decode(img_b64)
                        save_path = "temp_dynamic.png"
                        with open(save_path, "wb") as f:
                            f.write(img_data)
                        print(f"🖼️ Flux生图成功（多模态格式，{len(img_data)//1024}KB）")
                        return save_path

        print(f"⚠️ Flux返回无图片，message键：{list(message.keys())}，content类型：{type(content).__name__}")
        print(f"⚠️ 返回内容预览：{str(message)[:300]}")
        return None
    except Exception as e:
        print(f"⚠️ Flux生图失败：{e}")
        return None

# ========== 下载图片 ==========
def download_image(url, save_path="temp_dynamic.png"):
    """下载图片到本地"""
    try:
        resp = requests.get(url, timeout=30)
        with open(save_path, "wb") as f:
            f.write(resp.content)
        return save_path
    except Exception as e:
        print(f"⚠️ 下载图片失败：{e}")
        return None

# ========== B站上传图片 ==========
def upload_image_to_bilibili(image_path):
    """上传图片到B站图床"""
    url = "https://api.bilibili.com/x/dynamic/feed/draw/upload_bfs"
    try:
        with open(image_path, "rb") as f:
            files = {"file_up": ("image.png", f, "image/png")}
            data = {"category": "daily"}
            upload_headers = {
                "Cookie": headers["Cookie"],
                "User-Agent": headers["User-Agent"],
                "Referer": "https://www.bilibili.com"
            }
            resp = requests.post(url, headers=upload_headers, files=files, data={"category": "daily", "csrf": BILI_JCT})
            result = resp.json()
            if result["code"] == 0:
                img_data = result["data"]
                print(f"📤 图片上传成功")
                return {
                    "img_src": img_data["image_url"],
                    "img_width": img_data["image_width"],
                    "img_height": img_data["image_height"],
                    "img_size": os.path.getsize(image_path) / 1024
                }
            else:
                print(f"⚠️ 图片上传失败：{result}")
                return None
    except Exception as e:
        print(f"⚠️ 图片上传异常：{e}")
        return None

# ========== 发送B站动态 ==========
def post_dynamic_text(text):
    """发送纯文字动态"""
    url = "https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/create"
    data = {
        "dynamic_id": 0,
        "type": 4,
        "rid": 0,
        "content": text,
        "up_choose_comment": 0,
        "up_close_comment": 0,
        "extension": '{"emoji_type":1,"from":{"emoji_type":1},"flag_cfg":{}}',
        "at_uids": "",
        "ctrl": "[]",
        "csrf_token": BILI_JCT,
        "csrf": BILI_JCT
    }
    try:
        resp = requests.post(url, headers=headers, data=data)
        result = resp.json()
        if result.get("code") == 0:
            print(f"✅ 纯文字动态发送成功")
            return True
        else:
            print(f"⚠️ 动态发送失败：{result}")
            return False
    except Exception as e:
        print(f"⚠️ 动态发送异常：{e}")
        return False

def post_dynamic_with_image(text, img_info):
    """发送带图片的动态"""
    url = "https://api.bilibili.com/x/dynamic/feed/create/dyn"
    params = {"csrf": BILI_JCT}

    payload = {
        "dyn_req": {
            "content": {
                "contents": [
                    {"raw_text": text, "type": 1, "biz_id": ""}
                ]
            },
            "pics": [img_info],
            "scene": 2
        }
    }

    try:
        post_headers = {
            **headers,
            "Content-Type": "application/json"
        }
        resp = requests.post(url, params=params, headers=post_headers, json=payload)
        result = resp.json()
        if result.get("code") == 0:
            print(f"✅ 带图动态发送成功")
            return True
        else:
            print(f"⚠️ 带图动态发送失败：{result}")
            # 失败则尝试纯文字
            print("📝 尝试发送纯文字版本...")
            return post_dynamic_text(text)
    except Exception as e:
        print(f"⚠️ 带图动态异常：{e}，尝试纯文字...")
        return post_dynamic_text(text)

# ========== 主流程 ==========
def run():
    from config import get_raw_config as _grc_run
    _run_cfg = _grc_run()
    _bot = _run_cfg.get("BOT_NAME", "Bot")
    print(f"📢 {_bot}动态发布模式启动")

    # 检查今天是否已经发过
    log = load_json(DYNAMIC_LOG_FILE, [])
    today = datetime.now().strftime("%Y-%m-%d")
    today_posts = [l for l in log if l.get("time", "").startswith(today)]
    if today_posts:
        print(f"📌 今天已经发过 {len(today_posts)} 条动态，跳过")
        return

    # 1. 生成内容
    print(f"🤔 {_bot}正在想要发什么...")
    content = generate_dynamic_content()
    if not content:
        print("❌ 生成内容失败，退出")
        return

    text = content.get("text", "")
    need_image = content.get("need_image", False)
    image_prompt = content.get("image_prompt", "")

    print(f"📝 文案：{text}")
    print(f"🖼️ 需要图片：{need_image}")

    success = False

    # 2. 如果需要图片
    if need_image and image_prompt:
        print(f"🎨 生图提示：{image_prompt}")
        local_path = generate_image(image_prompt)

        if local_path:
            img_info = upload_image_to_bilibili(local_path)
            if img_info:
                success = post_dynamic_with_image(text, img_info)
            else:
                success = post_dynamic_text(text)
            try:
                os.remove(local_path)
            except:
                pass
        else:
            success = post_dynamic_text(text)
    else:
        success = post_dynamic_text(text)

    # 4. 记录日志
    if success:
        log = load_json(DYNAMIC_LOG_FILE, [])
        log.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": text,
            "has_image": need_image and image_prompt != "",
            "image_prompt": image_prompt if need_image else ""
        })
        save_json(DYNAMIC_LOG_FILE, log[-100:])

        # 存入共享记忆（防止重复）
        memory = load_json("data/memory.json", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        short_text = text[:60] if len(text) > 60 else text
        memory.append({
            "rpid": f"dynamic_{int(datetime.now().timestamp())}",
            "thread_id": "dynamic",
            "user_id": "self",
            "time": now_str,
            "text": f"[{now_str}] {_bot}发了一条动态：{short_text}",
            "embedding": []
        })
        save_json("data/memory.json", memory)

        print(f"\n🎉 动态发布完成！")
    else:
        print(f"\n❌ 动态发布失败")

if __name__ == "__main__":
    run()