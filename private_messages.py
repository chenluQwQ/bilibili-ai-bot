"""B站私信轮询、发送与安全判定。

仅处理个人会话中的纯文本和B站视频分享消息。首次启用时建立当前位置游标，不处理历史私信。
危险链接判断只解析文本，不访问目标网址。
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests


SESSIONS_URL = "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
MESSAGES_URL = "https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
SEND_URL = "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg"

_URL_RE = re.compile(
    r"""(?ix)
    (?:
        (?:https?|hxxps?)://[^\s<>"'，。！？、]+
        |
        www\.[^\s<>"'，。！？、]+
        |
        (?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+
        (?:com|net|org|cn|tv|cc|me|xyz|top|vip|site|link|app|io|info|live)
        (?:/[^\s<>"'，。！？、]*)?
    )
    """
)
_STRONG_ADULT_RE = re.compile(
    r"(?i)(裸聊|约炮|援交|卖片|色情网站|黄色网站|成人网站|成人视频|"
    r"无码视频|无码视频|看片地址|看片链接|成人视频|未成年.{0,8}(?:裸照|私密视频))"
)
_LINKED_ADULT_RE = re.compile(
    r"(?i)(色情|黄色|成人|福利姬|福利群|资源群|私密视频|色图|涩图|裸照|成人视频|看片)"
)
_ADULT_DOMAIN_MARKERS = (
    "porn",
    "sex",
    "xxx",
    "hentai",
    "jav",
    "xvideo",
    "onlyfans",
    "91porn",
    "麻豆",
)


@dataclass(frozen=True)
class SafetyDecision:
    should_block: bool
    reason: str = ""
    urls: tuple[str, ...] = ()


def _normalize_for_detection(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", value)
    value = re.sub(r"(?i)\bhxxps?://", lambda m: m.group(0).replace("xx", "tt"), value)
    value = re.sub(r"[\[\(\{]\s*\.\s*[\]\)\}]", ".", value)
    value = value.replace("。", ".").replace("．", ".").replace("｡", ".")
    value = re.sub(r"(?<=[A-Za-z0-9])点(?=[A-Za-z]{2,12}\b)", ".", value)
    return value


def extract_urls(text: str) -> list[str]:
    normalized = _normalize_for_detection(text)
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(normalized):
        candidate = match.group(0).rstrip(".,;:!?)]}")
        if candidate.lower().startswith("www."):
            candidate = "https://" + candidate
        elif "://" not in candidate:
            candidate = "https://" + candidate
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").strip(".").lower()
    except ValueError:
        return ""


def _is_trusted_host(host: str, trusted_domains: list[str]) -> bool:
    for item in trusted_domains:
        trusted = str(item or "").strip().strip(".").lower()
        if trusted and (host == trusted or host.endswith("." + trusted)):
            return True
    return False


def assess_private_message(
    text: str,
    trusted_domains: list[str] | None = None,
) -> SafetyDecision:
    """判定是否应因危险链接或色情引流而直接拉黑。"""
    normalized = _normalize_for_detection(text)
    urls = extract_urls(normalized)
    trusted = trusted_domains or ["bilibili.com", "b23.tv"]

    if _STRONG_ADULT_RE.search(normalized):
        return SafetyDecision(True, "疑似色情或成人引流内容", tuple(urls))

    for url in urls:
        host = _hostname(url)
        if not host:
            return SafetyDecision(True, "无法识别目标域名的链接", tuple(urls))
        try:
            ipaddress.ip_address(host)
            return SafetyDecision(True, f"不可信 IP 链接：{host}", tuple(urls))
        except ValueError:
            pass
        if any(marker in host for marker in _ADULT_DOMAIN_MARKERS):
            return SafetyDecision(True, f"疑似色情域名：{host}", tuple(urls))
        if not _is_trusted_host(host, trusted):
            return SafetyDecision(True, f"未信任的外部链接：{host}", tuple(urls))

    if urls and _LINKED_ADULT_RE.search(normalized):
        return SafetyDecision(True, "链接伴随疑似色情引流内容", tuple(urls))
    return SafetyDecision(False, urls=tuple(urls))


def is_protected_sender(mid: str | int, config: dict[str, Any]) -> bool:
    uid = str(mid or "").strip()
    protected = {
        str(config.get("OWNER_MID", "") or "").strip(),
        str(config.get("DEDE_USER_ID", "") or "").strip(),
    }
    protected.update(
        str(item or "").strip()
        for item in (config.get("PRIVATE_MESSAGE_BLOCK_WHITELIST_UIDS") or [])
    )
    protected.discard("")
    return uid in protected


def reply_scope_allows(mid: str | int, config: dict[str, Any]) -> bool:
    uid = str(mid or "").strip()
    scope = str(config.get("PRIVATE_MESSAGE_REPLY_SCOPE", "all") or "all").lower()
    if scope == "all":
        return True
    owner = str(config.get("OWNER_MID", "") or "").strip()
    whitelist = {
        str(item or "").strip()
        for item in (config.get("PRIVATE_MESSAGE_REPLY_WHITELIST_UIDS") or [])
    }
    if scope == "owner":
        return bool(uid and uid == owner)
    if scope == "whitelist":
        return bool(uid and (uid == owner or uid in whitelist))
    return False


class PrivateMessageClient:
    def __init__(
        self,
        base_dir: str,
        http: requests.Session | None = None,
        now=time.time,
    ):
        self.base_dir = base_dir
        self.state_file = os.path.join(base_dir, "data", "private_message_state.json")
        self.http = http or requests.Session()
        self.now = now

    @staticmethod
    def _headers(config: dict[str, Any]) -> dict[str, str]:
        return {
            "Cookie": (
                f"SESSDATA={config.get('SESSDATA', '')}; "
                f"bili_jct={config.get('BILI_JCT', '')}; "
                f"DedeUserID={config.get('DEDE_USER_ID', '')}"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://message.bilibili.com/",
            "Origin": "https://message.bilibili.com",
        }

    def _load_state(self) -> dict[str, Any]:
        try:
            with open(self.state_file, "r", encoding="utf-8") as file:
                state = json.load(file)
            if isinstance(state, dict):
                return state
        except (OSError, ValueError):
            pass
        return {
            "initialized": False,
            "initialized_at": int(self.now()),
            "account_uid": "",
            "device_id": str(uuid.uuid4()).upper(),
            "sessions": {},
            "processed_keys": [],
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        temp_file = self.state_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.state_file)

    @staticmethod
    def _json_content(raw: Any) -> str:
        if isinstance(raw, dict):
            return str(raw.get("content") or raw.get("text") or "").strip()
        if not isinstance(raw, str):
            return ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return str(parsed.get("content") or parsed.get("text") or "").strip()
        except (TypeError, ValueError):
            return raw.strip()
        return ""

    @staticmethod
    def _message_content(raw: Any, msg_type: int) -> tuple[str, str]:
        if msg_type == 1:
            return PrivateMessageClient._json_content(raw), "text"
        if msg_type != 7:
            return "", ""
        if isinstance(raw, dict):
            parsed = raw
        else:
            try:
                parsed = json.loads(str(raw or ""))
            except (TypeError, ValueError):
                return "", ""
        if not isinstance(parsed, dict):
            return "", ""
        bvid = str(parsed.get("bvid") or "").strip()
        aid = str(parsed.get("id") or parsed.get("aid") or "").strip()
        title = str(
            parsed.get("title")
            or parsed.get("headline")
            or parsed.get("name")
            or ""
        ).strip()
        if re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
            video_url = f"https://www.bilibili.com/video/{bvid}"
        elif aid.isdigit():
            video_url = f"https://www.bilibili.com/video/av{aid}"
        else:
            return "", ""
        prefix = f"[B站视频分享] {title}" if title else "[B站视频分享]"
        return f"{prefix}\n{video_url}", "video_share"

    def _get_sessions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.http.get(
            SESSIONS_URL,
            headers=self._headers(config),
            params={
                "session_type": 1,
                "group_fold": 1,
                "unfollow_fold": 0,
                "sort_rule": 2,
                "size": 100,
                "build": 0,
                "mobi_app": "web",
            },
            timeout=10,
        )
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"获取私信会话失败: code={data.get('code')} {data.get('message', '')}"
            )
        return list((data.get("data") or {}).get("session_list") or [])

    def _fetch_messages(
        self,
        config: dict[str, Any],
        talker_id: int,
        session_type: int,
        begin_seqno: int,
    ) -> dict[str, Any]:
        response = self.http.get(
            MESSAGES_URL,
            headers=self._headers(config),
            params={
                "talker_id": talker_id,
                "session_type": session_type,
                "begin_seqno": begin_seqno,
                "size": 20,
                "sender_device_id": 1,
                "build": 0,
                "mobi_app": "web",
            },
            timeout=10,
        )
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"获取私信内容失败: code={data.get('code')} {data.get('message', '')}"
            )
        return data.get("data") or {}

    def poll(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """返回新的入站纯文本消息；首次调用只建立游标。"""
        sessions = self._get_sessions(config)
        state = self._load_state()
        self_uid = str(config.get("DEDE_USER_ID", "") or "")
        previous_account = str(state.get("account_uid") or "")
        account_changed = bool(previous_account and previous_account != self_uid)
        if previous_account != self_uid:
            state = {
                "initialized": False,
                "initialized_at": int(self.now()),
                "account_uid": self_uid,
                "device_id": str(uuid.uuid4()).upper(),
                "sessions": {},
                "processed_keys": [],
            }
        session_state = state.setdefault("sessions", {})
        processed = [str(item) for item in state.get("processed_keys", [])]
        processed_set = set(processed)

        if not state.get("initialized"):
            for session in sessions:
                talker_id = int(session.get("talker_id") or 0)
                session_type = int(session.get("session_type") or 1)
                if talker_id:
                    session_state[f"{session_type}:{talker_id}"] = int(
                        session.get("max_seqno") or 0
                    )
            state["initialized"] = True
            state["initialized_at"] = int(self.now())
            self._save_state(state)
            reason = "账号已切换，已重置" if account_changed else "首次启用"
            print(f"[私信] 监听初始化完成（{reason}）：已跳过现有历史消息")
            return []

        max_age = max(
            60,
            int(config.get("PRIVATE_MESSAGE_MAX_MESSAGE_AGE", 3600) or 3600),
        )
        now = int(self.now())
        new_messages: list[dict[str, Any]] = []
        message_limit = max(
            1,
            min(20, int(config.get("PRIVATE_MESSAGE_MAX_PER_POLL", 3) or 3)),
        )

        for session in sessions:
            if len(new_messages) >= message_limit:
                break
            talker_id = int(session.get("talker_id") or 0)
            session_type = int(session.get("session_type") or 1)
            if not talker_id or session_type != 1:
                continue
            key = f"{session_type}:{talker_id}"
            last_seqno = int(session_state.get(key) or 0)
            remote_max = int(session.get("max_seqno") or 0)
            if last_seqno and remote_max and remote_max <= last_seqno:
                continue
            try:
                payload = self._fetch_messages(
                    config,
                    talker_id,
                    session_type,
                    last_seqno,
                )
            except Exception as exc:
                print(f"[私信警告] 会话 {talker_id} 拉取失败：{exc}")
                continue

            messages = list(payload.get("messages") or [])
            payload_max = int(payload.get("max_seqno") or remote_max or last_seqno)
            examined_max = last_seqno
            reached_limit = False
            for message in reversed(messages):
                msg_key = str(
                    message.get("msg_key")
                    or message.get("msg_seqno")
                    or ""
                )
                msg_seqno = int(message.get("msg_seqno") or 0)
                sender_uid = str(message.get("sender_uid") or "")
                msg_type = int(message.get("msg_type") or 0)
                timestamp = int(message.get("timestamp") or now)
                if timestamp > 10_000_000_000:
                    timestamp //= 1000
                if msg_seqno:
                    examined_max = max(examined_max, msg_seqno)
                if (
                    not msg_key
                    or msg_key in processed_set
                    or sender_uid == self_uid
                    or msg_type not in (1, 7)
                    or (last_seqno and msg_seqno and msg_seqno <= last_seqno)
                    or now - timestamp > max_age
                ):
                    continue
                content, content_type = self._message_content(
                    message.get("content"),
                    msg_type,
                )
                if not content:
                    continue
                account = session.get("account_info") or {}
                new_messages.append(
                    {
                        "msg_key": msg_key,
                        "msg_seqno": msg_seqno,
                        "talker_id": talker_id,
                        "session_type": session_type,
                        "sender_uid": sender_uid or str(talker_id),
                        "username": (
                            account.get("name")
                            or account.get("uname")
                            or f"UID {talker_id}"
                        ),
                        "content": content,
                        "content_type": content_type,
                        "timestamp": timestamp,
                    }
                )
                processed.append(msg_key)
                processed_set.add(msg_key)
                if len(new_messages) >= message_limit:
                    reached_limit = True
                    break

            if reached_limit:
                # 只推进到本轮最后实际取出的消息，剩余消息留给下一轮。
                observed_max = examined_max
            else:
                observed_max = max(
                    [last_seqno, remote_max, payload_max]
                    + [int(item.get("msg_seqno") or 0) for item in messages]
                )
            session_state[key] = observed_max

        state["processed_keys"] = processed[-1000:]
        self._save_state(state)
        return new_messages

    def send_text(
        self,
        config: dict[str, Any],
        receiver_id: str | int,
        text: str,
        session_type: int = 1,
    ) -> bool:
        """发送一次纯文本私信。写操作不重试，避免重复发送。"""
        sender_uid = str(config.get("DEDE_USER_ID", "") or "").strip()
        receiver_uid = str(receiver_id or "").strip()
        csrf = str(config.get("BILI_JCT", "") or "").strip()
        content = str(text or "").strip()
        if (
            not sender_uid.isdigit()
            or not receiver_uid.isdigit()
            or not csrf
            or not content
        ):
            return False
        state = self._load_state()
        device_id = state.get("device_id") or str(uuid.uuid4()).upper()
        state["device_id"] = device_id
        self._save_state(state)
        now_ms = int(self.now() * 1000)
        form = {
            "msg[sender_uid]": sender_uid,
            "msg[receiver_id]": receiver_uid,
            "msg[receiver_type]": str(session_type),
            "msg[msg_type]": "1",
            "msg[msg_status]": "0",
            "msg[dev_id]": str(device_id),
            "msg[timestamp]": str(now_ms),
            "msg[content]": json.dumps({"content": content}, ensure_ascii=False),
            "msg[new_face_version]": "0",
            "from_firework": "0",
            "build": "0",
            "mobi_app": "web",
            "csrf_token": csrf,
            "csrf": csrf,
        }
        try:
            response = self.http.post(
                SEND_URL,
                headers=self._headers(config),
                data=form,
                timeout=10,
            )
            result = response.json()
            if result.get("code") == 0:
                return True
            print(
                f"[私信警告] 发送失败 UID {receiver_uid}: "
                f"code={result.get('code')} {result.get('message', '')}"
            )
        except Exception as exc:
            print(f"[私信警告] 发送异常 UID {receiver_uid}: {exc}")
        return False
