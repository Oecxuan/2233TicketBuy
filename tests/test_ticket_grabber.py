"""抢票核心逻辑的测试（全部使用替身，不触网）。"""
import time

import pytest

import src.ticket_grabber as tg
from src.ticket_grabber import GrabPhase, TicketGrabber, TicketResult


@pytest.fixture(autouse=True)
def silent_notify(monkeypatch):
    """拦截成功通知，避免测试时弹窗/响铃。"""
    monkeypatch.setattr(tg, "_notify_success", lambda *a, **k: None)
    monkeypatch.setattr(tg, "_show_pay_qrcode", lambda *a, **k: None)


@pytest.fixture
def grabber(sample_config, fake_api, no_sleep):
    return TicketGrabber(sample_config, api=fake_api)


def make_result(message="", success=False, raw=None):
    return TicketResult(success=success, message=message, raw_data=raw)


class TestInit:
    def test_uses_injected_api(self, sample_config, fake_api):
        g = TicketGrabber(sample_config, api=fake_api)
        assert g.api is fake_api

    def test_defaults_from_config(self, sample_config, fake_api, no_sleep):
        sample_config.strategy.order_interval = 0.42
        sample_config.strategy.delta = 0.09
        g = TicketGrabber(sample_config, api=fake_api)
        assert g.grab_interval == 0.42
        assert g._delta == 0.09

    def test_buyer_extracted_from_viewers(self, sample_config, fake_api, no_sleep):
        viewers = [{"name": "张三", "tel": "138"}]
        g = TicketGrabber(sample_config, viewers=viewers, api=fake_api)
        assert g.buyer_name == "张三"
        assert g.buyer_tel == "138"

    def test_hot_project_detected_from_api(self, sample_config, fake_api,
                                           no_sleep, monkeypatch):
        from src.api_client import ProjectInfo

        # 检测到热门项目会写回配置文件，测试中必须拦截
        monkeypatch.setattr("src.config.save_config", lambda *a, **k: None)

        def hot_info(project_id):
            return ProjectInfo(id=project_id, hot_project=True, sale_begin=0)

        fake_api.get_project_info = hot_info
        sample_config.event.hot_project = False
        g = TicketGrabber(sample_config, api=fake_api)
        assert g._is_hot is True
        # 检测结果会写回内存配置
        assert sample_config.event.hot_project is True


class TestHandleGrabResult:
    def test_success_stops_loop(self, grabber):
        result = make_result(success=True)
        result.order_id = "123"
        assert grabber._handle_grab_result(result) is False
        assert grabber.phase is GrabPhase.SUCCESS
        assert grabber.result is result

    @pytest.mark.parametrize("code", [
        -101, -403, 100003, 100048, 100079, 100051, 209001, 80110000,
    ])
    def test_fatal_codes_stop_loop(self, grabber, code):
        assert grabber._handle_grab_result(make_result(f"errno={code}: boom")) is False

    @pytest.mark.parametrize("code", [
        1, 412, -412, 429, 10007, 100001, 100009, 900001, 900002,
        219, 100002, 100004, 3, 221, 100044, 100034, -401,
    ])
    def test_retryable_codes_continue(self, grabber, code):
        assert grabber._handle_grab_result(make_result(f"errno={code}: retry")) is True

    def test_unknown_error_continues(self, grabber):
        assert grabber._handle_grab_result(make_result("完全没见过的错误")) is True

    def test_412_counter_increments_and_resets(self, grabber):
        grabber._handle_grab_result(make_result("errno=412: slow down"))
        grabber._handle_grab_result(make_result("errno=412: slow down"))
        assert grabber._412_count == 2

        grabber._handle_grab_result(make_result("errno=100009: stock"))
        assert grabber._412_count == 0

    def test_412_alarm_after_max_count(self, grabber):
        grabber.max_412_count = 3
        for _ in range(3):
            grabber._handle_grab_result(make_result("errno=412: slow down"))
        assert grabber._412_count == 0  # 触发 300s 冷却后清零

    def test_429_increments_congestion(self, grabber):
        grabber._handle_grab_result(make_result("errno=429: too many"))
        grabber._handle_grab_result(make_result("errno=429: too many"))
        assert grabber._congestion_count == 2
        assert grabber._consecutive_congestion == 2

    def test_stock_error_resets_congestion(self, grabber):
        grabber._handle_grab_result(make_result("errno=100001: sold out"))
        assert grabber._consecutive_congestion == 1
        grabber._handle_grab_result(make_result("errno=100009: no stock"))
        assert grabber._consecutive_congestion == 0

    def test_price_update_caches_pay_money(self, grabber):
        result = make_result("errno=100034: price", raw={"data": {"pay_money": 12345}})
        assert grabber._handle_grab_result(result) is True
        assert grabber._cached_pay_money == 12345

    def test_fallback_string_matching_for_rate_limit(self, grabber):
        assert grabber._handle_grab_result(make_result("请求过于频繁")) is True
        assert grabber._412_count == 1

    def test_fallback_string_matching_for_limit(self, grabber):
        assert grabber._handle_grab_result(make_result("超出限购")) is False


