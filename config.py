"""
配置管理 — 支持动态热更新
配置存储在 config.json 中，可通过前端面板实时修改
"""
import json
import os
import time
import requests

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ========== 默认配置（首次运行自动生成 config.json） ==========
_DEFAULTS = {
    # B站配置
    "SESSDATA": "",
    "BILI_JCT": "",
    "DEDE_USER_ID": "",
    "OWNER_MID": 0,
    "REFRESH_TOKEN": "",

    # OpenRouter（全局默认，各模型可单独覆盖）
    "OR_API_KEY": "",
    "OR_BASE_URL": "https://openrouter.ai/api/v1",

    # 对话模型
    "OR_CHAT_MODEL": "anthropic/claude-sonnet-4-5",
    "OR_CHAT_MODEL_FALLBACK": "google/gemini-3-flash-preview",
    "OR_CHAT_URL": "",       # 留空=用全局 OR_BASE_URL
    "OR_CHAT_KEY": "",       # 留空=用全局 OR_API_KEY

    # 视觉模型
    "OR_VISION_MODEL": "google/gemini-3-flash-preview",
    "OR_VISION_MODEL_FALLBACK": "google/gemini-2.5-flash-preview",
    "OR_VISION_URL": "",
    "OR_VISION_KEY": "",

    # 搜索模型
    "OR_SEARCH_MODEL": "google/gemini-3-flash-preview:online",
    "OR_SEARCH_MODEL_FALLBACK": "google/gemini-2.5-flash-preview:online",
    "OR_SEARCH_URL": "",
    "OR_SEARCH_KEY": "",

    # 图片生成模型
    "OR_IMAGE_MODEL": "black-forest-labs/flux.2-pro",
    "OR_IMAGE_MODEL_FALLBACK": "",
    "OR_IMAGE_URL": "",
    "OR_IMAGE_KEY": "",

    # SiliconFlow（embedding）
    "SILICON_API_KEY": "",
    "EMBED_BASE_URL": "https://api.siliconflow.cn/v1",
    "EMBED_MODEL": "BAAI/bge-m3",

    # ===== 功能开关 =====
    "ENABLE_WEB_SEARCH": True,
    "ENABLE_PROACTIVE": True,
    "ENABLE_DYNAMIC": True,
    "ENABLE_PERSONALITY_EVOLUTION": True,
    "ENABLE_MOOD": True,
    "ENABLE_AFFECTION": True,

    # ===== 主动行为开关 =====
    "PROACTIVE_LIKE": True,
    "PROACTIVE_COIN": False,
    "PROACTIVE_FAV": True,
    "PROACTIVE_FOLLOW": True,
    "PROACTIVE_COMMENT": True,

    # ===== 调度参数 =====
    "PROACTIVE_VIDEO_COUNT": 3,    # 每天刷几个视频
    "PROACTIVE_COMMENT_COUNT": 2,  # 每天评论几条
    "PROACTIVE_TIMES_COUNT": 2,    # 每天触发几次主动评论
    "DYNAMIC_ENABLED": True,
    "EVOLVE_HOUR": 1,              # 性格演化时间（0-23）
    "SLEEP_START": 2,              # 休眠开始
    "SLEEP_END": 8,                # 休眠结束

    # ===== 权重参数 =====
    "MOOD_WEIGHT": 0.5,            # 心情对回复的影响程度 0-1

    # ===== Bot 基本信息 =====
    "BOT_NAME": "Bot",
    "BOT_AVATAR": "🤖",
    "USER_AVATAR": "🌙",
    "BOT_WELCOME": "你好，有什么想聊的？",
    "BOT_SUBTITLE": "AI 聊天助手",

    # ===== 人格系统 =====
    "ACTIVE_PERSONA": "default",

    # ===== 主动看视频的 UP主 UID 列表 =====
    "PROACTIVE_FOLLOW_UIDS": [],
    "PREFERRED_TIDS": [17, 160, 211, 3, 13, 167, 321, 36, 129],

    # ===== 自定义提示词（空=用默认） =====
    "PROMPT_DYNAMIC": "",
    "PROMPT_PROACTIVE_COMMENT": "",
    "PROMPT_VIDEO_EVALUATE": "",
    "PROMPT_PERSONALITY_EVOLVE": "",
    "PROMPT_SEARCH_PREFIX": "",
    "PROMPT_IMAGINE": "",
    "DYNAMIC_TOPICS": [],

    # ===== 主人信息 =====
    "OWNER_NAME": "",
    "OWNER_BILI_NAME": "",
}

