"""API 客户端的测试（网络全部 mock）。"""
import json

import pytest

import src.api_client as ac
from src.api_client import BilibiliAPI


@pytest.fixture
def api(sample_config, no_network):
    return BilibiliAPI(sample_config)


class TestCookieHandling:
    def test_build_cookie_string_skips_empty(self, api):
        api.cookies = {"SESSDATA": "abc", "empty": "", "zero": None}
        cookie_str = api._build_cookie_string()
        assert "SESSDATA=abc" in cookie_str
        assert "empty" not in cookie_str
        assert "zero" not in cookie_str

    def test_cookie_values_are_strings(self, api):
        api.cookies = {"n": 123}
        assert api._build_cookie_string() == "n=123"

    def test_extra_cookies_merged(self, sample_config, no_network):
        sample_config.user.cookies = {"buvid3": "B3", "buvid4": "B4"}
        api = BilibiliAPI(sample_config)
        assert api.cookies["buvid3"] == "B3"
        assert api.cookies["buvid4"] == "B4"
        assert api.cookies["SESSDATA"] == sample_config.user.sessdata


class TestRequest:
    def test_non_json_response_returns_error(self, api, monkeypatch):
        class BadResponse:
            status_code = 502
            text = "<html>bad gateway</html>"

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(
            ac.curl_requests, "request", lambda *a, **k: BadResponse())
        result = api._request("GET", "https://example.invalid")
        assert result["errno"] == 502
        assert result["data"] == {}

    def test_json_response_passthrough(self, api, monkeypatch):
        class GoodResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {"errno": 0, "data": {"ok": True}}

        monkeypatch.setattr(
            ac.curl_requests, "request", lambda *a, **k: GoodResponse())
        assert api._request("GET", "https://example.invalid")["data"] == {"ok": True}


