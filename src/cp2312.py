"""
cp2312 签名算法实现
1:1 对齐 BHYG bilibili_util.py 2026-06-21
"""

import base64
import time
import random
from typing import Dict, Optional


class Cp2312Generator:
    """cp2312 token 生成器（对齐 BHYG BilibiliClient）"""

    def __init__(self):
        self.token_gen: Optional[float] = None

    @staticmethod
    def _get_env_data() -> list:
        """获取环境数据（完全对齐 BHYG）"""
        return [
            0,
            0,
            random.randint(1000, 2000),
            random.randint(800, 1200),
            random.randint(1600, 2400),
            random.randint(800, 1200),
            0,
            0,
            random.randint(1600, 2400),
            random.randint(800, 1200),
            random.randint(1600, 2400),
            random.randint(10, 50),
            random.randint(100, 200),
            random.randint(50, 100),
            20,
            int(time.time() * 1000) % 256,
        ]

    @staticmethod
    def _m(t: int, env_data: list) -> int:
        """BHYG 内部 m 函数"""
        idx1 = t % 16
        idx2 = (3 * t) % 16
        return (env_data[idx1] + env_data[idx2] + 17 * t) & 255

    def generate_ctoken(
        self,
        m1=-1, m2=-1, m3=-1, m4=-1, m5=-1, m6=-1, m7=-1, m8=-1, m9=-1,
        touchend=-1, visibilitychange=-1, beforeunload=-1, timer=-1,
        ticket_collection_t=0, openWindow=-1,
    ) -> str:
        """生成 ctoken（1:1 对齐 BHYG generate_ctoken）"""
        if touchend == -1:
            touchend = random.randint(30, 50)
        if visibilitychange == -1:
            visibilitychange = random.randint(10, 50)
        if beforeunload == -1:
            if openWindow != -1:
                beforeunload = openWindow
            else:
                beforeunload = random.randint(10, 50)
        if timer == -1:
            timer = random.randint(1, 10)
        env_data = self._get_env_data()
        if m1 == -1:
            m1 = self._m(1, env_data)
        if m2 == -1:
            m2 = self._m(2, env_data)
        if m3 == -1:
            m3 = self._m(3, env_data)
        if m4 == -1:
            m4 = self._m(4, env_data)
        if m5 == -1:
            m5 = self._m(5, env_data)
        if m6 == -1:
            m6 = self._m(6, env_data)
        if m7 == -1:
            m7 = self._m(7, env_data)
        if m8 == -1:
            m8 = self._m(8, env_data)
        if m9 == -1:
            m9 = self._m(9, env_data)
        token_bytes = b""
        data = {
            "m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5,
            "m6": m6, "m7": m7, "m8": m8, "m9": m9,
            "touchend": touchend, "visibilitychange": visibilitychange,
            "beforeunload": beforeunload, "timer": timer,
            "ticket_collection_t": ticket_collection_t,
        }
        token_bytes += data["m1"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        try:
            token_bytes += data["touchend"].to_bytes(1, byteorder='big')
        except OverflowError:
            token_bytes += b"\xff"
        token_bytes += b"\x00"
        token_bytes += data["m2"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        try:
            token_bytes += data["visibilitychange"].to_bytes(1, byteorder='big')
        except OverflowError:
            token_bytes += b"\xff"
        token_bytes += b"\x00"
        token_bytes += data["m3"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        token_bytes += data["m4"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        try:
            token_bytes += data["beforeunload"].to_bytes(1, byteorder='big')
        except OverflowError:
            token_bytes += b"\xff"
        token_bytes += b"\x00"
        token_bytes += data["m5"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        try:
            temp_timer = data["timer"].to_bytes(2, byteorder='big')
            token_bytes += temp_timer[0].to_bytes(1, byteorder='big')
            token_bytes += b"\x00"
            token_bytes += temp_timer[1].to_bytes(1, byteorder='big')
            token_bytes += b"\x00"
        except OverflowError:
            token_bytes += b"\xff\x00\xff\x00"
        try:
            temp_ticket_collection_t = int(data["ticket_collection_t"]).to_bytes(2, byteorder='big')
            token_bytes += temp_ticket_collection_t[0].to_bytes(1, byteorder='big')
            token_bytes += b"\x00"
            token_bytes += temp_ticket_collection_t[1].to_bytes(1, byteorder='big')
            token_bytes += b"\x00"
        except OverflowError:
            token_bytes += b"\xff\x00\xff\x00"
        token_bytes += data["m6"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        token_bytes += data["m7"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        token_bytes += data["m8"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        token_bytes += data["m9"].to_bytes(1, byteorder='big')
        token_bytes += b"\x00"
        return base64.b64encode(token_bytes).decode('utf-8')


# 兼容旧接口
_default_generator = Cp2312Generator()


def create_generator() -> Cp2312Generator:
    """创建 cp2312 生成器"""
    return Cp2312Generator()


def get_ctoken(project_id: int, screen_id: int, sku_id: int, count: int = 1) -> str:
    """快速获取 ctoken"""
    return _default_generator.generate_ctoken()


def get_token(project_id: int, screen_id: int, sku_id: int, count: int = 1) -> str:
    """快速获取 token"""
    return _default_generator.generate_ctoken()
