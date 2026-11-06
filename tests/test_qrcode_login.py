"""扫码登录的测试（网络全部 mock）。"""
import pytest

from src.qrcode_login import (
    LoginResult,
    QRCodeLogin,
    extract_login_cookies,
)

COOKIES = [
    {"name": "DedeUserID", "value": "10086"},
    {"name": "SESSDATA", "value": "sess-value"},
    {"name": "DedeUserID__ckMd5", "value": "md5-value"},
    {"name": "bili_jct", "value": "csrf-value"},
]


class TestExtractLoginCookies:
    def test_maps_by_name(self):
        result = extract_login_cookies(COOKIES)
        assert result == {
            "sessdata": "sess-value",
            "bili_jct": "csrf-value",
            "dede_user_id": "10086",
            "dede_user_id_ckmd5": "md5-value",
        }

    def test_order_independent(self):
        """回归测试：旧实现按数组下标取值，顺序一变就取错字段。"""
        reversed_cookies = list(reversed(COOKIES))
        assert extract_login_cookies(reversed_cookies) == extract_login_cookies(COOKIES)

    def test_accepts_dict(self):
        result = extract_login_cookies({"SESSDATA": "s", "bili_jct": "j"})
        assert result["sessdata"] == "s"
        assert result["bili_jct"] == "j"
        assert result["dede_user_id"] == ""

    def test_missing_names_become_empty(self):
        result = extract_login_cookies([{"name": "SESSDATA", "value": "s"}])
        assert result["sessdata"] == "s"
        assert result["bili_jct"] == ""

    def test_tolerates_malformed_items(self):
        result = extract_login_cookies([{"name": "SESSDATA", "value": "s"}, None, "x"])
        assert result["sessdata"] == "s"

    def test_empty_input(self):
        assert extract_login_cookies(None)["sessdata"] == ""


class TestBuildLoginResult:
    def test_from_cookie_info(self):
        login = QRCodeLogin()
        data = {"cookie_info": {"cookies": COOKIES}}
        result = login._build_login_result(data, {})
        assert isinstance(result, LoginResult)
        assert result.success is True
        assert result.sessdata == "sess-value"
        assert result.bili_jct == "csrf-value"

    def test_falls_back_to_response_cookies(self):
        login = QRCodeLogin()
        result = login._build_login_result(
            {}, {"_cookies": {"SESSDATA": "s2", "bili_jct": "j2"}})
        assert result.success is True
        assert result.sessdata == "s2"

    def test_returns_none_without_credentials(self):
        login = QRCodeLogin()
        assert login._build_login_result({"cookie_info": {"cookies": []}}, {}) is None

    def test_requires_sessdata(self):
        login = QRCodeLogin()
        only_jct = [{"name": "bili_jct", "value": "j"}]
        assert login._build_login_result({"cookie_info": {"cookies": only_jct}}, {}) is None


class TestLoginFlow:
    def _login(self, monkeypatch, poll_payload, timeout=5):
        login = QRCodeLogin(timeout=timeout)
        monkeypatch.setattr(login, "get_qrcode_url", lambda: ("url", "key"))
        monkeypatch.setattr(login, "poll_scan_status", lambda: poll_payload)
        return login.login(display_qrcode=False)

    def test_success(self, monkeypatch):
        result = self._login(monkeypatch, {
            "data": {"code": 0, "cookie_info": {"cookies": COOKIES}},
        })
        assert result.success is True
        assert result.dede_user_id == "10086"

    def test_expired(self, monkeypatch):
        result = self._login(monkeypatch, {"data": {"code": 86038}})
        assert result.success is False
        assert "过期" in result.message

    def test_unknown_status(self, monkeypatch):
        result = self._login(monkeypatch, {"data": {"code": 12345}})
        assert result.success is False
        assert "未知状态" in result.message

    def test_timeout(self, monkeypatch):
        result = self._login(monkeypatch, {"data": {"code": 86101}}, timeout=0)
        assert result.success is False
        assert "超时" in result.message

    def test_success_without_cookies_reports_failure(self, monkeypatch):
        result = self._login(monkeypatch, {"data": {"code": 0, "cookie_info": {"cookies": []}}})
        assert result.success is False
        assert "未获取到cookie" in result.message


class TestQRCodeImage:
    def test_generates_png(self):
        png = QRCodeLogin().generate_qrcode_image("https://example.com")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 100


class TestPollWithoutKey:
    def test_requires_qrcode_key(self):
        with pytest.raises(Exception, match="请先获取二维码"):
            QRCodeLogin().poll_scan_status()
