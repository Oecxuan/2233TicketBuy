"""
B站API客户端
参考biliTickerBuy和BHYG的API设计
"""

import httpx
import json
import time
import random
import hashlib
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .cp2312 import Cp2312Generator, create_generator
from .config import Config
from .wbi import WbiSigner, get_wbi_signer, fetch_wbi_keys
from .error_recovery import safe_request, ErrorRecovery, get_error_recovery, NetworkError, APIError
from .logger import logger


@dataclass
class ProjectInfo:
    """项目信息"""
    id: int
    name: str
    start_time: int
    sale_begin: int
    screens: List[Dict]
    status: str
    cover: str = ""
    description: str = ""
    buyer_info: str = ""
    id_bind: int = 0
    hot_project: bool = False
    sale_flag_number: int = 0


@dataclass
class ScreenInfo:
    """场次信息"""
    id: int
    name: str
    start_time: str
    end_time: str
    skus: List[Dict]


class BilibiliAPI:
    """
    B站API客户端
    
    参考BHYG的API设计
    """
    
    # API 基础 URL
    BASE_URL = "https://show.bilibili.com/api"
    
    # 请求头模板（对齐 BHYG mobile headers）
    def _get_default_headers(self) -> Dict:
        """获取默认请求头（对齐 BHYG：仅 UA）"""
        return {
            "User-Agent": self._chrome_ua,
        }
    
    def __init__(self, config: Config, cp2312_generator: Optional[Cp2312Generator] = None):
        """
        初始化API客户端
        
        Args:
            config: 配置对象
            cp2312_generator: cp2312生成器
        """
        self.config = config
        self.cp2312 = cp2312_generator or create_generator()
        self.wbi_signer = get_wbi_signer()
        self.error_recovery = get_error_recovery()
        self._client = None  # 必须在 _init_fingerprint 之前
        
        # 生成设备ID
        # 持久化设备ID（对齐 BHYG：devicefp 从 session 加载）
        self.device_id = config.user.device_id if config.user.device_id else hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
        if not config.user.device_id:
            config.user.device_id = self.device_id
            from .config import save_config
            try:
                save_config(config)
            except Exception:
                pass
        
        # ========== 设备指纹系统（对标 BHYG） ==========
        self._model_list = {
            "OnePlus": ["PKR110","PJD110","PJZ110","PKU110","PJA110","PJF110","PJX110"],
            "IQOO": ["V2329A", "V2408A", "V2307A", "V2304A", "V2254A"],
            "HONOR": ["DVD-AN00", "PTP-AN20", "ROD2-W69", "ROD2-W09", "ROL-W00"],
            "Vivo": ["V2324A", "V2229A", "V2241A", "V2359A", "V2454A", "V2364A", "V2429A", "V2343A", "V2435A"],
            "Realme": ["RMX5060", "RMX3946", "RMX3948", "RMX5010"],
            "OPPO": ["PFFM20", "PJJ110", "PJW110", "PKM110", "PHU110"],
        }
        # 对标 BHYG：指纹值在 session 创建前初始化
        self.screen_info = "362*795*24"
        self.canvas_fp = "".join(random.choices("0123456789abcdef", k=32))
        self.webgl_fp = "".join(random.choices("0123456789abcdef", k=32))
        self.fe_sign = "".join(random.choices("0123456789abcdef", k=32))
        
        self._init_fingerprint()
        # Token 缓存（对齐 BHYG get_token 逻辑）
        self._token = None
        self._ptoken = None
        self._token_exp = 0  # 过期时间戳
        self._cached_id_bind: Optional[int] = None
        self._cached_buyer_info: str = ""
        # 构建Cookie（对齐 BHYG show.bilibili.com 专属 cookie）
        self.cookies = {
            "SESSDATA": config.user.sessdata,
            "bili_jct": config.user.bili_jct,
            "DedeUserID": config.user.dede_user_id,
            "DedeUserID__ckMd5": config.user.dede_user_id_ckmd5,
            # BHYG 风格：show.bilibili.com 专属 cookie
            "deviceFingerprint": self.device_id,
            # 设备指纹 cookie
            "buvid3": self.buvid3,
            "buvid4": self.buvid4,
            "buvid_fp": self.buvid_fp,
            "_uuid": self._uuid,
        }
        
        # 持久 HTTP Session（对齐 BHYG）
        self._client = None
        
        
        # load persisted session (BHYG style)
        self.load_session()
        # 代理配置
        self.proxy = None
        if config.proxy.enabled:
            if config.proxy.socks5:
                self.proxy = config.proxy.socks5
            elif config.proxy.https:
                self.proxy = config.proxy.https
            elif config.proxy.http:
                self.proxy = config.proxy.http
        
        # 初始化WBI密钥
        self._init_wbi_keys()
    
    def _init_wbi_keys(self) -> None:
        """初始化WBI密钥 + bili_ticket（对标 BHYG _getKeys）"""
        if not self.wbi_signer.is_initialized():
            logger.info("正在获取WBI密钥...")
            if fetch_wbi_keys(self.cookies):
                logger.info("WBI密钥获取成功")
            else:
                logger.warning("WBI密钥获取失败，部分功能可能不可用")
        
        # 对标 BHYG：通过 GenWebTicket API 获取 bili_ticket（风控通行证）
        self._fetch_bili_ticket()
    
    def _fetch_bili_ticket(self) -> None:
        """对标 BHYG _getKeys：调用 GenWebTicket API 获取 bili_ticket cookie"""
        import hmac as _hmac_mod
        try:
            ts = int(time.time())
            # HMAC-SHA256 签名
            o = _hmac_mod.new(
                b"XgwSnGZ1p",
                f"ts{ts}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            csrf = self.cookies.get("bili_jct", "")
            params = {
                "key_id": "ec02",
                "hexsign": o,
                "context[ts]": ts,
                "csrf": csrf,
            }
            client = self._get_client()
            resp = client.post(
                "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                params=params,
            )
            data = resp.json()
            if data.get("code") == 0 and "data" in data:
                nd = data["data"]
                bili_ticket = nd.get("ticket", "")
                bili_ticket_expires = nd.get("created_at", 0) + nd.get("ttl", 0)
                self.cookies["bili_ticket"] = bili_ticket
                self.cookies["bili_ticket_expires"] = str(bili_ticket_expires)
                if self._client is not None:
                    self._client.cookies.update({
                        "bili_ticket": bili_ticket,
                        "bili_ticket_expires": str(bili_ticket_expires),
                    })
                logger.debug(f"bili_ticket 获取成功")
            else:
                logger.warning(f"bili_ticket 获取失败: {data}")
        except Exception as e:
            logger.warning(f"bili_ticket 获取异常: {e}")
    
    # ==================== 设备指纹系统 ====================

    @staticmethod
    def _gen_hex(n: int) -> str:
        """生成随机 hex 字符串"""
        return "".join(random.choices("0123456789abcdef", k=n))

    def _gen_ua(self) -> str:
        """生成桌面 Chrome UA，对齐 BTB 策略（Web 端模拟）。"""
        chrome_major = random.choice([124, 125, 126, 127, 128, 129, 130, 131])
        chrome_ver = f"{chrome_major}.0.{random.randint(6000, 6900)}.{random.randint(80, 180)}"
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_ver} Safari/537.36"
        )