# ========== 加载/保存 ==========
def _load_config():
    """从 config.json 加载配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并：已保存的覆盖默认值，新增的字段用默认值补充
            merged = {**_DEFAULTS, **saved}
            return merged
        except Exception as e:
            print(f"⚠️ 读取 config.json 失败：{e}，使用默认配置")
    return dict(_DEFAULTS)

def _save_config(cfg):
    """保存配置到 config.json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _ensure_config_file():
    """确保 config.json 存在，不存在则从旧硬编码配置迁移或创建默认"""
    if not os.path.exists(CONFIG_FILE):
        print("📝 首次运行，生成 config.json...")
        _save_config(_DEFAULTS)

_ensure_config_file()
_cfg = _load_config()

# ========== 导出变量（兼容 from config import *） ==========
SESSDATA = _cfg["SESSDATA"]
BILI_JCT = _cfg["BILI_JCT"]
DEDE_USER_ID = _cfg["DEDE_USER_ID"]
OWNER_MID = _cfg["OWNER_MID"]
REFRESH_TOKEN = _cfg.get("REFRESH_TOKEN", "")

OR_API_KEY = _cfg["OR_API_KEY"]
OR_BASE_URL = _cfg["OR_BASE_URL"]
OR_CHAT_MODEL = _cfg["OR_CHAT_MODEL"]
OR_CHAT_MODEL_FALLBACK = _cfg.get("OR_CHAT_MODEL_FALLBACK", "")
OR_CHAT_URL = _cfg.get("OR_CHAT_URL", "")
OR_CHAT_KEY = _cfg.get("OR_CHAT_KEY", "")
OR_SEARCH_MODEL = _cfg["OR_SEARCH_MODEL"]
OR_SEARCH_MODEL_FALLBACK = _cfg.get("OR_SEARCH_MODEL_FALLBACK", "")
OR_SEARCH_URL = _cfg.get("OR_SEARCH_URL", "")
OR_SEARCH_KEY = _cfg.get("OR_SEARCH_KEY", "")
OR_VISION_MODEL = _cfg["OR_VISION_MODEL"]
OR_VISION_MODEL_FALLBACK = _cfg.get("OR_VISION_MODEL_FALLBACK", "")
OR_VISION_URL = _cfg.get("OR_VISION_URL", "")
OR_VISION_KEY = _cfg.get("OR_VISION_KEY", "")
OR_IMAGE_MODEL = _cfg["OR_IMAGE_MODEL"]
OR_IMAGE_MODEL_FALLBACK = _cfg.get("OR_IMAGE_MODEL_FALLBACK", "")
OR_IMAGE_URL = _cfg.get("OR_IMAGE_URL", "")
OR_IMAGE_KEY = _cfg.get("OR_IMAGE_KEY", "")

SILICON_API_KEY = _cfg["SILICON_API_KEY"]

# 功能开关
ENABLE_WEB_SEARCH = _cfg.get("ENABLE_WEB_SEARCH", True)
ENABLE_PROACTIVE = _cfg.get("ENABLE_PROACTIVE", True)
ENABLE_DYNAMIC = _cfg.get("ENABLE_DYNAMIC", True)
ENABLE_PERSONALITY_EVOLUTION = _cfg.get("ENABLE_PERSONALITY_EVOLUTION", True)
ENABLE_MOOD = _cfg.get("ENABLE_MOOD", True)
ENABLE_AFFECTION = _cfg.get("ENABLE_AFFECTION", True)

# 主动行为开关
PROACTIVE_LIKE = _cfg.get("PROACTIVE_LIKE", True)
PROACTIVE_COIN = _cfg.get("PROACTIVE_COIN", False)
PROACTIVE_FAV = _cfg.get("PROACTIVE_FAV", True)
PROACTIVE_FOLLOW = _cfg.get("PROACTIVE_FOLLOW", True)
PROACTIVE_COMMENT = _cfg.get("PROACTIVE_COMMENT", True)

