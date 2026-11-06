"""
强实名（id_bind>=1）+ hotProject 场景的离线契约测试。

没有真实活动可测时，用这些用例把接口约定固定下来：
- prepare 阶段的 buyer_info 是「列表」
- createV2 阶段的 buyer_info 是「JSON 字符串」
- hot 项目 body 里必须带 ctoken / ptoken
- 联系人 buyer/tel 要下发
- -352 风控 → 验证 → 重试 → 成功
"""
import json

import pytest

import src.ticket_grabber as tg
from src.api_client import BilibiliAPI, ProjectInfo, ScreenInfo
from src.ticket_grabber import GrabPhase, TicketGrabber

VIEWER = {
    "id": 11,
    "name": "张三",
    "personal_id": "000000000000000000",
    "id_type": 0,
    "tel": "13800000000",
    "verify_status": 1,
}


@pytest.fixture
def api(sample_config, no_network):
    return BilibiliAPI(sample_config)


class ScriptedRequests:
    """按 URL 返回预置响应，并记录每次请求。"""

    def __init__(self, prepare_data=None, create_handler=None):
        self.calls = []
        self.prepare_data = prepare_data or {"token": "ORDER_TOK", "ptoken": "PTOK=="}
        self.create_handler = create_handler

    def __call__(self, method, url, json_data=None, params=None, referer=None):
        self.calls.append({"url": url, "body": json_data})
        if "/ticket/order/prepare" in url:
            return {"errno": 0, "data": dict(self.prepare_data)}
        if "/ticket/order/createV2" in url:
            if self.create_handler:
                # create_calls 已包含本次调用
                return self.create_handler(len(self.create_calls))
            return {"errno": 0, "msg": "", "data": {"orderId": "123", "token": ""}}
        return {"errno": 0, "data": {}}

    @property
    def create_calls(self):
        return [c for c in self.calls if "/ticket/order/createV2" in c["url"]]

    @property
    def prepare_calls(self):
        return [c for c in self.calls if "/ticket/order/prepare" in c["url"]]


class TestRealNamePayload:
    def test_prepare_gets_list_and_create_gets_json_string(self, api, monkeypatch):
        script = ScriptedRequests()
        monkeypatch.setattr(api, "_request", script)

        api.create_order(
            project_id=1, screen_id=2, sku_id=3, count=1,
            viewers=[VIEWER], id_bind=1,
            buyer_name="张三", buyer_tel="13800000000",
        )

        prepare_body = script.prepare_calls[0]["body"]
        assert isinstance(prepare_body["buyer_info"], list)
        assert prepare_body["buyer_info"][0]["name"] == "张三"
        assert prepare_body["buyer_info"][0]["personal_id"] == VIEWER["personal_id"]

        create_body = script.create_calls[0]["body"]
        assert isinstance(create_body["buyer_info"], str)
        buyers = json.loads(create_body["buyer_info"])
        assert buyers[0]["name"] == "张三"
        assert buyers[0]["isBuyerValid"] is True
        assert buyers[0]["isBuyerInfoVerified"] is True

    def test_non_realname_prepare_keeps_empty_buyer_info(self, api, monkeypatch):
        """回归保护：普通项目（id_bind=0）走的是已验证通过的旧行为。"""
        script = ScriptedRequests()
        monkeypatch.setattr(api, "_request", script)

        api.create_order(
            project_id=1, screen_id=2, sku_id=3, count=1,
            viewers=[VIEWER], id_bind=0,
            buyer_name="张三", buyer_tel="13800000000",
        )

        assert script.prepare_calls[0]["body"]["buyer_info"] == ""
        assert script.create_calls[0]["body"]["buyer_info"] == "[]"

    def test_falls_back_to_prepare_buyers(self, api, monkeypatch):
        """没手选观演人时，用 prepare 返回的观演人。"""
        script = ScriptedRequests(prepare_data={
            "token": "T", "ptoken": "P",
            "buyer_info": [{"id": 7, "name": "李四", "personal_id": "X1"}],
        })
        monkeypatch.setattr(api, "_request", script)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1, id_bind=1)

        buyers = json.loads(script.create_calls[0]["body"]["buyer_info"])
        assert buyers[0]["name"] == "李四"

    def test_prepare_buyer_info_string_is_passed_through(self, api, monkeypatch):
        script = ScriptedRequests(prepare_data={
            "token": "T", "ptoken": "P",
            "buyer_info": json.dumps([{"id": 8, "name": "王五"}]),
        })
        monkeypatch.setattr(api, "_request", script)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1, id_bind=1)

        buyers = json.loads(script.create_calls[0]["body"]["buyer_info"])
        assert buyers[0]["name"] == "王五"

    def test_malformed_viewer_entries_are_skipped(self, api, monkeypatch):
        script = ScriptedRequests()
        monkeypatch.setattr(api, "_request", script)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         viewers=[None, "bad", VIEWER], id_bind=1)

        buyers = json.loads(script.create_calls[0]["body"]["buyer_info"])
        assert len(buyers) == 1
        assert buyers[0]["name"] == "张三"


