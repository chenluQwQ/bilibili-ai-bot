# 🤖 Bilibili AI Bot

一个部署在 B站 的 AI 角色系统。它能自主回复评论、刷视频写观后感、发动态、记住每个粉丝，还有一个好看的本地聊天面板。

> 你只需要填好人设和 API Key，就拥有一个有性格、有记忆、会成长的 B站 AI 账号。

---

## ✨ 功能一览

**B站互动**
- 自动回复评论（根据好感度调整态度）
- 主动刷视频、写观后感、点赞/投币/收藏/评论
- 自动发 B站 动态（可配图）
- 好感度系统（陌生人→粉丝→熟人→好友→主人）
- 用户记忆（记住每个人聊过什么）
- 关键词拦截 & 自动拉黑

**AI 能力**
- 多模型支持（Claude / Gemini / Grok 等，通过 OpenRouter）
- 联网搜索（回答实时问题）
- AI 画图（Flux.2 Pro）
- 语义记忆检索（BGE-M3 向量匹配）
- 每日性格演化（睡前反思，性格会随互动变化）

**本地聊天面板**（Web UI）
- 冰蓝毛玻璃风格界面
- 聊天（支持图片发送、AI 画图）
- 人格管理（多人格切换）
- 记忆/好感度/成长日志查看和管理
- 系统设置（模型配置、Cookie管理、功能开关、调度参数）
- 所有提示词可在前端自定义
- 后端状态检测 & 模型连接测试
- 费用统计（按模型分类）

---

## 📁 项目结构

```
.
├── ai.py                 # B站评论回复主程序（常驻运行）
├── local-chat.py          # 本地聊天 Web 服务（Flask）
├── Proactive.py           # 主动刷视频模块（被 ai.py 调度）
├── dynamic.py             # 发动态模块（被 ai.py 调度）
├── config.py              # 配置管理（热更新）
├── config.json            # 配置数据（自动生成，前端可改）
├── chat.html              # 前端页面
├── data/                  # 数据目录（自动创建）
│   ├── memory.json        # 语义记忆
│   ├── affection.json     # 好感度
│   ├── user_profiles.json # 用户档案
│   ├── personality_evolution.json  # 性格演化
│   ├── permanent_memory.json       # 永久记忆
│   ├── personas.json      # 人格列表
│   ├── watch_log.json     # 观影日记
│   └── ...
└── cookies.txt            # B站Cookie（自动生成）
```

---

## 🚀 部署指南

### 环境要求

