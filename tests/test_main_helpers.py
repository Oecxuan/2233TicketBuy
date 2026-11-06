"""main.py 中纯逻辑辅助函数的测试。"""
import pytest

import main


class TestTicketStatusDesc:
    @pytest.mark.parametrize("flag,expected", [
        (1, "未开售"),
        (3, "已停售"),
        (4, "已售罄"),
        (5, "不可售"),
        (6, "库存紧张"),
        (8, "暂时售罄"),
        (9, "无购买资格"),
    ])
    def test_flag_mapping(self, flag, expected):
        assert main.get_ticket_status_desc({"sale_flag_number": flag}) == expected

    def test_unknown_flag(self):
        assert main.get_ticket_status_desc({"sale_flag_number": 99}) == "未知"

    def test_on_sale_shows_stock_count(self):
        sku = {"sale_flag_number": 2, "stock": {"count": 12}}
        assert main.get_ticket_status_desc(sku) == "余12"

    def test_on_sale_without_stock_info(self):
        assert main.get_ticket_status_desc({"sale_flag_number": 2}) == "售卖中"

    def test_on_sale_with_int_stock(self):
        assert main.get_ticket_status_desc(
            {"sale_flag_number": 2, "stock": 3}) == "余3"


class TestViewersCache:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = [{"id": 1, "name": "张三"}]
        main._save_viewers_cache(data)
        assert main._load_viewers_cache() == data

    def test_missing_cache_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert main._load_viewers_cache() == []

    def test_corrupted_cache_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / main.VIEWERS_CACHE_FILE).write_text("{not json", encoding="utf-8")
        assert main._load_viewers_cache() == []


class TestSelectViewers:
    def test_manual_id_returns_viewer_dict(self, monkeypatch):
        """回归测试：曾返回 [int]，下游 v.get('name') 会崩溃。"""
        monkeypatch.setattr(main, "get_viewers", lambda api: [])
        monkeypatch.setattr("builtins.input", lambda *_: "42")

        viewers = main.select_viewers(api=None, count=1)
        assert isinstance(viewers, list) and len(viewers) == 1
        assert isinstance(viewers[0], dict)
        assert viewers[0]["id"] == 42
        assert viewers[0]["name"] == ""

    def test_manual_id_invalid_returns_empty(self, monkeypatch):
        monkeypatch.setattr(main, "get_viewers", lambda api: [])
        monkeypatch.setattr("builtins.input", lambda *_: "abc")
        assert main.select_viewers(api=None, count=1) == []

    def test_empty_input_returns_empty(self, monkeypatch):
        monkeypatch.setattr(main, "get_viewers", lambda api: [])
        monkeypatch.setattr("builtins.input", lambda *_: "")
        assert main.select_viewers(api=None, count=1) == []

    def test_select_from_list(self, monkeypatch):
        monkeypatch.setattr(main, "get_viewers",
                            lambda api: [{"name": "A"}, {"name": "B"}])
        monkeypatch.setattr("builtins.input", lambda *_: "2")

        viewers = main.select_viewers(api=None, count=1)
        assert [v["name"] for v in viewers] == ["B"]

    def test_select_out_of_range_then_valid(self, monkeypatch):
        answers = iter(["9", "1"])
        monkeypatch.setattr(main, "get_viewers", lambda api: [{"name": "A"}])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        viewers = main.select_viewers(api=None, count=1)
        assert viewers[0]["name"] == "A"

    def test_multiple_viewers(self, monkeypatch):
        answers = iter(["1", "2"])
        monkeypatch.setattr(main, "get_viewers",
                            lambda api: [{"name": "A"}, {"name": "B"}])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))

        viewers = main.select_viewers(api=None, count=2)
        assert [v["name"] for v in viewers] == ["A", "B"]


class TestGetViewers:
    def test_success_saves_cache(self, tmp_path, monkeypatch, fake_api):
        monkeypatch.chdir(tmp_path)
        fake_api.client.get_payload = {
            "errno": 0,
            "data": {"list": [{"id": 1, "name": "张三"}]},
        }
        viewers = main.get_viewers(fake_api)
        assert viewers == [{"id": 1, "name": "张三"}]
        assert main._load_viewers_cache() == viewers

    def test_error_returns_empty(self, tmp_path, monkeypatch, fake_api):
        monkeypatch.chdir(tmp_path)
        fake_api.client.get_payload = {"errno": -1, "msg": "denied"}
        assert main.get_viewers(fake_api) == []

    def test_exception_returns_empty(self, tmp_path, monkeypatch, fake_api):
        monkeypatch.chdir(tmp_path)

        def boom(url, **kwargs):
            raise RuntimeError("network")

        fake_api.client.get = boom
        assert main.get_viewers(fake_api) == []