# 调度
PROACTIVE_VIDEO_COUNT = _cfg.get("PROACTIVE_VIDEO_COUNT", 3)
PROACTIVE_COMMENT_COUNT = _cfg.get("PROACTIVE_COMMENT_COUNT", 2)
PROACTIVE_TIMES_COUNT = _cfg.get("PROACTIVE_TIMES_COUNT", 2)
DYNAMIC_ENABLED = _cfg.get("DYNAMIC_ENABLED", True)
EVOLVE_HOUR = _cfg.get("EVOLVE_HOUR", 1)
SLEEP_START = _cfg.get("SLEEP_START", 2)
SLEEP_END = _cfg.get("SLEEP_END", 8)

# 权重
MOOD_WEIGHT = _cfg.get("MOOD_WEIGHT", 0.5)

# 人格
ACTIVE_PERSONA = _cfg.get("ACTIVE_PERSONA", "default")

# 自定义提示词
PROMPT_DYNAMIC = _cfg.get("PROMPT_DYNAMIC", "")
PROMPT_PROACTIVE_COMMENT = _cfg.get("PROMPT_PROACTIVE_COMMENT", "")
PROMPT_VIDEO_EVALUATE = _cfg.get("PROMPT_VIDEO_EVALUATE", "")
PROMPT_PERSONALITY_EVOLVE = _cfg.get("PROMPT_PERSONALITY_EVOLVE", "")
PROMPT_SEARCH_PREFIX = _cfg.get("PROMPT_SEARCH_PREFIX", "")
PROMPT_IMAGINE = _cfg.get("PROMPT_IMAGINE", "")