class TestHotProjectPayload:
    def test_payload_contains_ctoken_and_ptoken(self, api, monkeypatch):
        script = ScriptedRequests()
        monkeypatch.setattr(api, "_request", script)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         viewers=[VIEWER], id_bind=1, is_hot=True)

        body = script.create_calls[0]["body"]
        assert "ctoken" in body and body["ctoken"]
        assert body["ptoken"] == "PTOK=="
        assert "ptoken=PTOK==" in script.create_calls[0]["url"]
        assert body["newRisk"] is True

    def test_prepare_contains_ctoken(self, api, monkeypatch):
        script = ScriptedRequests()
        monkeypatch.setattr(api, "_request", script)

        api.create_order(project_id=1, screen_id=2, sku_id=3, count=1,
                         id_bind=0, is_hot=True)

        assert script.prepare_calls[0]["body"]["token"]


class TestHotRealNameEndToEnd:
    def test_risk_then_success(self, api, sample_config, monkeypatch, no_sleep):
        """强实名 + hot：第一次 -352 风控，验证通过后第二次下单成功。"""
        monkeypatch.setattr(tg, "_show_pay_qrcode", lambda *a, **k: None)
        monkeypatch.setattr(tg, "_notify_success", lambda *a, **k: None)

        sample_config.strategy.enable_stock_check = False
        sample_config.event.hot_project = True
        sample_config.event.project_id = 1001701
        sample_config.event.screen_id = 2026
        sample_config.event.sku_id = 303

        def create_handler(attempt_no):
            if attempt_no == 1:
                return {
                    "errno": -352,
                    "msg": "风控",
                    "data": {"ga_data": {"riskParams": {"v_voucher": "vv"}}},
                }
            return {"errno": 0, "msg": "", "data": {"orderId": "9527", "token": ""}}

        script = ScriptedRequests(create_handler=create_handler)
        monkeypatch.setattr(api, "_request", script)

        monkeypatch.setattr(api, "check_login", lambda: True)
        monkeypatch.setattr(api, "get_user_info", lambda: {"vipStatus": 1})
        monkeypatch.setattr(api, "get_project_info", lambda pid: ProjectInfo(
            id=pid, name="强实名hot项目", id_bind=1, hot_project=True,
            screens=[], sale_begin=0))
        monkeypatch.setattr(api, "get_screen_info", lambda pid, sid: ScreenInfo(
            id=sid, name="场次", skus=[
                {"id": 303, "desc": "预售票", "price": 9900,
                 "stock": {"count": 5}},
            ]))

        monkeypatch.setattr(TicketGrabber, "_try_gaia_verify",
                            lambda self, result: True)

        grabber = TicketGrabber(sample_config, viewers=[VIEWER], api=api)
        result = grabber.run()

        assert result.success is True
        assert result.order_id == "9527"
        assert result.attempts == 2
        assert grabber.phase is GrabPhase.SUCCESS

        # 两次 create 都必须带观演人与联系人
        assert len(script.create_calls) == 2
        for call in script.create_calls:
            body = call["body"]
            assert json.loads(body["buyer_info"])[0]["name"] == "张三"
            assert body["buyer"] == "张三"
            assert body["tel"] == "13800000000"
