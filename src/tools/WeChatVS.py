"""
此工具用于对自有微信公众号服务后端做简易联调、巡检和运维验证。

边界说明：
- 只向你显式配置的服务端 URL 发送请求。
- 不负责获取、破解或枚举用户 openid；请使用测试号/自有用户的 openid。
- 适合在授权环境中模拟微信服务器转发的公众号事件和消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any, Literal
from urllib.parse import urlencode
from xml.etree.ElementTree import Element, SubElement, tostring

import requests


MessageFormat = Literal["xml", "json"]


@dataclass(slots=True)
class WeChatVSConfig:
    """微信公众号后端联调配置。"""

    endpoint: str
    token: str = ""
    app_id: str = ""
    default_openid: str = ""
    timeout_seconds: float = 10.0
    message_format: MessageFormat = "xml"
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WeChatVSResponse:
    """保留 HTTP 响应的关键字段，方便 agent 消费。"""

    status_code: int
    text: str
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class WeChatVSClient:
    """向自有微信公众号服务后端发送测试消息的轻量客户端。"""

    def __init__(self, config: WeChatVSConfig) -> None:
        if not config.endpoint.strip():
            raise ValueError("WeChatVSConfig.endpoint is required")
        if config.message_format not in ("xml", "json"):
            raise ValueError("message_format must be 'xml' or 'json'")
        self.config = config

    def send_text(
        self,
        content: str,
        *,
        openid: str | None = None,
        msg_id: int | None = None,
        created_at: int | None = None,
    ) -> WeChatVSResponse:
        """模拟用户给公众号发送文本消息。"""
        payload = {
            "ToUserName": self._app_id(),
            "FromUserName": self._openid(openid),
            "CreateTime": self._timestamp(created_at),
            "MsgType": "text",
            "Content": content,
            "MsgId": msg_id or int(time.time() * 1000),
        }
        return self._post(payload)

    def send_subscribe(self, *, openid: str | None = None, created_at: int | None = None) -> WeChatVSResponse:
        """模拟用户关注公众号事件。"""
        return self.send_event("subscribe", openid=openid, created_at=created_at)

    def send_unsubscribe(self, *, openid: str | None = None, created_at: int | None = None) -> WeChatVSResponse:
        """模拟用户取消关注公众号事件。"""
        return self.send_event("unsubscribe", openid=openid, created_at=created_at)

    def send_click(
        self,
        event_key: str,
        *,
        openid: str | None = None,
        created_at: int | None = None,
    ) -> WeChatVSResponse:
        """模拟用户点击自定义菜单。"""
        return self.send_event("CLICK", event_key=event_key, openid=openid, created_at=created_at)

    def send_event(
        self,
        event: str,
        *,
        event_key: str = "",
        openid: str | None = None,
        created_at: int | None = None,
    ) -> WeChatVSResponse:
        """模拟微信事件推送。"""
        payload = {
            "ToUserName": self._app_id(),
            "FromUserName": self._openid(openid),
            "CreateTime": self._timestamp(created_at),
            "MsgType": "event",
            "Event": event,
        }
        if event_key:
            payload["EventKey"] = event_key
        return self._post(payload)

    def send_custom(self, payload: dict[str, Any]) -> WeChatVSResponse:
        """发送自定义 payload，便于覆盖暂未封装的微信消息类型。"""
        normalized = {
            "ToUserName": payload.get("ToUserName") or self._app_id(),
            "FromUserName": payload.get("FromUserName") or self._openid(None),
            "CreateTime": payload.get("CreateTime") or self._timestamp(None),
            **payload,
        }
        return self._post(normalized)

    def build_signed_url(self, timestamp: int | None = None, nonce: str | None = None) -> str:
        """按微信公众号服务器配置规则拼接签名参数。"""
        ts = str(self._timestamp(timestamp))
        nc = nonce or str(int(time.time() * 1000))
        query = {"timestamp": ts, "nonce": nc}
        if self.config.token:
            query["signature"] = self._signature(ts, nc)

        separator = "&" if "?" in self.config.endpoint else "?"
        return f"{self.config.endpoint}{separator}{urlencode(query)}"

    def _post(self, payload: dict[str, Any]) -> WeChatVSResponse:
        url = self.build_signed_url()
        headers = {"Accept": "*/*", **self.config.extra_headers}

        if self.config.message_format == "json":
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", **headers},
                timeout=self.config.timeout_seconds,
            )
        else:
            response = requests.post(
                url,
                data=dict_to_wechat_xml(payload),
                headers={"Content-Type": "application/xml", **headers},
                timeout=self.config.timeout_seconds,
            )

        return WeChatVSResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )

    def _signature(self, timestamp: str, nonce: str) -> str:
        parts = sorted([self.config.token, timestamp, nonce])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()

    def _openid(self, openid: str | None) -> str:
        selected = (openid or self.config.default_openid).strip()
        if not selected:
            raise ValueError("openid is required; pass openid=... or set default_openid")
        return selected

    def _app_id(self) -> str:
        return self.config.app_id.strip() or "test_public_account"

    @staticmethod
    def _timestamp(value: int | None) -> int:
        return int(value or time.time())


def dict_to_wechat_xml(payload: dict[str, Any]) -> str:
    """把字典转换成微信公众号消息 XML。"""
    xml = Element("xml")
    for key, value in payload.items():
        child = SubElement(xml, str(key))
        child.text = "" if value is None else str(value)
    return tostring(xml, encoding="utf-8", xml_declaration=False).decode("utf-8")


def quick_text_request(
    endpoint: str,
    openid: str,
    content: str,
    *,
    token: str = "",
    app_id: str = "",
    timeout_seconds: float = 10.0,
) -> WeChatVSResponse:
    """最简入口：给自有公众号后端模拟一条用户文本消息。"""
    client = WeChatVSClient(
        WeChatVSConfig(
            endpoint=endpoint,
            token=token,
            app_id=app_id,
            default_openid=openid,
            timeout_seconds=timeout_seconds,
        )
    )
    return client.send_text(content)
