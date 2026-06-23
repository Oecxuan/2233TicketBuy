
"""
2233TicketBuy - B站 API 客户端
已验证可成功下单 hot 项目的方案：
1. curl_cffi Chrome146 指纹
2. 完整浏览器 cookie 套件（反爬关键）
3. prepare 传 ctoken → 获取 base64 ptoken
4. BTB cptoken 状态进化
"""
import json, time, random, hmac, hashlib, uuid
from typing import Dict, Optional, Any
from dataclasses import dataclass

import httpx
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL = True
except ImportError:
    HAS_CURL = False

try:
    from .cptoken_vendor import init_ctoken_state, generate_browser_window_state, sim_ctoken_state
    HAS_CPTOKEN = True
except ImportError:
    HAS_CPTOKEN = False

from .config import Config
from .logger import get_logger

logger = get_logger()

BASE_URL = "https://show.bilibili.com/api"
IMPORTANT = "chrome146"
COOKIE_DOMAIN = ".bilibili.com"

# ==================== 数据模型 ====================

@dataclass
class ProjectInfo:
    id: int
    name: str = ""
    id_bind: int = 0
    buyer_info: Any = None
    hot_project: bool = False
    screens: list = None
    sale_begin: int = 0
    start_time: int = 0
    status: str = ""
    cover: str = ""
    description: str = ""
    sale_flag_number: int = 0

    def __post_init__(self):
        if self.screens is None:
            self.screens = []


@dataclass
class ScreenInfo:
    """场次信息"""
    id: int
    name: str = ""
    start_time: str = ""
    end_time: str = ""
    skus: list = None

    def __post_init__(self):
        if self.skus is None:
            self.skus = []

# ==================== API 客户端 ====================

