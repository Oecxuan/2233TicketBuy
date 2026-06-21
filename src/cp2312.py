"""
cp2312 签名算法实现
对齐 biliTickerBuy 2026-06-21 cptoken 算法
"""

import base64
import struct
import time
import random
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class BrowserEnvironment:
    """浏览器环境参数"""
    scroll_x: int = 0
    scroll_y: int = 350
    inner_width: int = 1280
    inner_height: int = 720
    outer_width: int = 1280
    outer_height: int = 800
    screen_x: int = 0
    screen_y: int = 350
    screen_width: int = 1920
    screen_height: int = 1080
    screen_avail_width: int = 1920


class Cp2312Generator:
    """cp2312 token 生成器"""

    def __init__(self, env: Optional[BrowserEnvironment] = None):
        self.env = env or BrowserEnvironment()
        self.state: Optional[Dict[str, int]] = None
        self.token_gen: Optional[float] = None

    def derive_d(self, t: int, env_data: list) -> int:
        """模拟浏览器 d 函数"""
        idx1 = t % 16
        idx2 = (3 * t) % 16
        return (env_data[idx1] + env_data[idx2] + 17 * t) & 255

    def _get_env_data(self) -> list:
        """获取环境数据"""
        return [
            self.env.screen_width % 256,
            self.env.screen_height % 256,
            self.env.inner_width % 256,
            self.env.inner_height % 256,
            self.env.outer_width % 256,
            self.env.outer_height % 256,
            self.env.screen_x % 256,
            self.env.screen_y % 256,
            self.env.screen_avail_width % 256,
            self.env.scroll_x % 256,
            self.env.scroll_y % 256,
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
        ]

    def init_ctoken_state(self) -> None:
        """初始化 ctoken 状态"""
        env_data = self._get_env_data()
        self.state = {
            "m1": self.derive_d(1, env_data),
            "touchend": random.randint(30, 50),
            "m2": self.derive_d(2, env_data),
            "visibilitychange": random.randint(10, 50),
            "m3": self.derive_d(3, env_data),
            "m4": self.derive_d(4, env_data),
            "openWindow": random.randint(10, 50),
            "beforeunload": random.randint(10, 50),
            "m5": self.derive_d(5, env_data),
            "timer": random.randint(1, 10),
            "timediff": round(time.time() - int(time.time()), 3),
            "m6": self.derive_d(6, env_data),
            "m7": self.derive_d(7, env_data),
            "m8": self.derive_d(8, env_data),
            "m9": self.derive_d(9, env_data),
        }

    def update_state(self, ticket_time: int) -> None:
        """更新状态"""
        if self.state is None:
            self.init_ctoken_state()
            return
        env_data = self._get_env_data()
        for i, key in enumerate(["m1","m2","m3","m4","m5","m6","m7","m8","m9"], 1):
            self.state[key] = self.derive_d(i, env_data)
        self.state["beforeunload"] = self.state.get("openWindow", random.randint(10, 50))

    def generate_ctoken(self, state: Optional[Dict[str, int]] = None) -> str:
        """生成 ctoken（对齐 BTB 2026-06-21）"""
        if state is None:
            state = self.state
        if state is None:
            raise ValueError("请先初始化状态")

        m1 = state.get("m1", -1)
        touchend = state.get("touchend", -1)
        m2 = state.get("m2", -1)
        visibilitychange = state.get("visibilitychange", -1)
        m3 = state.get("m3", -1)
        m4 = state.get("m4", -1)
        openWindow = state.get("openWindow", -1)
        beforeunload = state.get("beforeunload", openWindow if openWindow != -1 else -1)
        m5 = state.get("m5", -1)
        timer = state.get("timer", -1)
        timediff = state.get("timediff", 0)
        m6 = state.get("m6", -1)
        m7 = state.get("m7", -1)
        m8 = state.get("m8", -1)
        m9 = state.get("m9", -1)

        if touchend == -1:
            touchend = random.randint(30, 50)
        if visibilitychange == -1:
            visibilitychange = random.randint(10, 50)
        if beforeunload == -1:
            beforeunload = random.randint(10, 50)
        if timer == -1:
            timer = random.randint(1, 10)

        def _b1(x: int) -> bytes:
            try:
                return int(x).to_bytes(1, "big")
            except OverflowError:
                return b"\xff"

        tb = (
            _b1(m1) + b"\x00"
            + _b1(touchend) + b"\x00"
            + _b1(m2) + b"\x00"
            + _b1(visibilitychange) + b"\x00"
            + _b1(m3) + b"\x00"
            + _b1(m4) + b"\x00"
            + _b1(beforeunload) + b"\x00"
            + _b1(m5) + b"\x00"
        )
        try:
            tt = int(timer).to_bytes(2, "big")
            tb += _b1(tt[0]) + b"\x00" + _b1(tt[1]) + b"\x00"
        except OverflowError:
            tb += b"\xff\x00\xff\x00"
        try:
            tc = int(float(timediff)).to_bytes(2, "big")
            tb += _b1(tc[0]) + b"\x00" + _b1(tc[1]) + b"\x00"
        except OverflowError:
            tb += b"\xff\x00\xff\x00"
        tb += (
            _b1(m6) + b"\x00"
            + _b1(m7) + b"\x00"
            + _b1(m8) + b"\x00"
            + _b1(m9) + b"\x00"
        )
        return base64.b64encode(tb).decode("utf-8")

    def generate_token(
        self, project_id: int, screen_id: int, order_type: int,
        count: int, sku_id: int, ts: Optional[int] = None,
    ) -> str:
        """生成 token"""
        if ts is None:
            ts = int(time.time())
        token_data = struct.pack(
            ">B4sIIBHI",
            0xC0, ts.to_bytes(4, "big"),
            project_id, screen_id, order_type, count, sku_id,
        )
        token = base64.b64encode(token_data).decode()
        token = token.replace("/", "_").replace("+", "-").replace("=", ".")
        return token

    def get_full_token(self, project_id: int, screen_id: int, sku_id: int, count: int = 1) -> Dict[str, str]:
        """获取完整 token"""
        if self.state is None:
            self.init_ctoken_state()
        ticket_time = int(time.time() * 1000) - random.randint(1000, 5000)
        self.update_state(ticket_time)
        ctoken = self.generate_ctoken()
        token = self.generate_token(
            project_id=project_id, screen_id=screen_id,
            order_type=1, count=count, sku_id=sku_id,
        )
        return {"ctoken": ctoken, "token": token}


def create_generator(
    screen_width: int = 362, screen_height: int = 795,
    inner_width: int = 362, inner_height: int = 747,
) -> Cp2312Generator:
    """创建 cp2312 生成器"""
    env = BrowserEnvironment(
        screen_width=screen_width, screen_height=screen_height,
        inner_width=inner_width, inner_height=inner_height,
        outer_width=inner_width, outer_height=inner_height + 80,
        screen_avail_width=screen_width,
    )
    return Cp2312Generator(env)


default_generator = create_generator()


def get_ctoken(project_id: int, screen_id: int, sku_id: int, count: int = 1) -> str:
    """快速获取 ctoken"""
    tokens = default_generator.get_full_token(project_id, screen_id, sku_id, count)
    return tokens["ctoken"]


def get_token(project_id: int, screen_id: int, sku_id: int, count: int = 1) -> str:
    """快速获取 token"""
    tokens = default_generator.get_full_token(project_id, screen_id, sku_id, count)
    return tokens["token"]