# ========== 动态更新函数 ==========
def reload_config():
    """重新加载配置（热更新）"""
    global SESSDATA, BILI_JCT, DEDE_USER_ID, OWNER_MID, REFRESH_TOKEN
    global OR_API_KEY, OR_BASE_URL, OR_CHAT_MODEL, OR_SEARCH_MODEL, OR_VISION_MODEL, OR_IMAGE_MODEL
    global OR_CHAT_MODEL_FALLBACK, OR_CHAT_URL, OR_CHAT_KEY
    global OR_SEARCH_MODEL_FALLBACK, OR_SEARCH_URL, OR_SEARCH_KEY
    global OR_VISION_MODEL_FALLBACK, OR_VISION_URL, OR_VISION_KEY
    global OR_IMAGE_MODEL_FALLBACK, OR_IMAGE_URL, OR_IMAGE_KEY
    global SILICON_API_KEY, _cfg
    global ENABLE_WEB_SEARCH, ENABLE_PROACTIVE, ENABLE_DYNAMIC
    global ENABLE_PERSONALITY_EVOLUTION, ENABLE_MOOD, ENABLE_AFFECTION
    global PROACTIVE_LIKE, PROACTIVE_COIN, PROACTIVE_FAV, PROACTIVE_FOLLOW, PROACTIVE_COMMENT
    global PROACTIVE_VIDEO_COUNT, PROACTIVE_COMMENT_COUNT, PROACTIVE_TIMES_COUNT
    global DYNAMIC_ENABLED, EVOLVE_HOUR, SLEEP_START, SLEEP_END
    global MOOD_WEIGHT, ACTIVE_PERSONA
    global PROMPT_DYNAMIC, PROMPT_PROACTIVE_COMMENT, PROMPT_VIDEO_EVALUATE
    global PROMPT_PERSONALITY_EVOLVE, PROMPT_SEARCH_PREFIX, PROMPT_IMAGINE

    _cfg = _load_config()
    SESSDATA = _cfg["SESSDATA"]
    BILI_JCT = _cfg["BILI_JCT"]
    DEDE_USER_ID = _cfg["DEDE_USER_ID"]
    OWNER_MID = _cfg["OWNER_MID"]
    REFRESH_TOKEN = _cfg.get("REFRESH_TOKEN", "")
    OR_API_KEY = _cfg["OR_API_KEY"]
    OR_BASE_URL = _cfg["OR_BASE_URL"]
    OR_CHAT_MODEL = _cfg["OR_CHAT_MODEL"]
    OR_CHAT_MODEL_FALLBACK = _cfg.get("OR_CHAT_MODEL_FALLBACK", "")
    OR_CHAT_URL = _cfg.get("OR_CHAT_URL", "")
    OR_CHAT_KEY = _cfg.get("OR_CHAT_KEY", "")
    OR_SEARCH_MODEL = _cfg["OR_SEARCH_MODEL"]
    OR_SEARCH_MODEL_FALLBACK = _cfg.get("OR_SEARCH_MODEL_FALLBACK", "")
    OR_SEARCH_URL = _cfg.get("OR_SEARCH_URL", "")
    OR_SEARCH_KEY = _cfg.get("OR_SEARCH_KEY", "")
    OR_VISION_MODEL = _cfg["OR_VISION_MODEL"]
    OR_VISION_MODEL_FALLBACK = _cfg.get("OR_VISION_MODEL_FALLBACK", "")
    OR_VISION_URL = _cfg.get("OR_VISION_URL", "")
    OR_VISION_KEY = _cfg.get("OR_VISION_KEY", "")
    OR_IMAGE_MODEL = _cfg["OR_IMAGE_MODEL"]
    OR_IMAGE_MODEL_FALLBACK = _cfg.get("OR_IMAGE_MODEL_FALLBACK", "")
    OR_IMAGE_URL = _cfg.get("OR_IMAGE_URL", "")
    OR_IMAGE_KEY = _cfg.get("OR_IMAGE_KEY", "")
    SILICON_API_KEY = _cfg["SILICON_API_KEY"]
    ENABLE_WEB_SEARCH = _cfg.get("ENABLE_WEB_SEARCH", True)
    ENABLE_PROACTIVE = _cfg.get("ENABLE_PROACTIVE", True)
    ENABLE_DYNAMIC = _cfg.get("ENABLE_DYNAMIC", True)
    ENABLE_PERSONALITY_EVOLUTION = _cfg.get("ENABLE_PERSONALITY_EVOLUTION", True)
    ENABLE_MOOD = _cfg.get("ENABLE_MOOD", True)
    ENABLE_AFFECTION = _cfg.get("ENABLE_AFFECTION", True)
    PROACTIVE_LIKE = _cfg.get("PROACTIVE_LIKE", True)
    PROACTIVE_COIN = _cfg.get("PROACTIVE_COIN", False)
    PROACTIVE_FAV = _cfg.get("PROACTIVE_FAV", True)
    PROACTIVE_FOLLOW = _cfg.get("PROACTIVE_FOLLOW", True)
    PROACTIVE_COMMENT = _cfg.get("PROACTIVE_COMMENT", True)
    PROACTIVE_VIDEO_COUNT = _cfg.get("PROACTIVE_VIDEO_COUNT", 3)
    PROACTIVE_COMMENT_COUNT = _cfg.get("PROACTIVE_COMMENT_COUNT", 2)
    PROACTIVE_TIMES_COUNT = _cfg.get("PROACTIVE_TIMES_COUNT", 2)
    DYNAMIC_ENABLED = _cfg.get("DYNAMIC_ENABLED", True)
    EVOLVE_HOUR = _cfg.get("EVOLVE_HOUR", 1)
    SLEEP_START = _cfg.get("SLEEP_START", 2)
    SLEEP_END = _cfg.get("SLEEP_END", 8)
    MOOD_WEIGHT = _cfg.get("MOOD_WEIGHT", 0.5)
    ACTIVE_PERSONA = _cfg.get("ACTIVE_PERSONA", "default")
    PROMPT_DYNAMIC = _cfg.get("PROMPT_DYNAMIC", "")
    PROMPT_PROACTIVE_COMMENT = _cfg.get("PROMPT_PROACTIVE_COMMENT", "")
    PROMPT_VIDEO_EVALUATE = _cfg.get("PROMPT_VIDEO_EVALUATE", "")
    PROMPT_PERSONALITY_EVOLVE = _cfg.get("PROMPT_PERSONALITY_EVOLVE", "")
    PROMPT_SEARCH_PREFIX = _cfg.get("PROMPT_SEARCH_PREFIX", "")
    PROMPT_IMAGINE = _cfg.get("PROMPT_IMAGINE", "")
    return _cfg

def update_config(updates: dict):
    """更新部分配置并保存"""
    cfg = _load_config()
    cfg.update(updates)
    _save_config(cfg)
    reload_config()
    return cfg

