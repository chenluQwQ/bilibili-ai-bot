import unittest

from bili_login import (
    QR_CONFIRMED,
    QR_GENERATE_URL,
    QR_POLL_URL,
    BiliQrLoginManager,
)


class FakeResponse:
    def __init__(self, payload, cookies=None):
        self._payload = payload
        self.cookies = FakeCookies(cookies or {})

    def json(self):
        return self._payload


class FakeCookies:
    def __init__(self, values=None):
        self.values = values or {}

    def get_dict(self):
        return dict(self.values)


class FakeSession:
    def __init__(self):
        self.cookies = FakeCookies()

    def get(self, url, **kwargs):
        if url == QR_GENERATE_URL:
            return FakeResponse({
                "code": 0,
                "data": {
                    "url": "https://passport.bilibili.com/h5-app/passport/login/scan",
                    "qrcode_key": "qr-key",
                },
            })
        if url == QR_POLL_URL:
            return FakeResponse({
                "code": 0,
                "data": {
                    "code": QR_CONFIRMED,
                    "url": (
                        "https://www.bilibili.com/?"
                        "SESSDATA=sess&bili_jct=csrf&DedeUserID=10001"
                    ),
                    "refresh_token": "refresh",
                },
            })
        if url.startswith("https://www.bilibili.com/?"):
            return FakeResponse({})
        return FakeResponse({
            "code": 0,
            "data": {
                "isLogin": True,
                "mid": 10001,
                "uname": "测试账号",
                "level_info": {"current_level": 6},
            },
        })


class BiliQrLoginTests(unittest.TestCase):
    def test_confirmed_login_returns_server_side_config(self):
        manager = BiliQrLoginManager(now=lambda: 1000)
        manager._image_data_url = lambda url: "data:image/png;base64,test"

        import bili_login

        original = bili_login.requests.Session
        bili_login.requests.Session = FakeSession
        try:
            started = manager.start()
            result = manager.poll(started["token"])
        finally:
            bili_login.requests.Session = original

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["config"]["SESSDATA"], "sess")
        self.assertEqual(result["config"]["BILI_JCT"], "csrf")
        self.assertEqual(result["config"]["REFRESH_TOKEN"], "refresh")
        self.assertEqual(result["account"]["mid"], "10001")

    def test_expired_local_token(self):
        manager = BiliQrLoginManager(now=lambda: 1000)
        result = manager.poll("missing")
        self.assertEqual(result["status"], "expired")


if __name__ == "__main__":
    unittest.main()
