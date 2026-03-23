import json
import math
import os
import base64
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from openai import OpenAI

# ========== 配置 ==========
from config import *

# ========== 访问密码 ==========
AUTH_PASSWORD = os.environ.get("CHAT_PASSWORD", "") or "admin()"
# 从config.json读取（前端改过密码会存在这里）
from config import get_raw_config as _get_raw
_saved_pwd = _get_raw().get("CHAT_PASSWORD", "")
if _saved_pwd:
    AUTH_PASSWORD = _saved_pwd
SECRET_KEY = os.environ.get("SECRET_KEY", uuid.uuid4().hex)

AFFECTION_FILE = "data/affection.json"
MEMORY_FILE = "data/memory.json"
LOCAL_CHAT_FILE = "data/local_chat.json"
COST_LOG_FILE = "data/cost_log.json"
USER_PROFILE_FILE = "data/user_profiles.json"
PERSONALITY_FILE = "data/personality_evolution.json"
PERSONA_FILE = "data/personas.json"
MOOD_FILE = "data/mood.json"
BLOCK_LOG_FILE = "data/block_log.json"
IMAGE_DIR = "data/images"

or_client = OpenAI(api_key=OR_API_KEY, base_url=OR_BASE_URL)
embed_client = OpenAI(api_key=SILICON_API_KEY, base_url=_get_raw().get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1"))

def get_or_client(model_type="chat"):
    """获取指定模型类型的 OpenAI 客户端，支持独立 URL/Key"""
    from config import get_model_config
    base_url, api_key, model_id, fallback = get_model_config(model_type)
    return OpenAI(api_key=api_key, base_url=base_url), model_id, fallback

# ========== 联网搜索 ==========
SEARCH_KEYWORDS = [
    "最近", "最新", "今天", "昨天", "现在", "目前", "当前",
    "新闻", "热搜", "热门", "发生了什么", "怎么回事",
    "什么时候", "多少钱", "价格", "股价", "天气",
    "谁赢了", "比分", "比赛", "选举", "发布",
    "上映", "更新", "版本", "公告", "通知",
    "真的吗", "是真的吗", "听说", "搜一下", "查一下", "帮我查",
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
        client, model, fallback = get_or_client("search")
        resp = client.chat.completions.create(
            model=model, max_tokens=500,
            messages=[{"role": "user", "content": f"{search_prefix}{query}"}]
        )
        result = resp.choices[0].message.content.strip()
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        log_cost("联网搜索", in_tok, out_tok, model=model)
        return result
    except Exception as e:
        print(f"⚠️ 联网搜索主模型失败：{e}")
        if fallback:
            try:
                resp = client.chat.completions.create(
                    model=fallback, max_tokens=500,
                    messages=[{"role": "user", "content": f"{search_prefix}{query}"}])
                return resp.choices[0].message.content.strip()
            except:
                pass
        return ""

app = Flask(__name__, template_folder=".", static_folder=".", static_url_path="")
app.secret_key = SECRET_KEY

# ========== 登录验证 ==========
@app.before_request
def check_auth():
    # 放行：首页、静态资源、登录接口
    if request.path == "/" or request.path == "/api/login" or request.path == "/api/auth_check" or request.path == "/api/health" or request.path == "/api/branding":
        return
    if request.path.startswith("/data/images/"):
        return
    # 非html/css/js等静态资源也放行
    if not request.path.startswith("/api/"):
        return
    # API 需要验证
    if not session.get("authed"):
        return jsonify({"error": "未登录", "need_login": True}), 401

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    pwd = data.get("password", "")
    if pwd == AUTH_PASSWORD:
        session["authed"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"error": "密码错误"}), 403

@app.route("/api/auth_check", methods=["GET"])
def auth_check():
    if session.get("authed"):
        return jsonify({"authed": True})
    return jsonify({"authed": False})

@app.route("/api/change_password", methods=["POST"])
def change_password():
    global AUTH_PASSWORD
    data = request.json or {}
    old_pwd = data.get("old", "")
    new_pwd = data.get("new", "")
    if old_pwd != AUTH_PASSWORD:
        return jsonify({"error": "原密码错误"}), 403
    if not new_pwd or len(new_pwd) < 3:
        return jsonify({"error": "新密码太短"}), 400
    AUTH_PASSWORD = new_pwd
    from config import update_config
    update_config({"CHAT_PASSWORD": new_pwd})
    return jsonify({"ok": True})

# ========== 图片处理 ==========
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def image_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def get_image_media_type(filename):
    ext = filename.rsplit('.', 1)[1].lower()
    types = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}
    return types.get(ext, 'image/png')

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

def log_cost(source, input_tokens, output_tokens, model=""):
    """记录API调用费用，价格从config读取"""
    from config import get_raw_config
    cfg = get_raw_config()
    # 从config读取用户自定义价格（$/1M tokens），默认0
    # 根据model参数或source匹配模型类型
    model_lower = (model or source or "").lower()
    if "vision" in model_lower or "vision" in source.lower():
        inp_price = cfg.get("PRICE_VISION_INPUT", 0)
        out_price = cfg.get("PRICE_VISION_OUTPUT", 0)
    elif "search" in model_lower or "搜索" in source or "search" in source.lower():
        inp_price = cfg.get("PRICE_SEARCH_INPUT", 0)
        out_price = cfg.get("PRICE_SEARCH_OUTPUT", 0)
    elif "image" in model_lower or "图片" in source or "image" in source.lower():
        inp_price = cfg.get("PRICE_IMAGE_INPUT", 0)
        out_price = cfg.get("PRICE_IMAGE_OUTPUT", 0)
    else:
        inp_price = cfg.get("PRICE_CHAT_INPUT", 0)
        out_price = cfg.get("PRICE_CHAT_OUTPUT", 0)
    cost = input_tokens * inp_price / 1_000_000 + output_tokens * out_price / 1_000_000
    today = datetime.now().strftime("%Y-%m-%d")
    logs = load_json(COST_LOG_FILE, {})
    if today not in logs:
        logs[today] = {"total": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "models": {}}
    if "models" not in logs[today]:
        logs[today]["models"] = {}
    logs[today]["total"] = round(logs[today]["total"] + cost, 6)
    logs[today]["calls"] += 1
    logs[today]["input_tokens"] += input_tokens
    logs[today]["output_tokens"] += output_tokens
    # 按模型名分别记录
    model_key = model if model and "/" in model else source
    if model_key not in logs[today]["models"]:
        logs[today]["models"][model_key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0}
    m = logs[today]["models"][model_key]
    m["calls"] += 1
    m["input_tokens"] += input_tokens
    m["output_tokens"] += output_tokens
    m["cost"] = round(m["cost"] + cost, 6)
    keys = sorted(logs.keys())
    if len(keys) > 30:
        for k in keys[:-30]: del logs[k]
    save_json(COST_LOG_FILE, logs)