class BilibiliAPI:
    def __init__(self, config: Config):
        self.config = config
        self.device_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()

        # 构建完整 cookie 字典（认证 + 指纹）
        self.cookies = {
            "SESSDATA": config.user.sessdata,
            "bili_jct": config.user.bili_jct,
            "DedeUserID": config.user.dede_user_id,
            "DedeUserID__ckMd5": config.user.dede_user_id_ckmd5,
        }
        # 合并用户提供的额外 cookie（buvid3, buvid4, bili_ticket 等）
        self.cookies.update(config.user.cookies)
        # 强制所有 cookie 值转字符串（httpx/curl_cffi 要求 str）
        self.cookies = {k: str(v) if v is not None else "" for k, v in self.cookies.items()}

        # Token 缓存
        self._token = None
        self._ptoken = None
        self._token_exp = 0

        # BTB ctoken 状态
        self._ctoken_state = None
        if HAS_CPTOKEN:
            self._init_ctoken_state()

        # bili_ticket (如果用户没提供，自动生成)
        self._ensure_bili_ticket()
        # 自动补全浏览器指纹 cookie（从 B站 SPI 获取 buvid3）
        self._ensure_fingerprint_cookies()
        self._client = None

    # ==================== 初始化 ====================

    def _init_ctoken_state(self):
        try:
            ws = generate_browser_window_state()
            tct = int(time.time() * 1000)
            self._ctoken_state = init_ctoken_state(
                browser_window_state=ws,
                href_length=90,
                user_agent_length=138,
                ticket_collection_t=tct,
            )
            logger.debug("ctoken state 初始化成功")
        except Exception as e:
            logger.warning(f"ctoken state 失败: {e}")

    def _ensure_fingerprint_cookies(self):
        """从 B站 SPI 获取 buvid3/buvid4，其余指纹需用户自行提供"""
        # SPI 获取真实 buvid3/buvid4
        if not self.cookies.get("buvid3") or not self.cookies.get("buvid4"):
            try:
                if HAS_CURL:
                    r = curl_requests.get(
                        "https://api.bilibili.com/x/frontend/finger/spi",
                        headers={"User-Agent": "Mozilla/5.0"},
                        impersonate=IMPORTANT, timeout=10)
                else:
                    c = httpx.Client(http2=True, timeout=10, verify=False)
                    r = c.get("https://api.bilibili.com/x/frontend/finger/spi",
                              headers={"User-Agent": "Mozilla/5.0"})
                    c.close()
                data = r.json().get("data", {})
                if data.get("b_3") and not self.cookies.get("buvid3"):
                    self.cookies["buvid3"] = data["b_3"]
                if data.get("b_4") and not self.cookies.get("buvid4"):
                    self.cookies["buvid4"] = data["b_4"]
            except Exception:
                pass

    def _ensure_bili_ticket(self):
        if "bili_ticket" in self.cookies and self.cookies["bili_ticket"]:
            return
        try:
            now = int(time.time())
            hs = hmac.new(b"XgwSnGZ1p", f"ts{now}".encode(), hashlib.sha256).hexdigest()
            if HAS_CURL:
                r = curl_requests.post(
                    "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                    params={"key_id":"ec02","hexsign":hs,"context[ts]":str(now),"csrf":""},
                    headers={"User-Agent":"Mozilla/5.0"}, impersonate=IMPORTANT)
            else:
                c = httpx.Client(http2=True, timeout=10, verify=False)
                r = c.post("https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                    params={"key_id":"ec02","hexsign":hs,"context[ts]":str(now),"csrf":""},
                    headers={"User-Agent":"Mozilla/5.0"})
                c.close()
            self.cookies["bili_ticket"] = r.json()["data"]["ticket"]
            logger.debug("bili_ticket 已生成")
        except Exception as e:
            logger.warning(f"bili_ticket 生成失败: {e}")

    # ==================== Cookie 构建 ====================

    def _build_cookie_string(self) -> str:
        """构建完整的 cookie 字符串（反爬关键！）"""
        parts = []
        for k, v in self.cookies.items():
            if v:
                parts.append(f"{k}={v}")
        return "; ".join(parts)

    # ==================== HTTP 请求 ====================

    def _request(self, method: str, url: str, json_data: dict = None,
                 params: dict = None, referer: str = None) -> dict:
        """发送请求（完整 cookie + Chrome 指纹）"""
        cookie_str = self._build_cookie_string()
        headers = {
            "origin": "https://show.bilibili.com",
            "referer": referer or "https://show.bilibili.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        }
        if cookie_str:
            headers["cookie"] = cookie_str

        if HAS_CURL:
            try:
                resp = curl_requests.request(
                    method=method, url=url, params=params, json=json_data,
                    headers=headers, impersonate=IMPORTANT, timeout=15)
            except KeyboardInterrupt:
                raise
        else:
            client = httpx.Client(http2=True, timeout=15, verify=False)
            try:
                resp = client.request(method=method, url=url, params=params,
                                      json=json_data, headers=headers)
            except KeyboardInterrupt:
                raise
            finally:
                client.close()
        try:
            return resp.json()
        except Exception:
            logger.warning(f"_request 响应非JSON: {resp.status_code} {resp.text[:200]}")
            return {"errno": -1, "msg": f"HTTP {resp.status_code}", "data": {}}

    # ==================== 项目信息 ====================

    def get_project_info(self, project_id: int) -> ProjectInfo:
        result = self._request("GET", f"{BASE_URL}/ticket/project/get",
                               params={"id": project_id})
        data = result.get("data", {})
        return ProjectInfo(
            id=data.get("id", project_id),
            name=data.get("name", ""),
            id_bind=data.get("id_bind", 0),
            buyer_info=data.get("buyer_info", ""),
            hot_project=data.get("hotProject", False),
            screens=data.get("screen_list", []),
            sale_begin=data.get("sale_begin", 0),
            start_time=data.get("start_time", 0),
            status=data.get("status", ""),
            cover=data.get("cover", ""),
            description=data.get("description", ""),
            sale_flag_number=data.get("sale_flag_number", 0),
        )

    # ==================== 下单核心 ====================

    def prepare_token(self, project_id: int, screen_id: int,
                      sku_id: int, count: int) -> dict:
        """
        prepare_token - 必须传 ctoken 以获取 base64 格式 ptoken
        """
        ctoken = ""
        if HAS_CPTOKEN and self._ctoken_state:
            try:
                snap = self._ctoken_state.snapshot(now_ms=int(time.time() * 1000))
                ctoken = snap.generate_prepare_ctoken()
            except Exception:
                pass

        body = {
            "project_id": project_id, "screen_id": screen_id,
            "order_type": 1, "count": count, "sku_id": sku_id,
            "buyer_info": "", "ignoreRequestLimit": True,
            "ticket_agent": "", "newRisk": True,
            "requestSource": "neul-next", "token": ctoken,
        }

        for _ in range(10):  # 重试最多 10 次
            try:
                result = self._request("POST",
                    f"{BASE_URL}/ticket/order/prepare?project_id={project_id}",
                    json_data=body,
                    referer=f"https://show.bilibili.com/platform/detail.html?id={project_id}")
                errno = result.get("errno", -1)
                if errno == 0:
                    return result.get("data", {})
                if errno == -401:
                    time.sleep(1)
                    continue
                logger.warning(f"prepare 失败 (errno={errno}): {result.get('msg','')}")
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"prepare 异常: {e}")
                time.sleep(0.5)
        return {}

    def create_order(self, project_id: int, screen_id: int,
                     sku_id: int, count: int, pay_money: int = 0,
                     viewers: list = None,
                     buyer_name: str = "", buyer_tel: str = "",
                     viewer_id: int = None,
                     cached_token: str = "", cached_ptoken: str = "",
                     is_hot: bool = False,
                     cached_pay_money: int = 0) -> tuple:
        """
        创建订单 - 已验证可成功下单
        返回: (result_dict, token, ptoken)
        """
        # 获取项目信息
        try:
            project = self.get_project_info(project_id)
            id_bind = project.id_bind
        except Exception:
            id_bind = 0

        # prepare 获取 token/ptoken
        prep_data = self.prepare_token(project_id, screen_id, sku_id, count)
        if not prep_data:
            return {"errno": -1, "msg": "prepare 失败", "data": {}}, "", ""

        token = prep_data.get("token", "")
        ptoken = prep_data.get("ptoken", "")

        now_ms = int(time.time() * 1000)

        # 构建订单 body
        actual_pay = cached_pay_money or pay_money
        order_data = {
            "project_id": project_id, "screen_id": screen_id,
            "count": count, "pay_money": actual_pay,
            "order_type": 1, "timestamp": now_ms,
            "sku_id": sku_id, "token": token,
            "deviceId": self.device_id,
        }

        # buyer_info
        if id_bind >= 1 and viewers:
            buyer_list = [{
                "id": v.get("id"), "uid": v.get("uid", int(self.config.user.dede_user_id or 0)),
                "name": v.get("name", ""), "tel": v.get("tel_masked", v.get("tel", "")),
                "personal_id": v.get("personal_id", ""), "id_type": v.get("id_type", 0),
                "verify_status": v.get("verify_status", 1),
                "isBuyerInfoVerified": True, "isBuyerValid": True,
            } for v in viewers]
            order_data["buyer_info"] = json.dumps(buyer_list, ensure_ascii=False)
        elif id_bind >= 1 and not viewers:
            # 从 prepare 数据中获取观演人
            prep_buyers = prep_data.get("buyer_info", [])
            if prep_buyers:
                buyer_list = [{
                    "id": b.get("id"), "uid": b.get("uid", int(self.config.user.dede_user_id or 0)),
                    "name": b.get("name", ""), "tel": b.get("tel_masked", b.get("tel", "")),
                    "personal_id": b.get("personal_id", ""), "id_type": b.get("id_type", 0),
                    "verify_status": b.get("verify_status", 1),
                    "isBuyerInfoVerified": True, "isBuyerValid": True,
                } for b in prep_buyers]
                order_data["buyer_info"] = json.dumps(buyer_list, ensure_ascii=False)
            else:
                # fallback: 空数组
                order_data["buyer_info"] = "[]"
        else:
            order_data["buyer_info"] = "[]"

        # clickPosition
        origin = now_ms - random.randint(10000, 20000)
        order_data["clickPosition"] = json.dumps({
            "x": random.randint(100, 500), "y": random.randint(500, 900),
            "origin": origin, "now": now_ms,
        })
        order_data["requestSource"] = "pc-new"
        order_data["newRisk"] = True
        order_data["ptoken"] = ptoken

        # ctoken (hot 项目)
        if HAS_CPTOKEN and self._ctoken_state:
            try:
                create_snap = sim_ctoken_state(
                    before_state=self._ctoken_state, now_ms=now_ms)
                order_data["ctoken"] = create_snap.generate_create_ctoken()
            except Exception as e:
                logger.warning(f"create ctoken 生成失败: {e}")

        # 发送请求
        url = f"{BASE_URL}/ticket/order/createV2?project_id={project_id}&ptoken={ptoken}"
        try:
            result = self._request("POST", url, json_data=order_data,
                referer="https://show.bilibili.com/platform/confirmOrder.html")
        except Exception as e:
            return {"errno": -1, "msg": str(e), "data": {}}, token, ptoken

        errno = result.get("errno", -1)
        if errno == 0:
            logger.info(f"下单成功! orderId={result['data']['orderId']}")
        else:
            logger.warning(f"下单失败: errno={errno} msg={result.get('msg','')}")
        return result, token, ptoken

    # ==================== 辅助 ====================

    def check_login(self) -> bool:
        try:
            r = self._request("GET", "https://api.bilibili.com/x/web-interface/nav")
            return r.get("data", {}).get("isLogin", False)
        except Exception:
            return False

    def close(self):
        """清理资源"""
        if self._client:
            try: self._client.close()
            except: pass
            self._client = None
        # 清理 btb 日志文件/目录
        import os as _os, shutil as _shutil
        for _f in _os.listdir('.'):
            if _f.startswith('btb'):
                _fp = _os.path.join('.', _f)
                try:
                    if _os.path.isdir(_fp):
                        _shutil.rmtree(_fp, ignore_errors=True)
                    elif _f.endswith('.log') or _f.endswith('.txt'):
                        _os.remove(_fp)
                except: pass



    def _get_client(self):
        """获取 HTTP 客户端（兼容原版调用）"""
        if self._client is None:
            if HAS_CURL:
                self._client = curl_requests.Session(impersonate=IMPORTANT)
                self._client.headers.update({
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
                })
            else:
                import httpx
                self._client = httpx.Client(http2=True, timeout=15, verify=False,
                    headers={
                        "accept": "*/*", "accept-language": "zh-CN,zh;q=0.9",
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
                    })
        return self._client

    def _get_default_headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
            "Referer": "https://show.bilibili.com/",
            "Origin": "https://show.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def get_screen_info(self, project_id: int, screen_id: int) -> ScreenInfo:
        """获取场次信息"""
        project = self.get_project_info(project_id)
        for screen in project.screens:
            if screen.get("id") == screen_id:
                return ScreenInfo(
                    id=screen["id"],
                    name=screen.get("name", ""),
                    start_time=screen.get("start_time", ""),
                    end_time=screen.get("end_time", ""),
                    skus=screen.get("ticket_list", []),
                )
        raise Exception(f"未找到场次: {screen_id}")

    def get_sku_list(self, project_id: int, screen_id: int):
        """获取票档列表"""
        screen = self.get_screen_info(project_id, screen_id)
        return screen.skus

    def get_user_info(self) -> dict:
        """获取用户信息"""
        url = "https://api.bilibili.com/x/web-interface/nav"
        result = self._request("GET", url)
        return result.get("data", {})

    def get_server_time(self) -> float:
        """获取服务器时间"""
        try:
            if HAS_CURL:
                resp = curl_requests.head("https://show.bilibili.com", impersonate=IMPORTANT)
            else:
                import httpx
                c = httpx.Client(http2=True, timeout=5, verify=False)
                resp = c.head("https://show.bilibili.com")
                c.close()
            from email.utils import parsedate_to_datetime
            date_str = resp.headers.get("Date", "")
            if date_str:
                return parsedate_to_datetime(date_str).timestamp()
        except: pass
        return time.time()

    def save_session(self) -> None:
        pass

    def load_session(self) -> bool:
        return False

    def warmup_connection(self) -> None:
        pass

    def reset_client(self) -> None:
        self.close()

def create_api_client(config: Config) -> BilibiliAPI:
    return BilibiliAPI(config)