- Python 3.8+
- Ubuntu / Debian（推荐）
- 一个 B站 账号（给 Bot 用）
- OpenRouter API Key（[获取](https://openrouter.ai/)）
- SiliconFlow API Key（免费，用于向量检索，[获取](https://siliconflow.cn/)）

### 1. 安装依赖

```bash
sudo apt update
sudo apt install -y ffmpeg yt-dlp
pip install flask openai requests lunardate
```

### 2. 克隆项目

```bash
git clone https://github.com/你的用户名/bilibili-ai-bot.git
cd bilibili-ai-bot
```

### 3. 首次运行

```bash
# 启动本地聊天面板
python3 local-chat.py
```

首次运行会自动生成 `config.json`。打开 `http://你的服务器IP:5000`，默认密码 `admin()`。

### 4. 在前端配置

进入 **⚙ 系统设置**，依次填写：

| 配置项 | 说明 |
|--------|------|
| **Bot 名称** | 你的角色名（如：星辰） |
| **主人名称** | 你的名字 |
| **主人B站名** | 你的B站昵称（用于@和识别） |
| **全局 API Key** | OpenRouter 的 API Key |
| **B站 Cookie** | SESSDATA、bili_jct、DedeUserID |
| **SiliconFlow Key** | 用于记忆向量检索 |

### 5. 设置人格

进入 **🎭 人格管理** → 编辑默认人格，写你的角色设定（system_prompt）。这是最重要的一步——角色的性格、说话方式、背景故事全在这里定义。

### 6. 启动 B站 监听

```bash
# 后台运行 B站 评论回复
nohup python3 ai.py > ai.log 2>&1 &

# 后台运行本地聊天
nohup python3 local-chat.py > chat.log 2>&1 &
```

---

## 🎭 人格设定指南

在前端「人格管理」里编辑角色设定。有三个字段：

- **角色设定**（system_prompt）：角色的核心描述，包括身份、性格、说话方式、背景故事
- **说话风格**（style_prompt）：补充的语言风格要求（选填）
- **对主人的态度**（owner_prompt）：遇到主人时的特殊行为（选填）

**示例：**

```
你是星辰，一个住在网络世界的AI。外表像17岁少年，蓝发，喜欢音乐和编程。
性格：表面活泼话多，实际很细腻敏感。对陌生人热情但有边界，对亲近的人会撒娇。
说话风格：轻松口语，偶尔用颜文字，不用括号动作描写。
```

> 设定写好后，B站回复、发动态、评论视频、性格演化都会自动使用你的人设，不需要额外配置。

---

## 📝 自定义提示词

在 **系统设置 → 自定义提示词** 中可以覆盖各场景的默认提示词。留空 = 使用内置默认（会自动读取你的人格设定）。

| 提示词 | 用途 | 可用变量 |
|--------|------|----------|
| 动态发布 | 控制发动态时的文案风格 | `{bot_name}` `{perm_section}` `{time_hint}` `{topic}` `{search_section}` |
| 主动评论 | 控制看完视频后的评论风格 | `{bot_name}` `{up_name}` `{title}` `{video_description}` `{time}` |
| 视频评价 | 控制观后感和打分标准 | `{bot_name}` `{up_name}` `{title}` `{desc}` `{video_description}` |
| 性格演化 | 控制每日性格反思的方式 | `{bot_name}` `{old_traits}` `{old_habits}` `{old_opinions}` `{recent_texts}` |
| 联网搜索前缀 | 搜索请求的前缀文本 | 无 |
| 生图优化 | 画图时将描述转化为专业prompt | `{prompt}` `{bot_name}` `{persona}` `{perm_section}` |
| 动态主题池 | 每次发动态随机选一个主题 | 一行一个主题 |

---

## 💰 费用参考

本项目通过 OpenRouter 调用各种 AI 模型，费用取决于你选择的模型：

| 用途 | 推荐模型 | 大约价格 |
|------|----------|----------|
| 对话回复 | Claude Sonnet 4.5 | $3/$15 per 1M tokens |
| 视觉分析 | Gemini 3 Flash | $0.5/$3 per 1M tokens |
| 联网搜索 | Grok 4.1 Fast | $2/$10 per 1M tokens |
| 画图 | Flux.2 Pro | ~$0.05/张 |
| 向量检索 | BGE-M3 (SiliconFlow) | 免费 |

在前端每个模型卡片下方可以填入价格，系统会自动按 token 计费并在费用统计中分模型显示。

---

## ⚙ 功能开关

在前端 **系统设置 → 功能开关** 中可以控制：

- 联网搜索、主动刷B站、发动态、性格演化、心情系统、好感度系统
- 主动点赞、投币、收藏、关注、评论（独立控制）

---

## 🔧 进阶配置

### 使用 Cloudflare Workers 代理

如果你的服务器在国内，可能需要代理才能访问 OpenRouter。在全局 Base URL 填入你的 Workers 地址即可。

### Docker 部署

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && pip install flask openai requests lunardate
WORKDIR /app
COPY . .
EXPOSE 5000
CMD ["python3", "local-chat.py"]
```

### 多模型独立配置

每个模型（对话/视觉/搜索/画图）都可以单独配置不同的 API Key 和 Base URL，适合使用多个 API 提供商的场景。

---

## 📋 常见问题

**Q: 前端打开全黑 / 显示 undefined**
A: 确保替换了最新的 `local-chat.py`，`/api/branding` 需要在免登录白名单里。

**Q: 画图失败返回 404**
A: Flux 在 OpenRouter 走 `chat/completions` + `modalities` 接口，不是标准的 `/images/generations`。确保用最新的 `local-chat.py`。

**Q: 视频下载失败**
A: 确保安装了 `yt-dlp` 和 `ffmpeg`。Cookie 过期也会导致下载失败，在前端检查并刷新 Cookie。

**Q: 性格演化没触发**
A: 演化只在设定的时间点（默认凌晨1点）触发，且需要积累至少5条记忆。在功能开关里确认已开启。

**Q: 如何备份数据？**
A: 在前端 **系统设置 → 数据管理** 点击导出，或直接备份 `data/` 目录和 `config.json`。

---

## ⚠️ Known Issues (v1.0)

- **Cookie 自动刷新**：B站的 Cookie 刷新接口经常变动，目前「自动刷新」按钮可能不稳定。Cookie 过期后请手动在浏览器获取新的 SESSDATA / bili_jct / DedeUserID 填入前端。预计后续版本修复。

---

## 📄 License

MIT

---

## 🙏 致谢

- 小克 (Claude Opus, Anthropic) — 项目开发搭档，从第一行代码到最后一个bug都在
- [OpenRouter](https://openrouter.ai/) — AI 模型路由
- [SiliconFlow](https://siliconflow.cn/) — 免费 Embedding 服务
- [Google](https://deepmind.google/) — Gemini