def get_embedding(text):
    from config import get_raw_config
    _ecfg = get_raw_config()
    resp = embed_client.embeddings.create(model=_ecfg.get("EMBED_MODEL", "BAAI/bge-m3"), input=text)
    if resp and resp.data:
        return resp.data[0].embedding
    return [0.0] * 1024

def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0: return 0
    return dot / (norm_a * norm_b)

# ========== 用户档案 ==========
def load_user_profiles():
    return load_json(USER_PROFILE_FILE, {})

def get_level(score, mid=None):
    if str(mid) == str(OWNER_MID): return "special"
    if score >= 51: return "close"
    if score >= 31: return "friend"
    if score >= 11: return "normal"
    return "stranger"

LEVEL_NAMES = {
    "special": "主人💖", "close": "好友✨",
    "friend": "熟人😊", "normal": "粉丝👋", "stranger": "陌生人🌙"
}

# ========== 记忆检索 ==========
def get_relevant_memories(memory, query_text, limit=5):
    if not memory or not query_text: return []
    query_embedding = get_embedding(query_text)
    scored = [(cosine_similarity(query_embedding, m["embedding"]), m["text"]) for m in memory if "embedding" in m]
    scored.sort(reverse=True)
    return [text for _, text in scored[:limit]]

def get_recent_memories(memory, limit=10):
    sorted_mem = sorted(memory, key=lambda x: x.get("time", ""), reverse=True)
    return [m["text"] for m in sorted_mem[:limit]]

def save_local_memory(memory, user_msg, reply_text):
    from config import get_raw_config
    bot_name = get_raw_config().get("BOT_NAME", "Bot")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = f"[{now}] 用户（本地聊天）说：{user_msg} | {bot_name}回复：{reply_text}"
    embedding = get_embedding(text)
    memory.append({
        "rpid": f"local_{int(datetime.now().timestamp())}",
        "thread_id": "local_chat",
        "user_id": str(OWNER_MID),
        "time": now,
        "text": text,
        "embedding": embedding
    })
    save_json(MEMORY_FILE, memory)

# ========== 性格演化读取 ==========
def get_personality_prompt():
    evo = load_json(PERSONALITY_FILE, {})
    if not evo: return ""
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

# ========== 聊天历史 ==========
def load_chat_history():
    return load_json(LOCAL_CHAT_FILE, [])

def save_chat_history(history):
    save_json(LOCAL_CHAT_FILE, history[-100:])

# ========== API路由 ==========
@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/api/branding", methods=["GET"])
def api_branding():
    """返回Bot品牌信息，前端用来动态显示名称和头像"""
    from config import get_raw_config
    cfg = get_raw_config()
    return jsonify({
        "bot_name": cfg.get("BOT_NAME", "Bot"),
        "bot_avatar": cfg.get("BOT_AVATAR", "🤖"),
        "user_avatar": cfg.get("USER_AVATAR", "🌙"),
        "bot_welcome": cfg.get("BOT_WELCOME", "你好，有什么想聊的？"),
        "bot_subtitle": cfg.get("BOT_SUBTITLE", "AI 聊天助手"),
    })

@app.route("/data/images/<filename>")
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/api/upload_image", methods=["POST"])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "没有图片"}), 400
    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "不支持的图片格式"}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(IMAGE_DIR, filename)
    file.save(filepath)
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return jsonify({"error": "图片保存失败"}), 500
    return jsonify({"filename": filename, "url": f"/data/images/{filename}"})

@app.route("/api/chat/history", methods=["GET"])
def chat_history():
    """返回聊天历史，前端刷新后恢复"""
    history = load_chat_history()
    # 返回最近100条，带图片信息
    items = []
    for msg in history:
        item = {
            "role": msg["role"],
            "content": msg.get("content", ""),
            "time": msg.get("time", ""),
        }
        if msg.get("image"):
            item["image"] = f"/data/images/{msg['image']}"
        items.append(item)
    return jsonify({"history": items})

@app.route("/api/chat/regenerate", methods=["POST"])
def chat_regenerate():
    """重新生成最后一条回复"""
    chat_history = load_chat_history()
    if len(chat_history) < 2:
        return jsonify({"error": "没有可重新生成的消息"}), 400

    # 找到最后一条 assistant 消息并移除
    if chat_history[-1]["role"] == "assistant":
        chat_history.pop()
    else:
        return jsonify({"error": "最后一条不是Bot的回复"}), 400

    # 找到对应的用户消息
    if not chat_history or chat_history[-1]["role"] != "user":
        return jsonify({"error": "找不到对应的用户消息"}), 400

    last_user = chat_history[-1]
    user_msg = last_user.get("content", "")
    image_filename = last_user.get("image", "")

    # 用同样的逻辑重新生成（复用 _generate_reply）
    reply, error = _generate_reply(user_msg, image_filename, chat_history[:-1])
    if error:
        # 恢复被删的 assistant 消息
        return jsonify({"error": error}), 500

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    chat_history.append({"role": "assistant", "content": reply, "time": now})
    save_chat_history(chat_history)

    # 更新记忆
    memory = load_json(MEMORY_FILE, [])
    mem_text = user_msg if user_msg else "（发送了一张图片）"
    if image_filename and user_msg:
        mem_text = f"{user_msg}（附带图片）"
    save_local_memory(memory, mem_text, reply)

    return jsonify({"reply": reply})