def get_config():
    """获取当前配置（脱敏版，隐藏密钥中间部分）"""
    cfg = _load_config()
    safe = {}
    for k, v in cfg.items():
        if isinstance(v, str) and ("KEY" in k or "TOKEN" in k or "SESSDATA" in k or "JCT" in k) and len(v) > 10:
            safe[k] = v[:6] + "***" + v[-4:]
        else:
            safe[k] = v
    return safe

def get_raw_config():
    """获取原始配置（不脱敏，仅后端使用）"""
    return _load_config()

# ========== 获取各模型的 API 配置 ==========
def get_model_config(model_type):
    """
    获取指定模型类型的 (base_url, api_key, model_id, fallback_model)
    model_type: "chat" / "vision" / "search" / "image"
    每个模型可以有独立的 URL 和 Key，留空则用全局的
    """
    cfg = _load_config()
    prefix = f"OR_{model_type.upper()}"
    base_url = cfg.get(f"{prefix}_URL", "") or cfg.get("OR_BASE_URL", "")
    api_key = cfg.get(f"{prefix}_KEY", "") or cfg.get("OR_API_KEY", "")
    model_id = cfg.get(f"{prefix}_MODEL", "")
    fallback = cfg.get(f"{prefix}_MODEL_FALLBACK", "")
    return base_url, api_key, model_id, fallback

# ========== B站 Cookie 有效性检查 ==========
def check_bili_cookie():
    """检查B站cookie是否有效，返回 (valid: bool, info: str)"""
    if not SESSDATA:
        return False, "SESSDATA 为空"
    try:
        url = "https://api.bilibili.com/x/web-interface/nav"
        h = {
            "Cookie": f"SESSDATA={SESSDATA}; bili_jct={BILI_JCT}; DedeUserID={DEDE_USER_ID}",
            "User-Agent": "Mozilla/5.0"
        }
        resp = requests.get(url, headers=h, timeout=10)
        data = resp.json()
        if data["code"] == 0:
            uname = data["data"].get("uname", "未知")
            mid = data["data"].get("mid", "")
            level = data["data"].get("level_info", {}).get("current_level", 0)
            return True, f"有效 | {uname} (UID:{mid}) LV{level}"
        else:
            return False, f"Cookie 已失效 (code: {data['code']})"
    except Exception as e:
        return False, f"检查失败: {e}"

# ========== B站 Cookie 自动刷新 ==========
def refresh_bili_cookie():
    """
    尝试刷新B站cookie（需要 REFRESH_TOKEN）
    返回 (success: bool, message: str)
    """
    cfg = _load_config()
    rt = cfg.get("REFRESH_TOKEN", "")
    if not rt:
        return False, "没有 refresh_token，无法自动刷新，请手动更新 Cookie"

    try:
        # 第一步：获取 refresh_csrf
        csrf_url = "https://www.bilibili.com/correspond/1/" + str(int(time.time() * 1000))
        csrf_resp = requests.get(csrf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)

        # 第二步：调用刷新接口
        url = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
        data = {
            "csrf": cfg["BILI_JCT"],
            "refresh_csrf": "",  # 从第一步获取
            "source": "main_web",
            "refresh_token": rt,
        }
        h = {
            "Cookie": f"SESSDATA={cfg['SESSDATA']}; bili_jct={cfg['BILI_JCT']}",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com"
        }
        resp = requests.post(url, headers=h, data=data, timeout=10)
        result = resp.json()

        if result["code"] == 0:
            new_data = result["data"]
            # 从 Set-Cookie 中提取新的 SESSDATA 和 bili_jct
            new_rt = new_data.get("refresh_token", rt)
            # 更新配置
            updates = {"REFRESH_TOKEN": new_rt}

            # 从响应 cookies 中获取新值
            for cookie in resp.cookies:
                if cookie.name == "SESSDATA":
                    updates["SESSDATA"] = cookie.value
                elif cookie.name == "bili_jct":
                    updates["BILI_JCT"] = cookie.value

            if "SESSDATA" in updates:
                update_config(updates)
                return True, "Cookie 刷新成功"
            else:
                return False, "刷新响应中未找到新 Cookie"
        else:
            return False, f"刷新失败: {result.get('message', str(result['code']))}"
    except Exception as e:
        return False, f"刷新出错: {e}"