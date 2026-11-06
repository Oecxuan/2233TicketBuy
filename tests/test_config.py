"""配置读写与校验的测试。"""
import yaml
import pytest

from src.config import (
    Config,
    ConfigManager,
    _dataclass_from_dict,
    _deep_merge,
)


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


class TestDefaults:
    def test_default_values(self):
        cfg = Config()
        assert cfg.event.count == 1
        assert cfg.event.project_id == 0
        assert cfg.strategy.enable_stock_check is True
        assert cfg.strategy.order_interval == 0.3
        assert cfg.strategy.after_sale_begin_delay == 0.2
        assert cfg.strategy.delta == 0.05
        assert cfg.strategy.stock_check_available_delay == 0
        assert cfg.user.cookies == {}

    def test_default_factories_are_not_shared(self):
        a, b = Config(), Config()
        a.user.cookies["k"] = "v"
        a.event.viewers.append({"id": 1})
        assert b.user.cookies == {}
        assert b.event.viewers == []


class TestLoad:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConfigManager(str(tmp_path / "missing.yaml")).load()

    def test_empty_file_uses_defaults(self, tmp_config_path):
        tmp_config_path.write_text("", encoding="utf-8")
        cfg = ConfigManager(str(tmp_config_path)).load()
        assert cfg.event.project_id == 0
        assert cfg.strategy.enable_stock_check is True

    def test_load_values(self, tmp_config_path):
        write_yaml(tmp_config_path, {
            "user": {"sessdata": "abc", "dede_user_id": "42"},
            "event": {"project_id": 1001701, "count": 2},
            "strategy": {"order_interval": 0.9, "enable_stock_check": False},
        })
        cfg = ConfigManager(str(tmp_config_path)).load()
        assert cfg.user.sessdata == "abc"
        assert cfg.user.dede_user_id == "42"
        assert cfg.event.project_id == 1001701
        assert cfg.event.count == 2
        assert cfg.strategy.order_interval == 0.9
        assert cfg.strategy.enable_stock_check is False

    def test_unknown_keys_do_not_crash(self, tmp_config_path):
        """旧版本遗留键 / 用户手写多余键不应导致加载失败。"""
        write_yaml(tmp_config_path, {
            "user": {"sessdata": "abc", "some_legacy_key": 1},
            "event": {"project_id": 7, "unknown_nested": {"a": 1}},
            "strategy": {"typo_field": True},
            "brand_new_section": {"x": 1},
        })
        cfg = ConfigManager(str(tmp_config_path)).load()
        assert cfg.user.sessdata == "abc"
        assert cfg.event.project_id == 7

    def test_non_dict_section_falls_back_to_default(self, tmp_config_path):
        write_yaml(tmp_config_path, {"user": "not-a-dict"})
        cfg = ConfigManager(str(tmp_config_path)).load()
        assert cfg.user.sessdata == ""


