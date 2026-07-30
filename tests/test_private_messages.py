import json
import os
import tempfile
import unittest

from private_messages import (
    MESSAGES_URL,
    SEND_URL,
    SESSIONS_URL,
    PrivateMessageClient,
    assess_private_message,
    is_protected_sender,
    reply_scope_allows,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self):
        self.session_max = 10
        self.messages = []
        self.posts = []

    def get(self, url, **kwargs):
        if url == SESSIONS_URL:
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "session_list": [
                            {
                                "talker_id": 20002,
                                "session_type": 1,
                                "max_seqno": self.session_max,
                                "account_info": {"name": "测试用户"},
                            }
                        ]
                    },
                }
            )
        if url == MESSAGES_URL:
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "max_seqno": self.session_max,
                        "messages": self.messages,
                    },
                }
            )
        raise AssertionError(url)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"code": 0, "data": {"msg_key": 123}})


class PrivateMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.http = FakeHttp()
        self.now = 2_000_000_000
        self.client = PrivateMessageClient(
            self.temp.name,
            http=self.http,
            now=lambda: self.now,
        )
        self.config = {
            "SESSDATA": "sess",
            "BILI_JCT": "csrf",
            "DEDE_USER_ID": "10001",
            "OWNER_MID": "30003",
            "PRIVATE_MESSAGE_MAX_MESSAGE_AGE": 3600,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_first_poll_only_initializes_cursor(self):
        self.http.messages = [
            {
                "msg_key": 1,
                "msg_seqno": 10,
                "sender_uid": 20002,
                "msg_type": 1,
                "timestamp": self.now,
                "content": json.dumps({"content": "旧消息"}),
            }
        ]
        self.assertEqual(self.client.poll(self.config), [])
        state_path = os.path.join(
            self.temp.name,
            "data",
            "private_message_state.json",
        )
        with open(state_path, "r", encoding="utf-8") as file:
            state = json.load(file)
        self.assertTrue(state["initialized"])
        self.assertEqual(state["sessions"]["1:20002"], 10)

    def test_new_inbound_text_is_returned_once(self):
        self.client.poll(self.config)
        self.http.session_max = 11
        self.http.messages = [
            {
                "msg_key": 11,
                "msg_seqno": 11,
                "sender_uid": 20002,
                "msg_type": 1,
                "timestamp": self.now,
                "content": json.dumps({"content": "你好"}, ensure_ascii=False),
            }
        ]
        messages = self.client.poll(self.config)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(self.client.poll(self.config), [])

    def test_account_change_resets_cursor_and_skips_history(self):
        self.client.poll(self.config)
        self.http.session_max = 11
        switched = dict(self.config, DEDE_USER_ID="99999")
        self.http.messages = [
            {
                "msg_key": 11,
                "msg_seqno": 11,
                "sender_uid": 20002,
                "msg_type": 1,
                "timestamp": self.now,
                "content": json.dumps({"content": "新账号旧消息"}, ensure_ascii=False),
            }
        ]
        self.assertEqual(self.client.poll(switched), [])

    def test_send_payload(self):
        self.assertTrue(self.client.send_text(self.config, 20002, "收到"))
        url, kwargs = self.http.posts[0]
        self.assertEqual(url, SEND_URL)
        self.assertEqual(kwargs["data"]["msg[receiver_id]"], "20002")
        self.assertEqual(
            json.loads(kwargs["data"]["msg[content]"])["content"],
            "收到",
        )
        self.assertEqual(kwargs["data"]["csrf"], "csrf")

    def test_poll_limit_leaves_remaining_message_for_next_round(self):
        self.config["PRIVATE_MESSAGE_MAX_PER_POLL"] = 1
        self.client.poll(self.config)
        self.http.session_max = 12
        self.http.messages = [
            {
                "msg_key": 12,
                "msg_seqno": 12,
                "sender_uid": 20002,
                "msg_type": 1,
                "timestamp": self.now,
                "content": json.dumps({"content": "第二条"}, ensure_ascii=False),
            },
            {
                "msg_key": 11,
                "msg_seqno": 11,
                "sender_uid": 20002,
                "msg_type": 1,
                "timestamp": self.now,
                "content": json.dumps({"content": "第一条"}, ensure_ascii=False),
            },
        ]
        first = self.client.poll(self.config)
        second = self.client.poll(self.config)
        self.assertEqual([item["content"] for item in first], ["第一条"])
        self.assertEqual([item["content"] for item in second], ["第二条"])

    def test_bilibili_video_share_card_is_converted_to_safe_text(self):
        self.client.poll(self.config)
        self.http.session_max = 11
        self.http.messages = [
            {
                "msg_key": 11,
                "msg_seqno": 11,
                "sender_uid": 20002,
                "msg_type": 7,
                "timestamp": self.now,
                "content": json.dumps({
                    "bvid": "BV1vxT46REZa",
                    "title": "测试视频",
                }, ensure_ascii=False),
            }
        ]
        messages = self.client.poll(self.config)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content_type"], "video_share")
        self.assertIn("测试视频", messages[0]["content"])
        self.assertIn(
            "https://www.bilibili.com/video/BV1vxT46REZa",
            messages[0]["content"],
        )
        self.assertFalse(assess_private_message(messages[0]["content"]).should_block)

    def test_safety_rules(self):
        self.assertFalse(
            assess_private_message("看看 https://www.bilibili.com/video/BV1xx").should_block
        )
        unknown = assess_private_message("点这里 https://evil.example.com/a")
        self.assertTrue(unknown.should_block)
        self.assertIn("未信任", unknown.reason)
        self.assertTrue(assess_private_message("加我裸聊").should_block)
        self.assertTrue(assess_private_message("看片 hxxps://b23[.]tv/abc").should_block)

    def test_owner_and_whitelist_are_protected(self):
        config = {
            "OWNER_MID": "30003",
            "PRIVATE_MESSAGE_BLOCK_WHITELIST_UIDS": ["40004"],
            "PRIVATE_MESSAGE_REPLY_WHITELIST_UIDS": ["40004"],
            "PRIVATE_MESSAGE_REPLY_SCOPE": "whitelist",
        }
        self.assertTrue(is_protected_sender("30003", config))
        self.assertTrue(is_protected_sender("40004", config))
        self.assertTrue(reply_scope_allows("30003", config))
        self.assertTrue(reply_scope_allows("40004", config))
        self.assertFalse(reply_scope_allows("50005", config))


if __name__ == "__main__":
    unittest.main()