import time
import random
import hashlib
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .cp2312 import Cp2312Generator, create_generator
from .config import Config
from .wbi import WbiSigner, get_wbi_signer, fetch_wbi_keys
from .error_recovery import safe_request, ErrorRecovery, get_error_recovery, NetworkError, APIError
from .logger import logger


@dataclass
class ProjectInfo:
    """项目信息"""
    id: int
    name: str
    start_time: int
    sale_begin: int
    screens: List[Dict]
    status: str
    cover: str = ""
    description: str = ""
    buyer_info: str = ""
    id_bind: int = 0
    hot_project: bool = False
    sale_flag_number: int = 0


@dataclass
class ScreenInfo:
    """场次信息"""
    id: int
    name: str
    start_time: str
    end_time: str
    skus: List[Dict]


class BilibiliAPI:
    """
    B站API客户端
    
    参考BHYG的API设计
    """
    
    # API 基础 URL
    BASE_URL = "https://show.bilibili.com/api"
    
    # 请求头模板（对齐 BHYG mobile headers）
    def _get_default_headers(self) -> Dict:
        """获取默认请求头（对齐 BHYG：仅 UA）"""
        return {
            "User-Agent": self._chrome_ua,
        }
    
    def __init__(self, config: Config, cp2312_generator: Optional[Cp2312Generator] = None):
        """
        初始化API客户端
        
        Args:
            config: 配置对象
            cp2312_generator: cp2312生成器
        """
        self.config = config
        self.cp2312 = cp2312_generator or create_generator()
        self.wbi_signer = get_wbi_signer()
        self.error_recovery = get_error_recovery()
        self._client = None  # 必须在 _init_fingerprint 之前
        
        # 生成设备ID
        # 持久化设备ID（对齐 BHYG：devicefp 从 session 加载）
        self.device_id = config.user.device_id if config.user.device_id else hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
        if not config.user.device_id:
            config.user.device_id = self.device_id
            from .config import save_config
            try:
                save_config(config)
            except Exception:
                pass
        
        # ========== 设备指纹系统（对标 BHYG） ==========
        self._model_list = {
            "OnePlus": ["PKR110","PJD110","PJZ110","PKU110","PJA110","PJF110","PJX110"],
            "IQOO": ["V2329A", "V2408A", "V2307A", "V2304A", "V2254A"],
            "HONOR": ["DVD-AN00", "PTP-AN20", "ROD2-W69", "ROD2-W09", "ROL-W00"],
            "Vivo": ["V2324A", "V2229A", "V2241A", "V2359A", "V2454A", "V2364A", "V2429A", "V2343A", "V2435A"],
            "Realme": ["RMX5060", "RMX3946", "RMX3948", "RMX5010"],
            "OPPO": ["PFFM20", "PJJ110", "PJW110", "PKM110", "PHU110"],
        }
        # 对标 BHYG：指纹值在 session 创建前初始化
        self.screen_info = "362*795*24"
        self.canvas_fp = "".join(random.choices("0123456789abcdef", k=32))
        self.webgl_fp = "".join(random.choices("0123456789abcdef", k=32))
        self.fe_sign = "".join(random.choices("0123456789abcdef", k=32))
        
        self._init_fingerprint()
        # Token 缓存（对齐 BHYG get_token 逻辑）
        self._token = None
        self._ptoken = None
        self._token_exp = 0  # 过期时间戳
        self._cached_id_bind: Optional[int] = None
        self._cached_buyer_info: str = ""
        # 构建Cookie（对齐 BHYG show.bilibili.com 专属 cookie）
        self.cookies = {
            "SESSDATA": config.user.sessdata,
            "bili_jct": config.user.bili_jct,
            "DedeUserID": config.user.dede_user_id,
            "DedeUserID__ckMd5": config.user.dede_user_id_ckmd5,
            # BHYG 风格：show.bilibili.com 专属 cookie
            "deviceFingerprint": self.device_id,
            # 设备指纹 cookie
            "buvid3": self.buvid3,
            "buvid4": self.buvid4,
            "buvid_fp": self.buvid_fp,
            "_uuid": self._uuid,
        }
        
        # 持久 HTTP Session（对齐 BHYG）
        self._client = None
        
        # 代理配置
        self.proxy = None
        if config.proxy.enabled:
            if config.proxy.socks5:
                self.proxy = config.proxy.socks5
            elif config.proxy.https:
                self.proxy = config.proxy.https
            elif config.proxy.http:
                self.proxy = config.proxy.http
        
        # 初始化WBI密钥
        self._init_wbi_keys()
    
    def _init_wbi_keys(self) -> None:
        """初始化WBI密钥 + bili_ticket（对标 BHYG _getKeys）"""
        if not self.wbi_signer.is_initialized():
            logger.info("正在获取WBI密钥...")
            if fetch_wbi_keys(self.cookies):
                logger.info("WBI密钥获取成功")
            else:
                logger.warning("WBI密钥获取失败，部分功能可能不可用")
        
        # 对标 BHYG：通过 GenWebTicket API 获取 bili_ticket（风控通行证）
        self._fetch_bili_ticket()
    
    def _fetch_bili_ticket(self) -> None:
        """对标 BHYG _getKeys：调用 GenWebTicket API 获取 bili_ticket cookie"""
        import hmac as _hmac_mod
        try:
            ts = int(time.time())
            # HMAC-SHA256 签名
            o = _hmac_mod.new(
                b"XgwSnGZ1p",
                f"ts{ts}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            csrf = self.cookies.get("bili_jct", "")
            params = {
                "key_id": "ec02",
                "hexsign": o,
                "context[ts]": ts,
                "csrf": csrf,
            }
            client = self._get_client()
            resp = client.post(
                "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                params=params,
            )
            data = resp.json()
            if data.get("code") == 0 and "data" in data:
                nd = data["data"]
                bili_ticket = nd.get("ticket", "")
                bili_ticket_expires = nd.get("created_at", 0) + nd.get("ttl", 0)
                self.cookies["bili_ticket"] = bili_ticket
                self.cookies["bili_ticket_expires"] = str(bili_ticket_expires)
                if self._client is not None:
                    self._client.cookies.update({
                        "bili_ticket": bili_ticket,
                        "bili_ticket_expires": str(bili_ticket_expires),
                    })
                logger.debug(f"bili_ticket 获取成功")
            else:
                logger.warning(f"bili_ticket 获取失败: {data}")
        except Exception as e:
            logger.warning(f"bili_ticket 获取异常: {e}")
    
    # ==================== 设备指纹系统 ====================

    @staticmethod
    def _gen_hex(n: int) -> str:
        """生成随机 hex 字符串"""
        return "".join(random.choices("0123456789abcdef", k=n))

    def _gen_ua(self) -> str:
        """生成桌面 Chrome UA，对齐 BTB 策略（Web 端模拟）。"""
        chrome_major = random.choice([124, 125, 126, 127, 128, 129, 130, 131])
        chrome_ver = f"{chrome_major}.0.{random.randint(6000, 6900)}.{random.randint(80, 180)}"
        return (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_ver} Safari/537.36"
        )
    @staticmethod
    def _gen_buvid3() -> str:
        """生成 buvid3（B站设备标识）"""
        import uuid as _uuid
        parts = [
            _uuid.uuid4().hex[:8].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:12].upper() + str(random.randint(10000, 99999)) + "infoc",
        ]
        return "-".join(parts)

    @staticmethod
    def _gen_buvid4() -> str:
        """生成 buvid4"""
        import uuid as _uuid
        parts = [
            _uuid.uuid4().hex[:16].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:4].upper(),
            _uuid.uuid4().hex[:12].upper() + str(random.randint(10000, 99999)),
        ]
        return "-".join(parts)

    @staticmethod
    def _gen_uuid_infoc() -> str:
        """生成 _uuid（infoc 格式）"""
        import uuid as _uuid
        hex_str = _uuid.uuid4().hex.upper()
        return (
            f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}"
            f"-{hex_str[16:20]}-{hex_str[20:32]}{random.randint(10000, 99999)}infoc"
        )

    def _init_fingerprint(self) -> None:
        """初始化设备指纹体系"""
        self._chrome_ua = self._gen_ua()  # 桌面 Chrome UA
        self._fetch_buvid_from_spi()
        self._uuid = self._gen_uuid_infoc()

        # 会话级静态指纹（对齐 BHYG：init 时生成一次，会话内不变）
        self._refresh_fingerprints()

    def _fetch_buvid_from_spi(self) -> None:
        """从 B站 SPi 指纹服务获取真实 buvid3/4（对齐 BHYG），失败时本地生成"""
        import hashlib

        # 本地计算 buvid_fp（含校验码，对齐 BHYG）
        random_md5 = hashlib.md5(str(random.random()).encode()).hexdigest()
        fp_raw = random_md5 + time.strftime("%Y%m%d%H%M%S", time.localtime()) + self._gen_hex(16)
        fp_sub = [fp_raw[i:i+2] for i in range(0, len(fp_raw), 2)]
        veri = 0
        for i in range(0, len(fp_sub), 2):
            veri += int(fp_sub[i], 16)
        self.buvid_fp = f"{fp_raw}{hex(veri % 256)[2:]}"

        try:
            client = self._get_client()
            resp = client.get(
                "https://api.bilibili.com/x/frontend/finger/spi",
            )
            data = resp.json()
            if data.get("code") == 0:
                self.buvid3 = data["data"].get("b_3", "")
                self.buvid4 = data["data"].get("b_4", "")
                logger.debug(f"SPi buvid 获取成功")
                return
        except Exception as e:
            logger.debug(f"SPi 获取失败，回退本地生成: {e}")

        # Fallback: 本地生成
        self.buvid3 = self._gen_buvid3()
        self.buvid4 = self._gen_buvid4()

    def _refresh_fingerprints(self) -> None:
        """生成会话级静态指纹（init 时调用一次，不在每次请求时刷新）"""
        self.canvas_fp = self._gen_hex(32)
        self.webgl_fp = self._gen_hex(32)
        self.fe_sign = self._gen_hex(32)
        self.screen_info = f"{362}*{795}*{24}"

    # ==================== 持久 HTTP Session ====================

    def _get_client(self) -> httpx.Client:
        """获取持久 HTTP 客户端（对齐 BHYG session）"""
        if self._client is None:
            self._client = httpx.Client(
                headers={
                # BTB 风格：桌面 Chrome 浏览器 headers
                "User-Agent": self._chrome_ua,
                "accept": "*/*",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
                "connection": "keep-alive",
                "origin": "https://show.bilibili.com",
                "priority": "u=1, i",
                "referer": "https://show.bilibili.com/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not/A)Brand";v="8"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
                timeout=10,
                http2=True,
                verify=False,
                event_hooks={
                    "request": [self._on_request],
                },
            )
            # 对标 BHYG：不在构造时传 cookies，通过 session.cookies.update() 管理
            _cookies = getattr(self, 'cookies', None)
            if _cookies:
                self._client.cookies.update(_cookies)
        return self._client
    def _on_request(self, request: httpx.Request) -> None:
        """请求前 hook：BTB 风格——不注入 Android 指纹 cookie。"""
        # DEBUG
        logger.debug(f"REQ HEADERS: {dict(request.headers)}")
        logger.debug(f"REQ COOKIES ({len(self._client.cookies)}): {dict(self._client.cookies)}")
    
    def _build_identify(self) -> str:
        """构建 identify cookie（对齐 BHYG _app_sign）"""
        from urllib.parse import quote, urlencode
        import hashlib
        params = {"ts": int(time.time() * 1000)}
        params["appkey"] = "1d8b6e7d45233436"
        # sorted keys for deterministic output
        query = urlencode(dict(sorted(params.items())))
        sign = hashlib.md5((query + "560c52ccd288fed045859ed18bffd973").encode()).hexdigest()
        params["sign"] = sign
        return quote(urlencode(params))

    # ========== Session 持久化（对齐 BHYG session 恢复） ==========
    
    @property
    def _session_file(self) -> str:
        """Session 持久化文件路径"""
        import os
        uid = self.config.user.dede_user_id or "unknown"
        session_dir = os.path.join(os.path.expanduser("~"), ".2233TicketBuy")
        os.makedirs(session_dir, exist_ok=True)
        return os.path.join(session_dir, f"session_{uid}.json")
    
    def save_session(self) -> None:
        """保存当前 session 的全部 cookie 到文件（对齐 BHYG save）"""
        if self._client is None:
            return
        try:
            import json
            cookies = {}
            for cookie in self._client.cookies.jar:
                cookies[cookie.name] = cookie.value
            with open(self._session_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False)
            logger.debug(f"Session 已保存: {len(cookies)} 个 cookie -> {self._session_file}")
        except Exception as e:
            logger.warning(f"保存 session 失败: {e}")
    
    def load_session(self) -> bool:
        """从文件加载 session cookie（对齐 BHYG load）"""
        import json, os
        if not os.path.exists(self._session_file):
            return False
        try:
            with open(self._session_file, "r", encoding="utf-8") as f:
                saved_cookies = json.load(f)
            if saved_cookies:
                # 确保 client 已创建
                client = self._get_client()
                client.cookies.update(saved_cookies)
                logger.info(f"Session 已恢复: {len(saved_cookies)} 个 cookie 来自 {self._session_file}")
                return True
        except Exception as e:
            logger.warning(f"加载 session 失败: {e}")
        return False
    
    def close(self) -> None:
        """关闭持久 session"""
        if self._client is not None:
            self.save_session()  # 持久化 session
            self._client.close()
            self._client = None

    def reset_client(self) -> None:
        """重置 HTTP 客户端（连接池+SSL+HTTP/2 stream 全部重建，用于清除服务端限流状态）"""
        self.close()
        self._get_client()  # 立即重建
        logger.info("HTTP 客户端已重建（重置连接池与 SSL 会话）")
    
    
    def warmup_connection(self) -> None:
        """预热 HTTP/2 连接（对齐 BHYG rush_mode 中的 session.head）"""
        try:
            client = self._get_client()
            client.head("https://show.bilibili.com", timeout=5)
            logger.debug("HTTP/2 连接预热完成")
        except Exception as e:
            logger.debug(f"连接预热失败（非关键）: {e}")

    def _get_headers(
        self,
        method: str,
        url: str,
        data: Optional[str] = None,
        extra_headers: Optional[Dict] = None,
    ) -> Dict:
        """构建请求头，BTB 风格：桌面浏览器 headers。"""
        headers = {
            "User-Agent": self._chrome_ua,
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
            "origin": "https://show.bilibili.com",
            "referer": "https://show.bilibili.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not/A)Brand";v="8"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers
    
    def _check_response(self, result: Dict) -> None:
        """检查响应状态（支持 errno 和 code 两种格式）"""
        # 检查errno格式（会员购API）
        errno = result.get("errno", None)
        if errno is not None:
            if errno != 0:
                msg = result.get("msg", "未知错误")
                logger.warning(f"API错误 errno={errno}: {msg}, 响应: {str(result)[:500]}")
                raise APIError(code=errno, message=msg)
            return
        
        # 检查code格式（通用API）
        code = result.get("code", None)
        if code is not None:
            if code != 0:
                message = result.get("message", result.get("msg", "未知错误"))
                raise APIError(code=code, message=message)
            return
        
        # 如果都没有找到，检查是否有data字段
        if "data" not in result:
            raise APIError(code=-1, message="响应格式异常")
    
    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        extra_headers: Optional[Dict] = None,
        use_wbi: bool = False,
    ) -> Dict:
        """发送 HTTP 请求"""
        # WBI签名
        if use_wbi and params:
            params = self.wbi_signer.sign(params.copy())
        
        # 准备请求体数据
        body_data = None
        if json_data:
            body_data = json.dumps(json_data)
        elif data:
            body_data = "&".join([f"{k}={v}" for k, v in data.items()])
        
        # 构建请求头
        headers = self._get_headers(method, url, body_data, extra_headers)
        
        try:
            client = self._get_client()
            response = client.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=headers,
            )
            
            # 调试日志：每次请求的方法/URL/状态码
            logger.debug(f"{method} {url} → {response.status_code}")
            if response.status_code >= 400:
                logger.debug(f"  响应头: {dict(response.headers)}")
            
            # 检查Content-Type
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                # 打印调试信息
                logger.debug(f"请求URL: {method} {url}")
                logger.debug(f"响应状态码: {response.status_code}")
                logger.debug(f"响应Content-Type: {content_type}")
                logger.debug(f"响应内容前200字符: {response.text[:200]}")
                raise Exception(f"API返回非JSON响应，Content-Type: {content_type}")
            
            result = response.json()
            
            # 检查响应状态
            self._check_response(result)
            
            return result
                
        except APIError:
            raise
        except httpx.TimeoutException:
            raise NetworkError("请求超时")
        except httpx.NetworkError as e:
            raise NetworkError(f"网络错误: {e}")
        except Exception as e:
            raise NetworkError(f"请求错误: {e}")
    
    def get_project_info(self, project_id: int) -> ProjectInfo:
        """
        获取项目信息
        
        使用正确的API端点: /api/ticket/project/get
        """
        url = f"{self.BASE_URL}/ticket/project/get"
        params = {"id": project_id}
        
        result = self._request("GET", url, params=params)
        data = result["data"]
        
        screens = data.get("screen_list", [])
        
        return ProjectInfo(
            id=data["id"],
            name=data["name"],
            start_time=data.get("start_time", 0),
            sale_begin=data.get("sale_begin", 0),
            screens=screens,
            status=data.get("status", ""),
            cover=data.get("cover", ""),
            description=data.get("description", ""),
            buyer_info=data.get("buyer_info", ""),
            id_bind=data.get("id_bind", 0),
            hot_project=data.get("hotProject", False),
            sale_flag_number=data.get("sale_flag_number", 0),
        )
    
    def get_screen_info(self, project_id: int, screen_id: int) -> ScreenInfo:
        """获取场次信息"""
        project = self.get_project_info(project_id)
        
        for screen in project.screens:
            if screen["id"] == screen_id:
                return ScreenInfo(
                    id=screen["id"],
                    name=screen.get("name", ""),
                    start_time=screen.get("start_time", ""),
                    end_time=screen.get("end_time", ""),
                    skus=screen.get("ticket_list", []),
                )
        
        raise Exception(f"未找到场次: {screen_id}")
    
    def get_sku_list(self, project_id: int, screen_id: int) -> List[Dict]:
        """获取票档列表"""
        screen = self.get_screen_info(project_id, screen_id)
        return screen.skus
    
    def prepare_token(self, project_id: int, screen_id: int, sku_id: int, count: int,
                      buyer_info=None, id_bind: int = 0, viewers: list = None, is_hot: bool = False) -> Dict:
        """准备 token（严格对齐 BHYG prepare_token）"""
        url = f"{self.BASE_URL}/ticket/order/prepare?project_id={project_id}"
        buyer_info_data = buyer_info if buyer_info else ""
        logger.debug(f"prepare_token: buyer_info={repr(buyer_info_data)}, is_hot={is_hot}")

        # BHYG: while True 内构建 data + seed + ctoken，每次重试都全新
        while True:
            random.seed(int(time.time() * 1000))
            data = {
                "project_id": project_id,
                "screen_id": screen_id,
                "order_type": 1,
                "count": count,
                "sku_id": sku_id,
                "buyer_info": buyer_info_data,
                "ignoreRequestLimit": True,
                "ticket_agent": "",
                "newRisk": True,
                "requestSource": "neul-next",
            }
            if is_hot:
                data["token"] = self.cp2312.generate_ctoken(
                    touchend=random.randint(1, 5),
                    beforeunload=random.randint(1, 3),
                    openWindow=random.randint(1, 3),
                )
            
            try:
                client = self._get_client()
                response = client.post(url, json=data)
                # BHYG post 方法：归一化响应为 {"code": ..., "message": ..., "data": ...}
                if response.status_code == 200:
                    resp_json = response.json()
                    result = {
                        "code": resp_json.get("code", resp_json.get("errno")),
                        "message": resp_json.get("message", resp_json.get("msg", "")),
                        "data": resp_json.get("data", {}),
                    }
                else:
                    result = {"code": response.status_code, "message": "", "data": {}}
            except Exception as e:
                logger.warning(f"prepare_token 请求异常: {e}")
                time.sleep(1)
                continue

            code = result["code"]
            if code == 0:
                resp_data = result.get("data", {})
                return resp_data
            elif code == -401:
                logger.warning("prepare_token 触发 gaia 风控，等待重试")
                time.sleep(1)
                continue
            else:
                logger.warning(f"prepare_token 失败 (code={code}): {result.get('message', result.get('msg', ''))}")
                time.sleep(1)

    def _get_token(self, project_id: int, screen_id: int, sku_id: int, count: int,
                   buyer_info=None, id_bind: int = 0, viewers: list = None, is_hot: bool = False):
        """获取 token（对齐 BHYG：hot 项目不缓存，每次都全新 prepare）"""
        # BHYG: get_token 中的 hasattr 检查永远为 False（self.token 从未被设置）
        # 因此 BHYG 每次都调用 prepare_token()，token 从不缓存
        # 热项目的 ptoken 可能是一次性的，复用会导致 100001
        if not is_hot and self._token and self._ptoken and time.time() < self._token_exp - 60:
            return self._token, self._ptoken
        
        prepare_data = self.prepare_token(project_id, screen_id, sku_id, count,
                                          buyer_info=buyer_info, id_bind=id_bind,
                                          viewers=viewers, is_hot=is_hot)
        self._token = prepare_data.get("token", "") or ""
        self._ptoken = prepare_data.get("ptoken", "") or ""
        self._token_exp = time.time() + 300
        self.cp2312.token_gen = time.time()
        return self._token, self._ptoken
    
    def create_order(
        self,
        project_id: int,
        screen_id: int,
        sku_id: int,
        count: int,
        buyer_name: str = "",
        buyer_tel: str = "",
        viewer_id: Optional[int] = None,
        viewers: list = None,
        cached_token: str = "",
        cached_ptoken: str = "",
        is_hot: bool = False,
        cached_pay_money: int = 0,
    ) -> tuple:
        """创建订单（严格对齐 BHYG do_order_create）"""
        url = f"{self.BASE_URL}/ticket/order/createV2?project_id={project_id}"
        
        # BHYG: 首次获取 id_bind 后缓存，不在下单循环中重复请求 API
        if self._cached_id_bind is None:
            project = self.get_project_info(project_id)
            self._cached_id_bind = project.id_bind
            self._cached_buyer_info = project.buyer_info or ""
        id_bind = self._cached_id_bind
        buyer_info_str = self._cached_buyer_info
        logger.debug(f"create_order: id_bind={id_bind}, buyer_info_str={repr(buyer_info_str)}")
        
        # 获取 token（BHYG 风格：过期重新 prepare，每次全新 ctoken）
        token, ptoken = self._get_token(
            project_id, screen_id, sku_id, count,
            buyer_info=buyer_info_str, id_bind=id_bind,
            viewers=viewers, is_hot=is_hot,
        )
        
        ptoken_clean = ptoken.replace("=", "") if ptoken else ""
        
        # 获取价格（优先使用缓存价格）
        pay_money = cached_pay_money if cached_pay_money else 0
        if not pay_money:
            project = self.get_project_info(project_id)
            for screen in project.screens:
                if screen["id"] == screen_id:
                    for sku in screen.get("ticket_list", []):
                        if sku["id"] == sku_id:
                            pay_money = sku.get("price", 0)
                            break
        
        now_ms = int(time.time() * 1000)
        
        # 严格对齐 BHYG do_order_create 字段名、类型、顺序
        order_data = {
            "project_id": project_id,
            "screen_id": screen_id,
            "count": count,
            "pay_money": pay_money,
            "order_type": 1,
            "timestamp": now_ms,
            "id_bind": id_bind,
            "need_contact": 1 if id_bind == 0 else 0,
            "is_package": 0,
            "package_num": 1,
            "contactInfo": {
                "uid": int(self.config.user.dede_user_id) if self.config.user.dede_user_id else 0,
                "username": buyer_name if id_bind == 0 else None,
                "tel": buyer_tel if id_bind == 0 else None,
            } if id_bind == 0 else None,
            "sku_id": sku_id,
            "coupon_code": "",
            "again": 1,
            "token": token,
            "deviceId": self.device_id,
            "version": "1.1.0",
        }
        
        # BHYG: buyer_info / buyer+tel 根据 id_bind 决定
        if id_bind == 1 or id_bind == 2:
            if viewers:
                order_data["buyer_info"] = json.dumps([{
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "tel": v.get("tel"),
                    "personal_id": v.get("personal_id"),
                    "id_type": v.get("id_type", 0),
                } for v in viewers])
        else:
            order_data["buyer"] = buyer_name
            order_data["tel"] = buyer_tel
        
        # BHYG: clickPosition（origin 优先用 token_gen）
        origin = (
            int(self.cp2312.token_gen * 1000)
            if self.cp2312.token_gen
            else now_ms - random.randint(10000, 20000)
        )
        order_data["clickPosition"] = {
            "x": random.randint(200, 400),
            "y": random.randint(750, 800),
            "origin": origin,
            "now": now_ms,
        }
        
        # BHYG: hot 项目 ctoken + ptoken + orderCreateUrl（先于 requestSource/newRisk）
        if is_hot:
            ctoken = ""
            try:
                token_gen = self.cp2312.token_gen or time.time()
                ctoken = self.cp2312.generate_ctoken(
                    timer=10 + 2 * int(time.time()) - 2 * int(token_gen),
                )
            except Exception:
                pass
            if ctoken:
                order_data["ctoken"] = ctoken
            order_data["ptoken"] = ptoken_clean
            order_data["orderCreateUrl"] = (
                "https://show.bilibili.com/api/ticket/order/createV2"
            )
        
        # BHYG: requestSource + newRisk 在最后
        order_data["requestSource"] = "neul-next"
        order_data["newRisk"] = True
        
        # BHYG 风格：直接 post，不传 explicit headers（session 自带 UA）
        request_url = url
        if is_hot:
            request_url = f"{url}&ptoken={ptoken_clean}"
        
        # DEBUG: 打印发送的 order_data 关键字段
        logger.debug(f"create_order POST: url={request_url}")
        logger.debug(f"  token={token[:30]}..., ptoken_clean={ptoken_clean[:30]}...")
        logger.debug(f"  ctoken={order_data.get('ctoken', 'N/A')[:30]}...")
        logger.debug(f"  orderCreateUrl={order_data.get('orderCreateUrl', 'N/A')}")
        logger.debug(f"  is_hot={is_hot}, id_bind={id_bind}")
        
        # DEBUG: 打印完整 HTTP 请求
        import copy
        safe_order = copy.deepcopy(order_data)
        for k in ('buyer_info', 'contactInfo', 'buyer', 'tel'):
            if k in safe_order:
                safe_order[k] = '***REDACTED***'
        import json as _json
        logger.debug(f"RAW POST BODY: {_json.dumps(safe_order, ensure_ascii=False)[:2000]}")
        logger.debug(f"RAW POST URL: {request_url}")
        logger.debug(f"Session cookies count: {len(self._get_client().cookies)}")
        
        try:
            client = self._get_client()
            response = client.post(request_url, json=order_data)
            logger.debug(f"RAW RESPONSE headers: {dict(response.headers)}")
            logger.debug(f"RAW RESPONSE status: {response.status_code}")
            # BHYG post 方法：归一化响应
            if response.status_code == 200:
                resp_json = response.json()
                result = {
                    "code": resp_json.get("code", resp_json.get("errno")),
                    "message": resp_json.get("message", resp_json.get("msg", "")),
                    "data": resp_json.get("data", {}),
                }
            else:
                result = {"code": response.status_code, "message": "", "data": {}}
        except json.JSONDecodeError:
            mapped = {429: 429, 412: 412}.get(getattr(response, 'status_code', 0), -1)
            return {"errno": mapped, "msg": f"HTTP {getattr(response, 'status_code', '?')}", "data": {}}, token, ptoken_clean
        except httpx.TimeoutException:
            return {"errno": -1, "msg": "请求超时", "data": {}}, token, ptoken_clean
        except httpx.NetworkError as e:
            return {"errno": -1, "msg": str(e), "data": {}}, token, ptoken_clean
        except Exception as e:
            return {"errno": -1, "msg": str(e), "data": {}}, token, ptoken_clean
        
        code = result["code"]
        msg = result["message"]
        
        return {"errno": code, "msg": msg, "data": result.get("data", {})}, token, ptoken_clean

    def get_order_info(self, order_id: str) -> Dict:
        """获取订单信息"""
        url = f"{self.BASE_URL}/ticket/order/info"
        params = {"order_id": order_id}
        return self._request("GET", url, params=params)
    
    def create_pay(self, order_id: str) -> Dict:
        """创建支付"""
        url = f"{self.BASE_URL}/ticket/order/createPay"
        data = {"order_id": order_id}
        return self._request("POST", url, json_data=data)
    
    def check_login(self) -> bool:
        """检查登录状态"""
        try:
            url = "https://api.bilibili.com/x/web-interface/nav"
            client = self._get_client()
            response = client.get(
                url,
                headers=self._get_default_headers(),
            )
            result = response.json()
            return result.get("code") == 0
        except:
            return False
    
    def get_user_info(self) -> Dict:
        """获取用户信息"""
        url = "https://api.bilibili.com/x/web-interface/nav"
        result = self._request("GET", url)
        return result["data"]

    def get_server_time(self) -> float:
        """获取 show.bilibili.com 服务器时间（通过 HTTP Date 头，用于精确同步）"""
        try:
            client = self._get_client()
            resp = client.head("https://show.bilibili.com")
            date_str = resp.headers.get("Date", "")
            if date_str:
                from email.utils import parsedate_to_datetime
                server_dt = parsedate_to_datetime(date_str)
                ts = server_dt.timestamp()
                offset = ts - time.time()
                logger.debug(f"服务器时间(Date头): {date_str}, 本地偏移: {offset:+.2f}s")
                return ts
        except Exception as e:
            logger.debug(f"获取服务器时间失败: {e}")
        return time.time()


def create_api_client(config: Config) -> BilibiliAPI:
    """创建API客户端"""
    return BilibiliAPI(config)
