"""B站网页二维码登录。

二维码在本机生成；登录 Cookie 仅保留在服务端 requests.Session 中，
成功后由调用方写入本地配置，不把凭证明文返回给浏览器。
"""
from __future__ import annotations

import base64
import io
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import qrcode
import requests


QR_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

QR_WAITING = 86101
QR_SCANNED = 86090
QR_EXPIRED = 86038
QR_CONFIRMED = 0


@dataclass
class _QrSession:
    client: requests.Session
    qrcode_key: str
    created_at: float


class BiliQrLoginManager:
    def __init__(self, now=time.time, ttl=180):
        self.now = now
        self.ttl = max(60, int(ttl))
        self._sessions: dict[str, _QrSession] = {}

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }

    @staticmethod
    def _image_data_url(login_url: str) -> str:
        image = qrcode.make(login_url)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _cleanup(self) -> None:
        expired = [
            token
            for token, item in self._sessions.items()
            if self.now() - item.created_at > self.ttl
        ]
        for token in expired:
            self._sessions.pop(token, None)

    def start(self) -> dict[str, Any]:
        self._cleanup()
        client = requests.Session()
        response = client.get(
            QR_GENERATE_URL,
            headers=self._headers(),
            params={
                "source": "main-fe-header",
                "go_url": "https://www.bilibili.com/",
                "web_location": "333.1007",
            },
            timeout=10,
        )
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"获取登录二维码失败: {payload.get('message', payload.get('code'))}"
            )
        data = payload.get("data") or {}
        login_url = str(data.get("url") or "")
        qrcode_key = str(data.get("qrcode_key") or "")
        if not login_url or not qrcode_key:
            raise RuntimeError("获取登录二维码失败: 返回值缺少 url 或 qrcode_key")

        token = secrets.token_urlsafe(24)
        self._sessions[token] = _QrSession(client, qrcode_key, self.now())
        return {
            "token": token,
            "image": self._image_data_url(login_url),
            "expires_in": self.ttl,
        }

    @staticmethod
    def _cookies_from_url(url: str) -> dict[str, str]:
        query = parse_qs(urlparse(url).query)
        result = {}
        for name in ("SESSDATA", "bili_jct", "DedeUserID"):
            values = query.get(name)
            if values:
                result[name] = values[0]
        return result

    @staticmethod
    def _collect_cookies(
        client: requests.Session,
        response: requests.Response,
        redirect_url: str,
    ) -> dict[str, str]:
        cookies = dict(client.cookies.get_dict())
        cookies.update(response.cookies.get_dict())
        cookies.update(BiliQrLoginManager._cookies_from_url(redirect_url))
        return {
            name: str(cookies.get(name) or "")
            for name in ("SESSDATA", "bili_jct", "DedeUserID")
        }

    def poll(self, token: str) -> dict[str, Any]:
        self._cleanup()
        item = self._sessions.get(str(token or ""))
        if not item:
            return {"status": "expired", "message": "二维码已过期，请重新获取"}

        response = item.client.get(
            QR_POLL_URL,
            headers=self._headers(),
            params={
                "qrcode_key": item.qrcode_key,
                "source": "main-fe-header",
            },
            timeout=10,
        )
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"查询扫码状态失败: {payload.get('message', payload.get('code'))}"
            )
        data = payload.get("data") or {}
        code = int(data.get("code", -1))
        if code == QR_WAITING:
            return {"status": "waiting", "message": "等待扫码"}
        if code == QR_SCANNED:
            return {"status": "scanned", "message": "已扫码，请在 App 内确认"}
        if code == QR_EXPIRED:
            self._sessions.pop(token, None)
            return {"status": "expired", "message": "二维码已过期，请重新获取"}
        if code != QR_CONFIRMED:
            return {
                "status": "waiting",
                "message": str(data.get("message") or f"等待确认（{code}）"),
            }

        redirect_url = str(data.get("url") or "")
        if redirect_url:
            try:
                item.client.get(
                    redirect_url,
                    headers=self._headers(),
                    timeout=10,
                    allow_redirects=True,
                )
            except requests.RequestException:
                # 部分网络环境无法访问跳转页，仍可从轮询响应和 URL 提取 Cookie。
                pass

        cookies = self._collect_cookies(item.client, response, redirect_url)
        if not cookies["SESSDATA"]:
            raise RuntimeError("扫码已确认，但响应中没有 SESSDATA")
        if not cookies["bili_jct"]:
            raise RuntimeError("扫码已确认，但响应中没有 bili_jct")

        nav_response = item.client.get(
            NAV_URL,
            headers=self._headers(),
            cookies=cookies,
            timeout=10,
        )
        nav = nav_response.json()
        if nav.get("code") != 0 or not (nav.get("data") or {}).get("isLogin"):
            raise RuntimeError("扫码成功，但登录状态校验失败")
        account = nav.get("data") or {}
        if not cookies["DedeUserID"]:
            cookies["DedeUserID"] = str(account.get("mid") or "")

        self._sessions.pop(token, None)
        return {
            "status": "confirmed",
            "message": "登录成功",
            "config": {
                "SESSDATA": cookies["SESSDATA"],
                "BILI_JCT": cookies["bili_jct"],
                "DEDE_USER_ID": cookies["DedeUserID"],
                "REFRESH_TOKEN": str(data.get("refresh_token") or ""),
            },
            "account": {
                "mid": str(account.get("mid") or ""),
                "name": str(account.get("uname") or ""),
                "level": int(
                    (account.get("level_info") or {}).get("current_level") or 0
                ),
            },
        }