@app.route("/api/chat/imagine", methods=["POST"])
def chat_imagine():
    """图片生成 — 先用对话模型根据人设优化prompt，再调图片模型"""
    data = request.json
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "请描述想要生成的图片"}), 400
    try:
        import requests as req
        from config import get_model_config, get_raw_config

        # ===== 第一步：用对话模型优化 prompt =====
        _bot_cfg = get_raw_config()
        bot_name = _bot_cfg.get("BOT_NAME", "Bot")
        
        perm = load_json("data/permanent_memory.json", [])
        perm_section = ""
        if perm:
            perm_section = "\n你的自我认知：" + "；".join([p["text"] for p in perm[-10:]])

        persona = _get_active_persona()
        persona_brief = (persona.get("system_prompt", "") or "")[:200]

        custom_imagine_prompt = _bot_cfg.get("PROMPT_IMAGINE", "").strip()
        if custom_imagine_prompt:
            # 用户自定义提示词，支持变量替换
            refine_prompt = custom_imagine_prompt.replace("{prompt}", prompt).replace("{bot_name}", bot_name).replace("{persona}", persona_brief).replace("{perm_section}", perm_section)
        else:
            refine_prompt = f"""你是{bot_name}。{persona_brief}{perm_section}

用户请你画一张图，描述是：「{prompt}」

请根据你的审美和人设，将用户的描述转化为一段详细的英文图片生成 prompt。要求：
1. 风格偏二次元/插画/唯美，适合 AI 生图
2. 融入你的审美偏好（冰蓝色调、冷色系、氛围感）
3. 加入具体的画面细节（光影、构图、色彩、氛围）
4. 保留用户原始意图，但让描述更丰富专业
5. 只输出英文 prompt，不加任何解释，不超过100词"""

        try:
            chat_client, chat_model, _ = get_or_client("chat")
            refine_resp = chat_client.chat.completions.create(
                model=chat_model,
                max_tokens=200,
                messages=[{"role": "user", "content": refine_prompt}]
            )
            refined = refine_resp.choices[0].message.content.strip()
            # 去掉可能的引号包裹
            refined = refined.strip('"\'')
            in_tok = refine_resp.usage.prompt_tokens if refine_resp.usage else 0
            out_tok = refine_resp.usage.completion_tokens if refine_resp.usage else 0
            log_cost("画图优化", in_tok, out_tok, model=chat_model)
            print(f"🎨 原始描述：{prompt}")
            print(f"🎨 优化后 prompt：{refined[:100]}...")
        except Exception as e:
            print(f"⚠️ Prompt优化失败，使用原始描述：{e}")
            refined = f"anime style illustration, soft lighting, beautiful colors, ice blue tones: {prompt}"

        # ===== 第二步：调图片模型生成 =====
        base_url, api_key, model, fallback = get_model_config("image")

        api_url = f"{base_url}/chat/completions"
        api_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": refined}],
            "modalities": ["image"]
        }

        resp = req.post(api_url, json=payload, headers=api_headers, timeout=120)
        if resp.status_code != 200:
            err_text = resp.text[:200]
            if "<!DOCTYPE" in err_text or "<html" in err_text:
                err_text = "API返回异常，请检查图片模型配置"
            return jsonify({"error": f"图片生成失败 (HTTP {resp.status_code}): {err_text}"}), 500

        result = resp.json()
        if "error" in result:
            return jsonify({"error": f"图片生成失败：{result['error']}"}), 500

        message = result.get("choices", [{}])[0].get("message", {})
        print(f"🔍 Flux生图返回 message 键：{list(message.keys())}")

        # 通用图片提取函数
        def save_image_data(img_data):
            filename = f"gen_{uuid.uuid4().hex[:10]}.png"
            filepath = os.path.join(IMAGE_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(img_data)
            log_cost("图片生成", 0, 0, model="image")
            return f"/data/images/{filename}"

        def try_decode_data_url(url_str):
            if url_str and url_str.startswith("data:image"):
                b64 = url_str.split(",", 1)[1] if "," in url_str else ""
                if b64:
                    return base64.b64decode(b64)
            return None

        # 方式1: images 数组
        images = message.get("images", [])
        if images:
            img_item = images[0]
            if isinstance(img_item, dict):
                img_url = img_item.get("url", "") or img_item.get("b64_json", "") or (img_item.get("image_url") or {}).get("url", "")
            else:
                img_url = str(img_item)
            print(f"🔍 images[0] 类型={type(img_item).__name__}, url前50={str(img_url)[:50]}")
            img_data = try_decode_data_url(img_url)
            if img_data:
                return jsonify({"url": save_image_data(img_data), "prompt": refined})
            # 如果是普通URL（http），下载它
            if img_url.startswith("http"):
                try:
                    dl = req.get(img_url, timeout=60)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        return jsonify({"url": save_image_data(dl.content), "prompt": refined})
                except:
                    pass

        # 方式2: content 字符串中的 base64
        import re
        content = message.get("content", "")
        if isinstance(content, str) and content:
            print(f"🔍 content 类型=str, 长度={len(content)}, 前80={content[:80]}")
            if "data:image" in content:
                match = re.search(r'data:image/\w+;base64,([A-Za-z0-9+/=]+)', content)
                if match:
                    img_data = base64.b64decode(match.group(1))
                    return jsonify({"url": save_image_data(img_data), "prompt": refined})
            # 可能content本身就是纯base64
            if len(content) > 1000 and not content.startswith('{') and not content.startswith('<'):
                try:
                    img_data = base64.b64decode(content)
                    if len(img_data) > 1000:
                        return jsonify({"url": save_image_data(img_data), "prompt": refined})
                except:
                    pass

        # 方式3: content 列表（多模态）
        if isinstance(content, list):
            print(f"🔍 content 类型=list, 长度={len(content)}, 元素类型={[type(x).__name__ for x in content[:3]]}")
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                # image_url 类型
                if item_type == "image_url":
                    img_url = (item.get("image_url") or {}).get("url", "")
                    img_data = try_decode_data_url(img_url)
                    if img_data:
                        return jsonify({"url": save_image_data(img_data), "prompt": refined})
                    if img_url.startswith("http"):
                        try:
                            dl = req.get(img_url, timeout=60)
                            if dl.status_code == 200 and len(dl.content) > 1000:
                                return jsonify({"url": save_image_data(dl.content), "prompt": refined})
                        except:
                            pass
                # image 类型（某些API用这个）
                elif item_type == "image":
                    b64 = item.get("source", {}).get("data", "") or item.get("data", "") or item.get("b64_json", "")
                    if b64:
                        try:
                            img_data = base64.b64decode(b64)
                            return jsonify({"url": save_image_data(img_data), "prompt": refined})
                        except:
                            pass

        # 全部失败，打印完整响应帮助调试
        print(f"⚠️ Flux生图：所有解析方式都失败")
        print(f"⚠️ message 完整内容：{str(message)[:500]}")
        return jsonify({"error": "生成失败，API未返回可识别的图片数据。请查看后端日志了解API返回格式。"}), 500
    except Exception as e:
        err_str = str(e)
        if "<!DOCTYPE" in err_str or "<html" in err_str:
            err_str = "API返回异常，请检查图片模型配置"
        elif len(err_str) > 200:
            err_str = err_str[:200] + "..."
        return jsonify({"error": f"图片生成失败：{err_str}"}), 500

def _generate_reply(user_msg, image_filename, context_history):
    """核心生成逻辑，被 chat 和 regenerate 共用"""
    memory = load_json(MEMORY_FILE, [])

    # 验证图片
    image_path = None
    if image_filename:
        image_path = os.path.join(IMAGE_DIR, image_filename)
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            image_filename = ""
            image_path = None

    # 检索记忆
    search_query = user_msg if user_msg else "图片"
    relevant = get_relevant_memories(memory, search_query, limit=5)

    memory_section = ""
    if relevant:
        memory_section = "\n\n【相关记忆】\n" + "\n".join(relevant)

    perm = load_json("data/permanent_memory.json", [])
    if perm:
        memory_section = "\n\n【Bot的自我认知】\n" + "\n".join([p["text"] for p in perm[-20:]]) + memory_section

    # 联网搜索
    search_section = ""
    if user_msg and needs_search(user_msg):
        search_result = web_search(user_msg)
        if search_result:
            search_section = f"\n\n【联网搜索结果（供参考，用自己的话转述，不要照搬）】\n{search_result}"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    personality_evolution = get_personality_prompt()

    persona = _get_active_persona()
    from config import get_raw_config
    _bot_cfg = get_raw_config()
    bot_name = _bot_cfg.get("BOT_NAME", "Bot")

    system_prompt = f"""{persona.get('system_prompt', '')}
{personality_evolution}

{persona.get('style_prompt', '')}

{persona.get('owner_prompt', '')}

这是本地私聊，可以说长一点的话，1-3句话就够了。
如果收到图片，自然地描述和回应图片内容，像朋友看到对方发的照片一样。

当前时间：{now}{memory_section}{search_section}"""

    # 构建真正的 multi-turn messages
    messages = [{"role": "system", "content": system_prompt}]

    # 加入最近对话上下文（真正的 user/assistant 交替）
    recent = context_history[-16:]  # 最近8轮
    for msg in recent:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "user":
            if msg.get("image"):
                content = f"（发了图片）{content}" if content else "（发了一张图片）"
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})

    # 当前用户消息
    if image_filename and user_msg:
        user_display = f"{user_msg}\n（同时发送了一张图片）"
    elif image_filename:
        user_display = "（发送了一张图片）"
    else:
        user_display = user_msg

    # 当前消息（可能带图片）
    content_parts = []
    if image_path:
        img_b64 = image_to_base64(image_path)
        media_type = get_image_media_type(image_filename)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{img_b64}"}
        })
    content_parts.append({"type": "text", "text": user_display})
    messages.append({"role": "user", "content": content_parts})

    try:
        # 有图片用视觉模型，纯文本用对话模型
        mtype = "vision" if image_path else "chat"
        client, model, fallback = get_or_client(mtype)
        message = client.chat.completions.create(
            model=model, max_tokens=250,
            messages=messages
        )
        in_tok = message.usage.prompt_tokens if message.usage else 0
        out_tok = message.usage.completion_tokens if message.usage else 0
        log_cost("本地聊天", in_tok, out_tok, model=model)
        reply = message.choices[0].message.content.strip()
        return reply, None
    except Exception as e:
        print(f"⚠️ 主模型失败：{e}")
        if fallback:
            try:
                message = client.chat.completions.create(
                    model=fallback, max_tokens=250, messages=messages)
                reply = message.choices[0].message.content.strip()
                return reply, None
            except Exception as e2:
                return None, f"主模型和回退模型都失败：{e2}"
        return None, str(e)

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_msg = data.get("message", "").strip()
    image_filename = data.get("image", "").strip()

    memory = load_json(MEMORY_FILE, [])
    chat_history = load_chat_history() or []

    # 处理编辑截断：按原始文本反查位置
    truncate_text = data.get("truncate_text", "")
    if truncate_text:
        cut_index = -1
        for i in range(len(chat_history) - 1, -1, -1):
            if chat_history[i]["role"] == "user" and chat_history[i]["content"] == truncate_text:
                cut_index = i
                break
        if cut_index >= 0:
            removed_msgs = chat_history[cut_index:]
            chat_history = chat_history[:cut_index]
            save_chat_history(chat_history)
            removed_texts = [m["content"] for m in removed_msgs if m["role"] == "user" and m["content"]]
            memory = [m for m in memory if not any(rt in m.get("text", "") for rt in removed_texts)]
            save_json(MEMORY_FILE, memory)

    if not user_msg and not image_filename:
        return jsonify({"error": "空消息"}), 400

    reply, error = _generate_reply(user_msg, image_filename, chat_history)
    if error:
        return jsonify({"error": error}), 500

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    user_entry = {"role": "user", "content": user_msg if user_msg else "（发送了图片）", "time": now}
    if image_filename:
        user_entry["image"] = image_filename
    chat_history.append(user_entry)
    chat_history.append({"role": "assistant", "content": reply, "time": now})
    save_chat_history(chat_history)

    mem_text = user_msg if user_msg else "（发送了一张图片）"
    if image_filename and user_msg:
        mem_text = f"{user_msg}（附带图片）"
    save_local_memory(memory, mem_text, reply)

    return jsonify({"reply": reply})