class TestStockCheck:
    def test_has_stock(self, sample_config, make_stock_api, no_sleep):
        g = TicketGrabber(sample_config, api=make_stock_api(3))
        assert g.check_ticket_stock() is True
        assert g._raw_stock_status == 3

    def test_sold_out(self, sample_config, make_stock_api, no_sleep):
        g = TicketGrabber(sample_config, api=make_stock_api(2))
        assert g.check_ticket_stock() is False
        assert g._raw_stock_status == 2

    def test_network_error_returns_false(self, sample_config, fake_api, no_sleep, monkeypatch):
        def boom(url, **kwargs):
            raise RuntimeError("network down")

        fake_api.client.post = boom
        g = TicketGrabber(sample_config, api=fake_api)
        assert g.check_ticket_stock() is False


class TestCreateOrder:
    def test_passes_cached_id_bind(self, grabber, fake_api):
        grabber._project_id_bind = 1
        result = grabber._try_create_order()
        assert result.success is True
        assert fake_api.order_calls[0]["id_bind"] == 1

    def test_id_bind_none_when_not_cached(self, grabber, fake_api):
        grabber._try_create_order()
        assert fake_api.order_calls[0]["id_bind"] is None

    def test_passes_contact_info_to_api(self, sample_config, fake_api, no_sleep):
        """联系人信息必须一路传到下单请求，否则会返回 209001。"""
        viewers = [{"name": "张三", "tel": "13800000000"}]
        g = TicketGrabber(sample_config, viewers=viewers, api=fake_api)
        g._try_create_order()
        call = fake_api.order_calls[0]
        assert call["buyer_name"] == "张三"
        assert call["buyer_tel"] == "13800000000"

    def test_gaia_risk_failure_returns_unsuccessful(self, grabber, fake_api, monkeypatch):
        fake_api.order_result = {"errno": -352, "msg": "risk", "data": {}}
        monkeypatch.setattr(TicketGrabber, "_try_gaia_verify", lambda self, r: False)
        result = grabber._try_create_order()
        assert result.success is False
        assert "-352" in result.message

    def test_gaia_risk_success_asks_retry(self, grabber, fake_api, monkeypatch):
        fake_api.order_result = {"errno": -352, "msg": "risk", "data": {}}
        monkeypatch.setattr(TicketGrabber, "_try_gaia_verify", lambda self, r: True)
        result = grabber._try_create_order()
        assert result.success is False
        assert "gaia" in result.message

    def test_exception_is_captured(self, grabber, fake_api):
        def boom(**kwargs):
            raise ValueError("kaboom")

        fake_api.create_order = boom
        result = grabber._try_create_order()
        assert result.success is False
        assert "kaboom" in result.message


class TestGrabTicket:
    def test_stops_immediately_when_stop_event_set(self, grabber):
        grabber._stop_event.set()
        result = grabber.grab_ticket()
        assert result.success is False
        assert "已停止" in result.message
        assert result.attempts == 0

    def test_success_on_first_attempt(self, sample_config, make_fake_api,
                                      no_sleep, silent_notify):
        sample_config.strategy.enable_stock_check = False
        api = make_fake_api(order_result={
            "errno": 0, "msg": "", "data": {"orderId": "777", "token": ""},
        })
        g = TicketGrabber(sample_config, api=api)
        result = g.grab_ticket()
        assert result.success is True
        assert result.order_id == "777"
        assert result.attempts == 1
        assert g.phase is GrabPhase.SUCCESS

    def test_gives_up_on_fatal_error(self, sample_config, make_fake_api,
                                     no_sleep, silent_notify):
        sample_config.strategy.enable_stock_check = False
        api = make_fake_api(order_result={
            "errno": -403, "msg": "forbidden", "data": {},
        })
        g = TicketGrabber(sample_config, api=api)
        result = g.grab_ticket()
        assert result.success is False
        assert result.attempts == 1

    def test_stock_mode_skips_order_when_no_stock(self, sample_config,
                                                  make_stock_api, no_sleep):
        sample_config.strategy.enable_stock_check = True
        api = make_stock_api(2)
        g = TicketGrabber(sample_config, api=api)

        # 无票时循环会一直 continue，用 stop 事件在第一次检查后停止
        original_check = g.check_ticket_stock

        def check_and_stop():
            result = original_check()
            g._stop_event.set()
            return result

        g.check_ticket_stock = check_and_stop
        result = g.grab_ticket()
        assert result.success is False
        assert api.order_calls == []


class TestWaitForStart:
    def test_returns_immediately_when_already_on_sale(self, sample_config, fake_api, no_sleep):
        sample_config.strategy.advance_ms = 0
        sample_config.strategy.after_sale_begin_delay = 0
        g = TicketGrabber(sample_config, api=fake_api)
        start = time.monotonic()
        g.wait_for_start(int(time.time()) - 60)
        assert time.monotonic() - start < 2

    def test_advance_ms_shifts_start_earlier(self, sample_config, fake_api):
        """advance_ms 应该让程序提前开始，因此过去的时间点也应立刻返回。"""
        sample_config.strategy.advance_ms = 500
        sample_config.strategy.after_sale_begin_delay = 0
        g = TicketGrabber(sample_config, api=fake_api)
        start = time.monotonic()
        g.wait_for_start(int(time.time()) - 1)
        assert time.monotonic() - start < 2


class TestStop:
    def test_stop_sets_flag_and_phase(self, grabber):
        grabber.stop()
        assert grabber._stop_event.is_set()
        assert grabber.phase is GrabPhase.FAILED