class TestProjectInfo:
    def test_maps_fields(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request", lambda *a, **k: {
            "errno": 0,
            "data": {
                "id": 1001701,
                "name": "活动",
                "id_bind": 1,
                "hotProject": True,
                "screen_list": [{"id": 1}],
                "sale_begin": 1700000000,
                "status": "on_sale",
            },
        })
        info = api.get_project_info(1001701)
        assert info.id == 1001701
        assert info.name == "活动"
        assert info.id_bind == 1
        assert info.hot_project is True
        assert info.screens == [{"id": 1}]
        assert info.sale_begin == 1700000000

    def test_missing_fields_use_defaults(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request", lambda *a, **k: {"errno": -1, "data": {}})
        info = api.get_project_info(42)
        assert info.id == 42
        assert info.name == ""
        assert info.screens == []


class TestCheckLogin:
    def test_logged_in(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request",
                            lambda *a, **k: {"data": {"isLogin": True}})
        assert api.check_login() is True

    def test_not_logged_in(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request",
                            lambda *a, **k: {"data": {"isLogin": False}})
        assert api.check_login() is False

    def test_exception_returns_false(self, api, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("x")

        monkeypatch.setattr(api, "_request", boom)
        assert api.check_login() is False


class TestPrepareToken:
    def test_returns_data_on_success(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request", lambda *a, **k: {
            "errno": 0, "data": {"token": "T", "ptoken": "P"},
        })
        data, errno, msg = api.prepare_token(1, 2, 3, 1)
        assert data == {"token": "T", "ptoken": "P"}
        assert errno == 0
        assert msg == ""

    def test_retries_on_401_then_succeeds(self, api, monkeypatch):
        calls = {"n": 0}

        def fake_request(*a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"errno": -401}
            return {"errno": 0, "data": {"token": "T"}}

        monkeypatch.setattr(api, "_request", fake_request)
        monkeypatch.setattr(ac.time, "sleep", lambda *_: None)
        data, errno, _ = api.prepare_token(1, 2, 3, 1)
        assert data == {"token": "T"}
        assert errno == 0
        assert calls["n"] == 3

    def test_business_error_is_not_retried(self, api, monkeypatch):
        """回归测试：座位信息为空曾被重试 10 次并吞掉真实错误码。"""
        calls = {"n": 0}

        def fake_request(*a, **k):
            calls["n"] += 1
            return {"errno": 80110000, "msg": "座位信息为空"}

        monkeypatch.setattr(api, "_request", fake_request)
        data, errno, msg = api.prepare_token(1, 2, 3, 1)
        assert data == {}
        assert errno == 80110000
        assert "座位信息为空" in msg
        assert calls["n"] == 1

    def test_returns_last_error_after_retryable_failures(self, api, monkeypatch):
        monkeypatch.setattr(api, "_request", lambda *a, **k: {"errno": 429})
        monkeypatch.setattr(ac.time, "sleep", lambda *_: None)
        data, errno, _ = api.prepare_token(1, 2, 3, 1, retry=3)
        assert data == {}
        assert errno == 429


class TestCreateOrder:
    def _patch(self, api, monkeypatch, project_calls=None):
        captured = {}

        def fake_prepare(project_id, screen_id, sku_id, count, buyer_info=None):
            return ({"token": "TOK", "ptoken": "PTOK", "buyer_info": []}, 0, "")

        def fake_request(method, url, json_data=None, params=None,
                         referer=None):
            captured["method"] = method
            captured["url"] = url
            captured["body"] = json_data
            return {"errno": 0, "msg": "", "data": {"orderId": "888"}}

        monkeypatch.setattr(api, "prepare_token", fake_prepare)
        monkeypatch.setattr(api, "_request", fake_request)

        if project_calls is not None:
            def fake_project(pid):
                project_calls.append(pid)
                return type("P", (), {"id_bind": 1})()

            monkeypatch.setattr(api, "get_project_info", fake_project)

        return captured

    def test_uses_cached_id_bind_without_extra_request(self, api, monkeypatch):
        calls = []
        captured = self._patch(api, monkeypatch, project_calls=calls)

        result, token, ptoken = api.create_order(
            project_id=1, screen_id=2, sku_id=3, count=1,
            id_bind=1,
        )
        assert calls == []  # 不应再请求项目详情
        assert result["errno"] == 0
        assert token == "TOK" and ptoken == "PTOK"
        assert "ptoken=PTOK" in captured["url"]
        assert captured["body"]["ptoken"] == "PTOK"

    def test_fetches_id_bind_when_not_provided(self, api, monkeypatch):
        calls = []
        self._patch(api, monkeypatch, project_calls=calls)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1)
        assert calls == [1]

    def test_body_contains_device_and_position(self, api, monkeypatch):
        captured = self._patch(api, monkeypatch)
        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         pay_money=10000, id_bind=0)
        body = captured["body"]
        assert body["deviceId"] == api.device_id
        assert body["pay_money"] == 10000
        assert body["newRisk"] is True
        assert "clickPosition" in body
        position = json.loads(body["clickPosition"])
        assert {"x", "y", "origin", "now"} <= set(position)

    def test_viewers_serialized_to_buyer_info(self, api, monkeypatch):
        captured = self._patch(api, monkeypatch)
        viewers = [{"id": 11, "name": "张三", "personal_id": "110", "id_type": 1}]
        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         viewers=viewers, id_bind=1)
        buyers = json.loads(captured["body"]["buyer_info"])
        assert buyers[0]["name"] == "张三"
        assert buyers[0]["isBuyerValid"] is True

    def test_empty_buyer_info_when_id_bind_zero(self, api, monkeypatch):
        captured = self._patch(api, monkeypatch)
        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         viewers=[{"id": 1, "name": "x"}], id_bind=0)
        assert captured["body"]["buyer_info"] == "[]"

    def test_contact_info_sent_when_provided(self, api, monkeypatch):
        """回归测试：buyer/tel 曾只接收不使用，导致 errno=209001。"""
        captured = self._patch(api, monkeypatch)
        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         buyer_name="张三", buyer_tel="13800000000",
                         id_bind=0)
        assert captured["body"]["buyer"] == "张三"
        assert captured["body"]["tel"] == "13800000000"

    def test_contact_info_omitted_when_empty(self, api, monkeypatch):
        captured = self._patch(api, monkeypatch)
        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1, id_bind=0)
        assert "buyer" not in captured["body"]
        assert "tel" not in captured["body"]

    def test_prepare_failure_returns_real_errno(self, api, monkeypatch):
        """prepare 的业务错误码必须透传，不能统一吞成 -1。"""
        monkeypatch.setattr(api, "prepare_token",
                            lambda *a, **k: ({}, 80110000, "座位信息为空"))
        result, token, ptoken = api.create_order(
            project_id=1, screen_id=2, sku_id=3, count=1, id_bind=0)
        assert result["errno"] == 80110000
        assert "座位信息为空" in result["msg"]
        assert token == "" and ptoken == ""

    def test_request_exception_captured(self, api, monkeypatch):
        monkeypatch.setattr(api, "prepare_token",
                            lambda *a, **k: ({"token": "T", "ptoken": "P"}, 0, ""))

        def boom(*a, **k):
            raise RuntimeError("conn reset")

        monkeypatch.setattr(api, "_request", boom)
        result, token, ptoken = api.create_order(
            project_id=1, screen_id=2, sku_id=3, count=1, id_bind=0)
        assert result["errno"] == -1
        assert "conn reset" in result["msg"]


class TestScreenInfo:
    def test_found(self, api, monkeypatch):
        monkeypatch.setattr(api, "get_project_info", lambda pid: type("P", (), {
            "screens": [{
                "id": 2, "name": "场次", "start_time": "a", "end_time": "b",
                "ticket_list": [{"id": 3}],
            }],
        })())
        screen = api.get_screen_info(1, 2)
        assert screen.name == "场次"
        assert screen.skus == [{"id": 3}]

    def test_missing_screen_raises(self, api, monkeypatch):
        monkeypatch.setattr(api, "get_project_info",
                            lambda pid: type("P", (), {"screens": []})())
        with pytest.raises(Exception, match="未找到场次"):
            api.get_screen_info(1, 999)