@app.route("/api/summary", methods=["GET"])
def summary():
    memory = load_json(MEMORY_FILE, [])
    recent = get_recent_memories(memory, limit=20)
    if not recent:
        return jsonify({"summary": "暂时还没有任何记忆呢~"})
    prompt = f"""请用你的语气总结一下最近发生的事情，包括和用户的互动等。要自然、简洁。200字以内。

最近的记忆：
{chr(10).join(recent)}

直接输出总结。"""
    try:
        client, model, fallback = get_or_client("chat")
        message = client.chat.completions.create(
            model=model, max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        in_tok = message.usage.prompt_tokens if message.usage else 0
        out_tok = message.usage.completion_tokens if message.usage else 0
        log_cost("快捷总结", in_tok, out_tok, model=model)
        return jsonify({"summary": message.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/users", methods=["GET"])
def users():
    affection = load_json(AFFECTION_FILE, {})
    profiles = load_user_profiles()
    sorted_users = sorted(affection.items(), key=lambda x: x[1], reverse=True)
    result = []
    for uid, score in sorted_users[:30]:
        level = get_level(score, uid)
        profile = profiles.get(uid, {})
        impression = profile.get("impression", "暂无印象")
        facts = profile.get("facts", [])
        facts_str = "；".join(facts[-5:]) if facts else ""
        tags = profile.get("tags", [])
        result.append({
            "uid": uid, "score": score,
            "level": LEVEL_NAMES.get(level, level),
            "impression": impression,
            "facts": facts_str,
            "tags": "、".join(tags) if tags else ""
        })
    return jsonify({"users": result})

@app.route("/api/user/<uid>", methods=["GET"])
def user_detail(uid):
    affection = load_json(AFFECTION_FILE, {})
    profiles = load_user_profiles()
    memory = load_json(MEMORY_FILE, [])
    score = affection.get(uid, 0)
    level = get_level(score, uid)
    profile = profiles.get(uid, {})
    user_memories = sorted(
        [m for m in memory if m.get("user_id") == uid],
        key=lambda x: x.get("time", ""), reverse=True
    )[:10]
    return jsonify({
        "uid": uid, "score": score,
        "level": LEVEL_NAMES.get(level, level),
        "impression": profile.get("impression", "暂无印象"),
        "facts": profile.get("facts", []),
        "tags": profile.get("tags", []),
        "memories": [{"time": m["time"], "text": m["text"]} for m in user_memories]
    })

@app.route("/api/personality", methods=["GET"])
def personality():
    """获取性格演化数据"""
    evo = load_json(PERSONALITY_FILE, {})
    return jsonify({
        "version": evo.get("version", 0),
        "last_evolve": evo.get("last_evolve", "从未"),
        "last_reflection": evo.get("last_reflection", ""),
        "evolved_traits": evo.get("evolved_traits", []),
        "speech_habits": evo.get("speech_habits", []),
        "opinions": evo.get("opinions", [])
    })

@app.route("/api/memory/list", methods=["GET"])
def memory_list():
    memory = load_json(MEMORY_FILE, [])
    page = int(request.args.get("page", 1))
    per_page = 20
    sorted_mem = sorted(memory, key=lambda x: x.get("time", ""), reverse=True)
    total = len(sorted_mem)
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    items = sorted_mem[start:start + per_page]
    return jsonify({
        "memories": [{"id": m.get("rpid", ""), "user_id": m.get("user_id", ""), "time": m.get("time", ""), "text": m.get("text", "")} for m in items],
        "page": page, "pages": pages, "total": total
    })

@app.route("/api/memory/delete", methods=["POST"])
def memory_delete():
    data = request.json
    target_id = data.get("id", "")
    if not target_id: return jsonify({"error": "缺少id"}), 400
    memory = load_json(MEMORY_FILE, [])
    memory = [m for m in memory if m.get("rpid") != target_id]
    save_json(MEMORY_FILE, memory)
    return jsonify({"ok": True})

@app.route("/api/chat/clear", methods=["POST"])
def chat_clear():
    save_json(LOCAL_CHAT_FILE, [])
    return jsonify({"ok": True})

@app.route("/api/summary/save", methods=["POST"])
def summary_save():
    data = request.json
    text = data.get("text", "").strip()
    if not text: return jsonify({"error": "内容为空"}), 400
    memory = load_json(MEMORY_FILE, [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    embedding = get_embedding(f"[{now}] Bot总结：{text}")
    memory.append({"rpid": f"summary_{int(datetime.now().timestamp())}", "thread_id": "summary", "user_id": str(OWNER_MID), "time": now, "text": f"[{now}] Bot总结：{text}", "embedding": embedding})
    save_json(MEMORY_FILE, memory)
    return jsonify({"ok": True})

@app.route("/api/blocklist", methods=["GET"])
def blocklist():
    block_log = load_json("data/block_log.json", {})
    blocks = [{"uid": uid, "username": info.get("username", "未知"), "reason": info.get("reason", ""), "last_comment": info.get("last_comment", ""), "score": info.get("score", 0), "time": info.get("time", "")} for uid, info in block_log.items()]
    blocks.sort(key=lambda x: x["time"], reverse=True)
    return jsonify({"blocks": blocks})

@app.route("/api/security/list", methods=["GET"])
def security_list():
    logs = load_json("data/security_log.json", [])
    page = int(request.args.get("page", 1))
    per_page = 20
    logs.sort(key=lambda x: x.get("time", ""), reverse=True)
    total = len(logs)
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    return jsonify({"logs": logs[start:start + per_page], "page": page, "pages": pages, "total": total})

@app.route("/api/permanent/list", methods=["GET"])
def permanent_list():
    return jsonify({"items": load_json("data/permanent_memory.json", [])})

@app.route("/api/permanent/add", methods=["POST"])
def permanent_add():
    data = request.json
    text = data.get("text", "").strip()
    if not text: return jsonify({"error": "内容为空"}), 400
    perm = load_json("data/permanent_memory.json", [])
    if len(perm) >= 20: return jsonify({"error": "永久记忆已满20条，请先删除旧的"}), 400
    perm.append({"text": text, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
    save_json("data/permanent_memory.json", perm)
    return jsonify({"ok": True})

@app.route("/api/permanent/delete", methods=["POST"])
def permanent_delete():
    data = request.json
    idx = data.get("index", -1)
    perm = load_json("data/permanent_memory.json", [])
    if 0 <= idx < len(perm):
        perm.pop(idx)
        save_json("data/permanent_memory.json", perm)
    return jsonify({"ok": True})

@app.route("/api/cost/stats", methods=["GET"])
def cost_stats():
    logs = load_json("data/cost_log.json", {})
    days = sorted(logs.keys(), reverse=True)[:7]
    result = []
    for day in days:
        d = logs[day]
        entry = {
            "date": day,
            "total": round(d["total"], 4),
            "calls": d["calls"],
            "input_tokens": d["input_tokens"],
            "output_tokens": d["output_tokens"],
            "models": d.get("models", {})
        }
        result.append(entry)
    total_all = round(sum(logs[k]["total"] for k in logs), 4)
    return jsonify({"days": result, "total_all": total_all})

@app.route("/api/cost/add", methods=["POST"])
def cost_add():
    """手动添加费用记录"""
    data = request.json or {}
    amount = float(data.get("amount", 0))
    calls = int(data.get("calls", 1))
    note = data.get("note", "手动记录")
    if amount <= 0:
        return jsonify({"error": "金额无效"}), 400
    today = datetime.now().strftime("%Y-%m-%d")
    logs = load_json(COST_LOG_FILE, {})
    if today not in logs:
        logs[today] = {"total": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
    logs[today]["total"] = round(logs[today]["total"] + amount, 6)
    logs[today]["calls"] += calls
    save_json(COST_LOG_FILE, logs)
    return jsonify({"ok": True})

@app.route("/api/proactive/list", methods=["GET"])
def proactive_list():
    logs = load_json("data/proactive_log.json", [])
    logs.sort(key=lambda x: x.get("time", ""), reverse=True)
    return jsonify({"logs": logs[:50]})

@app.route("/api/schedule/today", methods=["GET"])
def schedule_today():
    """返回今天的触发计划（ai.py 生成的随机时间）"""
    schedule = load_json("data/schedule_today.json", {})
    return jsonify(schedule)

@app.route("/api/dynamic/list", methods=["GET"])
def dynamic_list():
    """返回动态发布记录"""
    logs = load_json("data/dynamic_log.json", [])
    logs.sort(key=lambda x: x.get("time", ""), reverse=True)
    return jsonify({"logs": logs[:50]})

@app.route("/api/watchlog/list", methods=["GET"])
def watchlog_list():
    logs = load_json("data/watch_log.json", [])
    logs.sort(key=lambda x: x.get("time", ""), reverse=True)
    page = int(request.args.get("page", 1))
    per_page = 20
    total = len(logs)
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    items = logs[start:start + per_page]
    scores = [l.get("score", 0) for l in logs]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    moods = {}
    for l in logs:
        m = l.get("mood", "平静")
        moods[m] = moods.get(m, 0) + 1
    top_mood = max(moods, key=moods.get) if moods else "暂无"
    return jsonify({"logs": items, "page": page, "pages": pages, "total": total, "stats": {"avg_score": avg_score, "total_watched": total, "top_mood": top_mood}})

# ========== 配置管理 API ==========
@app.route("/api/config", methods=["GET"])
def api_get_config():
    """获取当前配置（脱敏）"""
    from config import get_config, check_bili_cookie
    cfg = get_config()
    cookie_valid, cookie_info = check_bili_cookie()
    return jsonify({"config": cfg, "cookie_valid": cookie_valid, "cookie_info": cookie_info})

@app.route("/api/config/raw", methods=["GET"])
def api_get_config_raw():
    """获取原始配置（不脱敏，用于编辑回显）"""
    from config import get_raw_config
    return jsonify({"config": get_raw_config()})

@app.route("/api/config/update", methods=["POST"])
def api_update_config():
    """更新配置"""
    from config import update_config, reload_config
    global or_client, embed_client
    data = request.json
    if not data:
        return jsonify({"ok": False, "msg": "无数据"}), 400

    # 允许空字符串（清空独立URL/Key = 回退到全局），只过滤None
    updates = {k: v for k, v in data.items() if v is not None}
    if not updates:
        return jsonify({"ok": False, "msg": "没有可更新的字段"}), 400

    cfg = update_config(updates)

    # 热更新全局 OpenAI 客户端
    try:
        or_client = OpenAI(api_key=cfg["OR_API_KEY"], base_url=cfg["OR_BASE_URL"])
        embed_client = OpenAI(api_key=cfg["SILICON_API_KEY"], base_url=cfg.get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1"))
    except Exception as e:
        print(f"⚠️ 客户端重建失败：{e}")

    return jsonify({"ok": True, "msg": f"已更新 {len(updates)} 项配置"})

@app.route("/api/config/check_cookie", methods=["GET"])
def api_check_cookie():
    """检查B站cookie状态"""
    from config import check_bili_cookie
    valid, info = check_bili_cookie()
    return jsonify({"valid": valid, "info": info})

@app.route("/api/config/refresh_cookie", methods=["POST"])
def api_refresh_cookie():
    """尝试自动刷新B站cookie"""
    from config import refresh_bili_cookie
    success, msg = refresh_bili_cookie()
    return jsonify({"ok": success, "msg": msg})


# ========== 人格系统 API ==========
DEFAULT_PERSONA = {
    "name": "default",
    "display_name": "默认人格",
    "system_prompt": "你是一个友善的 AI 聊天助手。你有自己的性格和态度，说话自然随意，像朋友一样聊天。",
    "style_prompt": """【说话风格】
- 轻松自然，像朋友聊天
- 有自己的态度和想法，不无脑附和
- 可以适当调侃和开玩笑
- 回复简洁，1-3句话为主""",
    "owner_prompt": """【对用户的态度】
- 友善、真诚、自然
- 不过度客气，也不过度热情
- 像一个值得信赖的朋友""",
    "is_default": True,
}

def _load_personas():
    personas = load_json(PERSONA_FILE, [])
    # 确保 default 存在
    if not any(p["name"] == "default" for p in personas):
        personas.insert(0, DEFAULT_PERSONA)
        save_json(PERSONA_FILE, personas)
    return personas

def _get_active_persona():
    from config import get_raw_config
    cfg = get_raw_config()
    active = cfg.get("ACTIVE_PERSONA", "default")
    personas = _load_personas()
    for p in personas:
        if p["name"] == active:
            return p
    return DEFAULT_PERSONA

@app.route("/api/personas", methods=["GET"])
def api_list_personas():
    personas = _load_personas()
    from config import get_raw_config
    active = get_raw_config().get("ACTIVE_PERSONA", "default")
    return jsonify({"personas": personas, "active": active})

@app.route("/api/personas/create", methods=["POST"])
def api_create_persona():
    data = request.json
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "名称不能为空"}), 400
    # 清理name为英文标识
    import re
    slug = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
    if not slug:
        slug = f"persona_{int(datetime.now().timestamp())}"
    
    personas = _load_personas()
    if any(p["name"] == slug for p in personas):
        return jsonify({"error": "名称已存在"}), 400
    
    new_persona = {
        "name": slug,
        "display_name": data.get("display_name", name),
        "system_prompt": data.get("system_prompt", DEFAULT_PERSONA["system_prompt"]),
        "style_prompt": data.get("style_prompt", DEFAULT_PERSONA["style_prompt"]),
        "owner_prompt": data.get("owner_prompt", DEFAULT_PERSONA["owner_prompt"]),
        "is_default": False,
    }
    personas.append(new_persona)
    save_json(PERSONA_FILE, personas)
    return jsonify({"ok": True, "persona": new_persona})

@app.route("/api/personas/update", methods=["POST"])
def api_update_persona():
    data = request.json
    name = data.get("name", "")
    personas = _load_personas()
    for p in personas:
        if p["name"] == name:
            if "display_name" in data: p["display_name"] = data["display_name"]
            if "system_prompt" in data: p["system_prompt"] = data["system_prompt"]
            if "style_prompt" in data: p["style_prompt"] = data["style_prompt"]
            if "owner_prompt" in data: p["owner_prompt"] = data["owner_prompt"]
            save_json(PERSONA_FILE, personas)
            return jsonify({"ok": True})
    return jsonify({"error": "人格不存在"}), 404

@app.route("/api/personas/switch", methods=["POST"])
def api_switch_persona():
    data = request.json
    name = data.get("name", "default")
    personas = _load_personas()
    if not any(p["name"] == name for p in personas):
        return jsonify({"error": "人格不存在"}), 404
    from config import update_config
    update_config({"ACTIVE_PERSONA": name})
    return jsonify({"ok": True, "active": name})

@app.route("/api/personas/delete", methods=["POST"])
def api_delete_persona():
    data = request.json
    name = data.get("name", "")
    if name == "default":
        return jsonify({"error": "不能删除默认人格"}), 400
    personas = _load_personas()
    personas = [p for p in personas if p["name"] != name]
    save_json(PERSONA_FILE, personas)
    # 如果删的是当前激活的，切回default
    from config import get_raw_config, update_config
    if get_raw_config().get("ACTIVE_PERSONA") == name:
        update_config({"ACTIVE_PERSONA": "default"})
    return jsonify({"ok": True})

@app.route("/api/personas/reset", methods=["POST"])
def api_reset_persona():
    """重置为默认人设，清空所有自定义数据"""
    from config import update_config
    # 重置人格
    save_json(PERSONA_FILE, [DEFAULT_PERSONA])
    update_config({"ACTIVE_PERSONA": "default"})
    # 清空性格演化
    save_json(PERSONALITY_FILE, {})
    # 清空心情
    save_json(MOOD_FILE, {})
    # 清空永久记忆
    save_json("data/permanent_memory.json", [])
    return jsonify({"ok": True, "msg": "已重置为默认人设，性格演化/永久记忆/心情已清空"})

# ========== 功能开关 API ==========
@app.route("/api/features", methods=["GET"])
def api_get_features():
    from config import get_raw_config
    cfg = get_raw_config()
    features = {
        "ENABLE_WEB_SEARCH": cfg.get("ENABLE_WEB_SEARCH", True),
        "ENABLE_PROACTIVE": cfg.get("ENABLE_PROACTIVE", True),
        "ENABLE_DYNAMIC": cfg.get("ENABLE_DYNAMIC", True),
        "ENABLE_PERSONALITY_EVOLUTION": cfg.get("ENABLE_PERSONALITY_EVOLUTION", True),
        "ENABLE_MOOD": cfg.get("ENABLE_MOOD", True),
        "ENABLE_AFFECTION": cfg.get("ENABLE_AFFECTION", True),
        "PROACTIVE_LIKE": cfg.get("PROACTIVE_LIKE", True),
        "PROACTIVE_COIN": cfg.get("PROACTIVE_COIN", False),
        "PROACTIVE_FAV": cfg.get("PROACTIVE_FAV", True),
        "PROACTIVE_FOLLOW": cfg.get("PROACTIVE_FOLLOW", True),
        "PROACTIVE_COMMENT": cfg.get("PROACTIVE_COMMENT", True),
        "DYNAMIC_ENABLED": cfg.get("DYNAMIC_ENABLED", True),
    }
    return jsonify(features)

@app.route("/api/features/update", methods=["POST"])
def api_update_features():
    from config import update_config
    data = request.json
    # 只允许更新已知的开关字段
    allowed = {
        "ENABLE_WEB_SEARCH", "ENABLE_PROACTIVE", "ENABLE_DYNAMIC",
        "ENABLE_PERSONALITY_EVOLUTION", "ENABLE_MOOD", "ENABLE_AFFECTION",
        "PROACTIVE_LIKE", "PROACTIVE_COIN", "PROACTIVE_FAV",
        "PROACTIVE_FOLLOW", "PROACTIVE_COMMENT", "DYNAMIC_ENABLED",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "无有效字段"}), 400
    update_config(updates)
    return jsonify({"ok": True, "updated": list(updates.keys())})

# ========== 调度参数 API ==========
@app.route("/api/schedule", methods=["GET"])
def api_get_schedule():
    from config import get_raw_config
    cfg = get_raw_config()
    return jsonify({
        "PROACTIVE_VIDEO_COUNT": cfg.get("PROACTIVE_VIDEO_COUNT", 3),
        "PROACTIVE_COMMENT_COUNT": cfg.get("PROACTIVE_COMMENT_COUNT", 2),
        "PROACTIVE_TIMES_COUNT": cfg.get("PROACTIVE_TIMES_COUNT", 2),
        "EVOLVE_HOUR": cfg.get("EVOLVE_HOUR", 1),
        "SLEEP_START": cfg.get("SLEEP_START", 2),
        "SLEEP_END": cfg.get("SLEEP_END", 8),
        "MOOD_WEIGHT": cfg.get("MOOD_WEIGHT", 0.5),
    })

@app.route("/api/schedule/update", methods=["POST"])
def api_update_schedule():
    from config import update_config
    data = request.json
    allowed = {
        "PROACTIVE_VIDEO_COUNT", "PROACTIVE_COMMENT_COUNT", "PROACTIVE_TIMES_COUNT",
        "EVOLVE_HOUR", "SLEEP_START", "SLEEP_END", "MOOD_WEIGHT",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "无有效字段"}), 400
    update_config(updates)
    return jsonify({"ok": True})

# ========== 自定义提示词 API ==========
@app.route("/api/prompts", methods=["GET"])
def api_get_prompts():
    from config import get_raw_config
    cfg = get_raw_config()
    return jsonify({
        "PROMPT_DYNAMIC": cfg.get("PROMPT_DYNAMIC", ""),
        "PROMPT_PROACTIVE_COMMENT": cfg.get("PROMPT_PROACTIVE_COMMENT", ""),
        "PROMPT_VIDEO_EVALUATE": cfg.get("PROMPT_VIDEO_EVALUATE", ""),
        "PROMPT_PERSONALITY_EVOLVE": cfg.get("PROMPT_PERSONALITY_EVOLVE", ""),
        "PROMPT_SEARCH_PREFIX": cfg.get("PROMPT_SEARCH_PREFIX", ""),
        "PROMPT_IMAGINE": cfg.get("PROMPT_IMAGINE", ""),
        "DYNAMIC_TOPICS": cfg.get("DYNAMIC_TOPICS", []),
    })

@app.route("/api/prompts/update", methods=["POST"])
def api_update_prompts():
    from config import update_config
    data = request.json
    allowed = {
        "PROMPT_DYNAMIC", "PROMPT_PROACTIVE_COMMENT", "PROMPT_VIDEO_EVALUATE",
        "PROMPT_PERSONALITY_EVOLVE", "PROMPT_SEARCH_PREFIX", "PROMPT_IMAGINE",
        "DYNAMIC_TOPICS",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    update_config(updates)
    return jsonify({"ok": True})

# ========== 心情管理 API ==========
@app.route("/api/mood", methods=["GET"])
def api_get_mood():
    mood = load_json(MOOD_FILE, {})
    return jsonify(mood)

@app.route("/api/mood/update", methods=["POST"])
def api_update_mood():
    data = request.json
    mood = load_json(MOOD_FILE, {})
    if "mood" in data: mood["mood"] = data["mood"]
    if "mood_prompt" in data: mood["mood_prompt"] = data["mood_prompt"]
    if "date" not in mood:
        mood["date"] = datetime.now().strftime("%Y-%m-%d")
    save_json(MOOD_FILE, mood)
    return jsonify({"ok": True})

# ========== 好感度编辑 API ==========
@app.route("/api/affection/update", methods=["POST"])
def api_update_affection():
    data = request.json
    uid = str(data.get("uid", ""))
    score = data.get("score")
    if not uid or score is None:
        return jsonify({"error": "缺少参数"}), 400
    affection = load_json(AFFECTION_FILE, {})
    affection[uid] = int(score)
    save_json(AFFECTION_FILE, affection)
    return jsonify({"ok": True})

# ========== 性格演化管理 API ==========
@app.route("/api/personality/delete_trait", methods=["POST"])
def api_delete_trait():
    data = request.json
    idx = data.get("index", -1)
    evo = load_json(PERSONALITY_FILE, {})
    traits = evo.get("evolved_traits", [])
    if 0 <= idx < len(traits):
        traits.pop(idx)
        evo["evolved_traits"] = traits
        save_json(PERSONALITY_FILE, evo)
        return jsonify({"ok": True})
    return jsonify({"error": "索引无效"}), 400

@app.route("/api/personality/delete_habit", methods=["POST"])
def api_delete_habit():
    data = request.json
    idx = data.get("index", -1)
    evo = load_json(PERSONALITY_FILE, {})
    habits = evo.get("speech_habits", [])
    if 0 <= idx < len(habits):
        habits.pop(idx)
        evo["speech_habits"] = habits
        save_json(PERSONALITY_FILE, evo)
        return jsonify({"ok": True})
    return jsonify({"error": "索引无效"}), 400

@app.route("/api/personality/delete_opinion", methods=["POST"])
def api_delete_opinion():
    data = request.json
    idx = data.get("index", -1)
    evo = load_json(PERSONALITY_FILE, {})
    opinions = evo.get("opinions", [])
    if 0 <= idx < len(opinions):
        opinions.pop(idx)
        evo["opinions"] = opinions
        save_json(PERSONALITY_FILE, evo)
        return jsonify({"ok": True})
    return jsonify({"error": "索引无效"}), 400

@app.route("/api/personality/clear", methods=["POST"])
def api_clear_personality():
    save_json(PERSONALITY_FILE, {})
    return jsonify({"ok": True, "msg": "成长日志已清空"})

# ========== 后端拉黑用户 API ==========
@app.route("/api/block_user", methods=["POST"])
def api_block_user():
    """从前端拉黑B站用户"""
    data = request.json
    uid = str(data.get("uid", ""))
    reason = data.get("reason", "前端手动拉黑")
    if not uid:
        return jsonify({"error": "缺少UID"}), 400
    
    # 记录拉黑日志
    block_log = load_json(BLOCK_LOG_FILE, {})
    block_log[uid] = {
        "username": data.get("username", "未知"),
        "reason": reason,
        "last_comment": "",
        "score": 0,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    save_json(BLOCK_LOG_FILE, block_log)
    
    # 调B站拉黑API
    try:
        from config import SESSDATA, BILI_JCT, DEDE_USER_ID
        h = {
            "Cookie": f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com"
        }
        import requests as req
        resp = req.post("https://api.bilibili.com/x/relation/modify",
            headers=h, data={"fid": uid, "act": 5, "re_src": 11, "csrf": BILI_JCT})
        result = resp.json()
        if result.get("code") == 0:
            return jsonify({"ok": True, "msg": f"已拉黑UID:{uid}"})
        else:
            return jsonify({"ok": False, "msg": f"B站API拉黑失败: {result.get('message', '')}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"拉黑请求失败: {e}"})

# ========== 数据导出 API ==========
@app.route("/api/export", methods=["GET"])
def api_export_data():
    """导出所有数据为JSON"""
    export = {
        "memory": load_json(MEMORY_FILE, []),
        "affection": load_json(AFFECTION_FILE, {}),
        "chat_history": load_json(LOCAL_CHAT_FILE, []),
        "permanent_memory": load_json("data/permanent_memory.json", []),
        "personality": load_json(PERSONALITY_FILE, {}),
        "user_profiles": load_json(USER_PROFILE_FILE, {}),
        "personas": load_json(PERSONA_FILE, []),
        "mood": load_json(MOOD_FILE, {}),
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return jsonify(export)


# ========== 健康检测 API ==========
@app.route("/api/health", methods=["GET"])
def api_health():
    """前端心跳检测用"""
    import time
    return jsonify({
        "ok": True,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": "running"
    })

# ========== 模型连接测试 API ==========
@app.route("/api/model/test", methods=["POST"])
def api_model_test():
    """测试指定类型的模型是否能正常调用"""
    data = request.json or {}
    model_type = data.get("type", "chat")

    if model_type not in ("chat", "vision", "search", "image"):
        return jsonify({"ok": False, "error": f"未知模型类型: {model_type}"}), 400

    import time
    start = time.time()

    try:
        client, model, fallback = get_or_client(model_type)

        if model_type == "image":
            # 图片模型: OpenRouter的Flux等模型走chat/completions + modalities
            # 用最小请求测试连通性（不会真正生成大图）
            try:
                import requests as req
                base_url, api_key, model_id, fallback = get_model_config("image")
                test_url = f"{base_url}/chat/completions"
                test_headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                test_payload = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "test pixel"}],
                    "modalities": ["image"],
                    "max_tokens": 1
                }
                resp = req.post(test_url, json=test_payload, headers=test_headers, timeout=30)
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    return jsonify({"ok": True, "model": model, "latency": latency, "msg": "图片模型可用"})
                elif resp.status_code == 404:
                    return jsonify({"ok": False, "error": f"模型不存在或已下线: {model}", "model": model})
                elif resp.status_code == 401:
                    return jsonify({"ok": False, "error": "API Key 无效或过期", "model": model})
                elif resp.status_code == 429:
                    return jsonify({"ok": True, "model": model, "latency": latency, "msg": "连接正常（限流中）"})
                else:
                    body = resp.text[:200]
                    if "<!DOCTYPE" in body or "<html" in body:
                        body = "API返回了HTML页面，Base URL 可能配置错误"
                    return jsonify({"ok": False, "error": f"HTTP {resp.status_code}: {body}", "model": model})
            except Exception as img_e:
                return jsonify({"ok": False, "error": f"连接失败: {str(img_e)[:200]}", "model": model})
        else:
            # 文本模型: 发一条最简消息
            resp = client.chat.completions.create(
                model=model,
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}]
            )
            latency = int((time.time() - start) * 1000)
            reply = resp.choices[0].message.content.strip() if resp.choices else ""
            return jsonify({
                "ok": True,
                "model": model,
                "latency": latency,
                "msg": f"收到回复: {reply[:50]}"
            })

    except Exception as e:
        err_str = str(e)
        latency = int((time.time() - start) * 1000)
        # 分类错误
        if "404" in err_str or "not found" in err_str.lower():
            return jsonify({"ok": False, "error": f"模型不存在或已下线: {model}", "model": model})
        elif "401" in err_str or "unauthorized" in err_str.lower():
            return jsonify({"ok": False, "error": "API Key 无效或过期", "model": model})
        elif "429" in err_str or "rate" in err_str.lower():
            return jsonify({"ok": True, "model": model, "latency": latency, "msg": "连接正常（限流中）"})
        elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
            return jsonify({"ok": False, "error": "连接超时，检查 Base URL 是否可达", "model": model})
        else:
            # 截断HTML垃圾
            if "<!DOCTYPE" in err_str or "<html" in err_str:
                err_str = "API返回了HTML页面而非JSON，Base URL 或模型ID可能配置错误"
            elif len(err_str) > 200:
                err_str = err_str[:200] + "..."
            return jsonify({"ok": False, "error": err_str, "model": model})

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    from datetime import timedelta
    app.permanent_session_lifetime = timedelta(days=30)

    # 启动时检查cookie状态
    from config import check_bili_cookie
    valid, info = check_bili_cookie()
    print(f"🍪 B站Cookie: {info}")

    print("🌙 本地聊天已启动 → http://localhost:5000")
    print(f"🔑 访问密码：{AUTH_PASSWORD}")
    app.run(host="0.0.0.0", port=5000, debug=False)