class TestSave:
    def test_roundtrip_preserves_all_strategy_fields(self, tmp_config_path):
        """回归测试：save 曾遗漏 after_sale_begin_delay/order_interval/delta。"""
        mgr = ConfigManager(str(tmp_config_path))
        cfg = Config()
        cfg.strategy.after_sale_begin_delay = 1.25
        cfg.strategy.order_interval = 0.77
        cfg.strategy.delta = 0.11
        cfg.strategy.stock_check_available_delay = 0.5
        mgr.save(cfg)

        raw = yaml.safe_load(tmp_config_path.read_text(encoding="utf-8"))
        assert raw["strategy"]["after_sale_begin_delay"] == 1.25
        assert raw["strategy"]["order_interval"] == 0.77
        assert raw["strategy"]["delta"] == 0.11
        assert raw["strategy"]["stock_check_available_delay"] == 0.5

        reloaded = ConfigManager(str(tmp_config_path)).load()
        assert reloaded.strategy.after_sale_begin_delay == 1.25
        assert reloaded.strategy.order_interval == 0.77
        assert reloaded.strategy.delta == 0.11

    def test_save_keeps_user_cookies(self, tmp_config_path):
        """内存里 cookies 为空时，不应抹掉用户手填的指纹 cookie。"""
        write_yaml(tmp_config_path, {
            "user": {"cookies": {"buvid3": "B3", "buvid4": "B4"}},
        })
        cfg = ConfigManager(str(tmp_config_path)).load()
        # 模拟用户手动清空内存 cookies（例如从默认配置另存）
        cfg.user.cookies = {}
        ConfigManager(str(tmp_config_path)).save(cfg)

        raw = yaml.safe_load(tmp_config_path.read_text(encoding="utf-8"))
        assert raw["user"]["cookies"]["buvid3"] == "B3"
        assert raw["user"]["cookies"]["buvid4"] == "B4"

    def test_save_updates_known_cookies(self, tmp_config_path):
        write_yaml(tmp_config_path, {"user": {"cookies": {"buvid3": "OLD"}}})
        cfg = ConfigManager(str(tmp_config_path)).load()
        cfg.user.cookies["buvid3"] = "NEW"
        ConfigManager(str(tmp_config_path)).save(cfg)

        raw = yaml.safe_load(tmp_config_path.read_text(encoding="utf-8"))
        assert raw["user"]["cookies"]["buvid3"] == "NEW"

    def test_save_preserves_unknown_sections(self, tmp_config_path):
        write_yaml(tmp_config_path, {
            "user": {"sessdata": "old"},
            "my_custom_section": {"keep": "me"},
        })
        cfg = ConfigManager(str(tmp_config_path)).load()
        cfg.user.sessdata = "new"
        ConfigManager(str(tmp_config_path)).save(cfg)

        raw = yaml.safe_load(tmp_config_path.read_text(encoding="utf-8"))
        assert raw["my_custom_section"] == {"keep": "me"}
        assert raw["user"]["sessdata"] == "new"

    def test_save_creates_parent_directory(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "config.yaml"
        ConfigManager(str(target)).save(Config())
        assert target.exists()

    def test_save_without_config_raises(self, tmp_path):
        with pytest.raises(ValueError):
            ConfigManager(str(tmp_path / "c.yaml")).save()

    def test_save_is_idempotent(self, tmp_config_path):
        mgr = ConfigManager(str(tmp_config_path))
        cfg = Config()
        mgr.save(cfg)
        first = tmp_config_path.read_text(encoding="utf-8")
        ConfigManager(str(tmp_config_path)).save(ConfigManager(str(tmp_config_path)).load())
        second = tmp_config_path.read_text(encoding="utf-8")
        assert first == second


class TestValidate:
    def test_default_config_reports_missing_fields(self):
        errors = ConfigManager("unused.yaml").validate(Config())
        joined = " ".join(errors)
        assert "sessdata" in joined
        assert "bili_jct" in joined
        assert "dede_user_id" in joined
        assert "project_id" in joined
        assert "screen_id" in joined
        assert "sku_id" in joined

    def test_valid_config_has_no_errors(self, sample_config):
        assert ConfigManager("unused.yaml").validate(sample_config) == []

    def test_invalid_numbers(self, sample_config):
        sample_config.event.count = 0
        sample_config.strategy.concurrency = 0
        sample_config.strategy.retry_count = -1
        errors = ConfigManager("unused.yaml").validate(sample_config)
        assert any("购票数量" in e for e in errors)
        assert any("并发数" in e for e in errors)
        assert any("重试次数" in e for e in errors)

    def test_validate_none_config(self):
        assert ConfigManager("unused.yaml").validate(None) == ["配置未加载"]


class TestHelpers:
    def test_dataclass_from_dict_ignores_unknown(self):
        from src.config import EventConfig

        obj = _dataclass_from_dict(EventConfig, {"project_id": 5, "nope": 1})
        assert obj.project_id == 5

    def test_dataclass_from_dict_handles_non_dict(self):
        from src.config import EventConfig

        assert _dataclass_from_dict(EventConfig, None).project_id == 0

    def test_deep_merge_keeps_nested_keys(self):
        merged = _deep_merge(
            {"a": {"x": 1, "y": 2}, "b": 1},
            {"a": {"y": 3}},
        )
        assert merged == {"a": {"x": 1, "y": 3}, "b": 1}

    def test_deep_merge_empty_dict_does_not_wipe(self):
        merged = _deep_merge({"cookies": {"k": "v"}}, {"cookies": {}})
        assert merged["cookies"] == {"k": "v"}


class TestCreateExampleConfig:
    def test_example_contains_every_strategy_field(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "config.yaml"))
        mgr.create_example_config()

        example = tmp_path / "config.yaml.example"
        assert example.exists()
        raw = yaml.safe_load(example.read_text(encoding="utf-8"))
        for key in (
            "retry_count",
            "retry_delay_ms",
            "concurrency",
            "advance_ms",
            "timeout_seconds",
            "after_sale_begin_delay",
            "order_interval",
            "delta",
            "enable_stock_check",
            "stock_check_available_delay",
        ):
            assert key in raw["strategy"], f"示例配置缺少字段: {key}"
