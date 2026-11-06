"""ctoken 生成算法的测试（纯本地逻辑，无网络）。"""
import base64

import pytest

from src.cptoken_vendor import (
    CTokenSnapshot,
    generate_browser_window_state,
    generate_ctoken,
    init_ctoken_state,
    sim_ctoken_state,
)

FIELDS = dict(
    m1=1, touchend=2, m2=3, visibilitychange=4, m3=5, m4=6,
    openWindow=7, m5=8, timer=9, timediff=1.5, m6=10, m7=11,
    m8=12, m9=13, beforeunload=14,
)

# 字节布局：14 个字段，其中 timer/timediff 各占 2 字节，每个字节后跟 \x00
EXPECTED_LEN = 32


class TestGenerateCtoken:
    def test_returns_valid_base64(self):
        token = generate_ctoken()
        assert isinstance(token, str)
        payload = base64.b64decode(token)
        assert len(payload) == EXPECTED_LEN

    def test_deterministic_for_same_input(self):
        assert generate_ctoken(**FIELDS) == generate_ctoken(**FIELDS)

    def test_byte_layout(self):
        payload = base64.b64decode(generate_ctoken(
            m1=65, touchend=66, m2=67, visibilitychange=68,
            m3=69, m4=70, openWindow=71, m5=72,
            timer=1000, timediff=1.5,
            m6=73, m7=74, m8=75, m9=76, beforeunload=77,
        ))
        assert len(payload) == EXPECTED_LEN

        # 奇数位全部是 \x00 分隔符
        for index in range(0, EXPECTED_LEN, 2):
            assert payload[index + 1] == 0, f"偏移 {index + 1} 不是分隔符"

        # 字段顺序：m1, touchend, m2, visibilitychange, m3, m4, beforeunload, m5
        assert payload[0] == 65
        assert payload[2] == 66
        assert payload[4] == 67
        assert payload[6] == 68
        assert payload[8] == 69
        assert payload[10] == 70
        assert payload[12] == 77
        assert payload[14] == 72

        # timer=1000 -> 0x03E8 ; timediff=1.5 -> 1
        assert payload[16] == 0x03 and payload[18] == 0xE8
        assert payload[20] == 0 and payload[22] == 1

    def test_out_of_range_value_clamps_to_ff(self):
        payload = base64.b64decode(generate_ctoken(**{**FIELDS, "m1": 300}))
        assert payload[0] == 0xFF

    def test_negative_value_clamps_to_ff(self):
        payload = base64.b64decode(generate_ctoken(**{**FIELDS, "m1": -5}))
        assert payload[0] == 0xFF

    def test_defaults_are_filled(self):
        # 不传可选字段时不应抛异常，且仍是合法长度
        token = generate_ctoken(ticket_collection_t=123)
        assert len(base64.b64decode(token)) == EXPECTED_LEN


class TestCTokenSnapshot:
    def _snapshot(self, **overrides):
        data = dict(
            m1=1, touchend=2, m2=3, visibilitychange=4, m3=5, m4=6,
            openWindow=7, m5=8, timer=9, timediff=1.5, m6=10, m7=11,
            m8=12, m9=13,
        )
        data.update(overrides)
        return CTokenSnapshot(**data)

    def test_kwargs_excludes_internal_fields(self):
        kwargs = self._snapshot().kwargs()
        assert "openWindow" in kwargs
        assert "beforeunload" in kwargs
        assert "ticket_collection_t" not in kwargs
        assert "base_timer" not in kwargs

    def test_prepare_and_create_ctoken_both_valid(self):
        snap = self._snapshot(beforeunload=77)
        prepare = base64.b64decode(snap.generate_prepare_ctoken())
        create = base64.b64decode(snap.generate_create_ctoken())
        assert len(prepare) == len(create) == EXPECTED_LEN

    def test_prepare_keeps_explicit_beforeunload(self):
        snap = self._snapshot(beforeunload=77)
        assert base64.b64decode(snap.generate_prepare_ctoken())[12] == 77

    def test_create_ignores_openwindow_and_beforeunload(self):
        """create 变体不传 openWindow/beforeunload，因此 beforeunload 是随机的。"""
        snap = self._snapshot(beforeunload=77)
        create_a = base64.b64decode(snap.generate_create_ctoken())
        create_b = base64.b64decode(snap.generate_create_ctoken())
        # 除 beforeunload 外其余字节一致
        for index in range(EXPECTED_LEN):
            if index == 12:
                continue
            assert create_a[index] == create_b[index]

    def test_generate_ctoken_alias(self):
        # beforeunload 显式给定，保证两次生成结果可比较
        snap = self._snapshot(beforeunload=14)
        assert snap.generate_ctoken() == snap.generate_prepare_ctoken()


class TestRuntimeState:
    T0 = 1_700_000_000_000

    def test_timer_and_timediff_grow_with_time(self):
        state = init_ctoken_state(ticket_collection_t=self.T0)
        s1 = state.snapshot(now_ms=self.T0 + 1_000)
        s2 = state.snapshot(now_ms=self.T0 + 5_000)
        assert s2.timer - s1.timer == 4
        assert s2.timediff - s1.timediff == pytest.approx(4.0)

    def test_snapshot_is_monotonic(self):
        state = init_ctoken_state(ticket_collection_t=self.T0)
        previous = state.snapshot(now_ms=self.T0)
        for delta in (100, 900, 3_000, 30_000):
            current = state.snapshot(now_ms=self.T0 + delta)
            assert current.timer >= previous.timer
            assert current.timediff >= previous.timediff
            previous = current

    def test_sim_ctoken_state_advances(self):
        state = init_ctoken_state(ticket_collection_t=self.T0)
        snap = sim_ctoken_state(state, now_ms=self.T0 + 3_000)
        assert snap.touchend >= state.touchend
        assert snap.openWindow >= state.openWindow
        assert snap.timer == state.base_timer + 3

    def test_sim_ctoken_state_produces_valid_token(self):
        state = init_ctoken_state(ticket_collection_t=self.T0)
        snap = sim_ctoken_state(state, now_ms=self.T0 + 1_000)
        assert len(base64.b64decode(snap.generate_create_ctoken())) == EXPECTED_LEN


class TestBrowserWindowState:
    def test_required_keys(self):
        ws = generate_browser_window_state()
        for key in (
            "scrollX", "scrollY", "innerWidth", "innerHeight",
            "outerWidth", "outerHeight", "screenX", "screenY",
            "screenWidth", "screenHeight", "screenAvailWidth",
            "screenAvailHeight",
        ):
            assert key in ws

    def test_non_maximized_constraints(self):
        ws = generate_browser_window_state(
            screen_width=1920, screen_height=1080,
            maximized=False, scroll=False,
        )
        assert ws["screenWidth"] == 1920
        assert ws["screenHeight"] == 1080
        assert 1016 <= ws["screenAvailHeight"] <= 1040
        assert 1152 <= ws["outerWidth"] <= 1728
        assert ws["innerWidth"] <= ws["outerWidth"]
        assert ws["innerHeight"] <= ws["outerHeight"]
        assert ws["scrollX"] == 0
        assert ws["scrollY"] == 0

    def test_maximized_constraints(self):
        ws = generate_browser_window_state(
            screen_width=1920, screen_height=1080, maximized=True,
        )
        assert ws["outerWidth"] == 1920
        assert ws["outerHeight"] == ws["screenAvailHeight"]
        assert ws["screenX"] == 0
        assert ws["screenY"] == 0
