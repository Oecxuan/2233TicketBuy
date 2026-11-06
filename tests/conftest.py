"""pytest 公共配置：路径注入与通用 fixture。"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# cptoken_vendor 用 loguru 打印状态，测试时静音避免污染输出
try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()
except Exception:  # pragma: no cover
    pass


@pytest.fixture
def tmp_config_path(tmp_path):
    """临时配置文件路径。"""
    return tmp_path / "config.yaml"


@pytest.fixture
def sample_config():
    """一套已填好必填项的内存配置。"""
    from src.config import Config

    cfg = Config()
    cfg.user.sessdata = "sess"
    cfg.user.bili_jct = "csrf"
    cfg.user.dede_user_id = "10086"
    cfg.event.project_id = 1001701
    cfg.event.screen_id = 2026
    cfg.event.sku_id = 303
    cfg.event.count = 1
    return cfg


@pytest.fixture
def no_network(monkeypatch):
    """禁止测试期间发起真实网络请求，避免拖慢/污染测试。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("network access disabled in tests")

    import src.api_client as api_client

    monkeypatch.setattr(api_client.curl_requests, "get", _boom, raising=False)
    monkeypatch.setattr(api_client.curl_requests, "post", _boom, raising=False)
    monkeypatch.setattr(api_client.curl_requests, "head", _boom, raising=False)
    monkeypatch.setattr(api_client.curl_requests, "request", _boom, raising=False)

    yield _boom


class FakeResponse:
    """最小化的 HTTP 响应替身。"""

    def __init__(self, payload, headers=None, status_code=200):
        self._payload = payload
        self.headers = headers or {}
        self.status_code = status_code
        self.text = str(payload)
        self.cookies = {}

    def json(self):
        return self._payload


class FakeClient:
    """最小化的 HTTP 客户端替身：记录调用并返回预置响应。"""

    def __init__(self, post_payload=None, get_payload=None, head_payload=None):
        self.post_payload = post_payload or {"code": 0, "data": {}}
        self.get_payload = get_payload or {"code": 0, "data": {}}
        self.head_payload = head_payload or {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse(self.post_payload)

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse(self.get_payload)

    def head(self, url, **kwargs):
        self.calls.append(("head", url, kwargs))
        return FakeResponse(self.head_payload, headers={"Date": "Wed, 21 Oct 2026 07:28:00 GMT"})

    def close(self):
        pass


@pytest.fixture
def fake_client():
    return FakeClient()


class FakeAPI:
    """
    BilibiliAPI 的测试替身。

    只实现 TicketGrabber / main 用到的接口，避免真实网络。
    """

    def __init__(self, stock_status=3, order_result=None, client=None):
        self.cookies = {"bili_jct": "csrf", "SESSDATA": "sess"}
        self.stock_status = stock_status
        self.order_result = order_result or {
            "errno": 0,
            "msg": "",
            "data": {"orderId": "9001", "token": ""},
        }
        self.client = client or FakeClient()
        self.order_calls = []
        self.stock_calls = 0
        self.server_time = time.time()

    # --- 供 check_ticket_stock 使用 ---
    def _get_client(self):
        return self.client

    def _get_default_headers(self):
        return {}

    # --- 供 grabber 使用 ---
    def get_project_info(self, project_id):
        from src.api_client import ProjectInfo

        return ProjectInfo(
            id=project_id,
            name="测试活动",
            id_bind=1,
            hot_project=False,
            screens=[],
            sale_begin=0,
        )

    def get_screen_info(self, project_id, screen_id):
        from src.api_client import ScreenInfo

        return ScreenInfo(id=screen_id, name="测试场次", skus=[
            {"id": 303, "desc": "测试票档", "price": 10000, "stock": {"count": 5}}
        ])

    def get_user_info(self):
        return {"vipStatus": 1}

    def check_login(self):
        return True

    def get_server_time(self):
        return self.server_time

    def create_order(self, **kwargs):
        self.order_calls.append(kwargs)
        if callable(self.order_result):
            return self.order_result(kwargs), "tok", "ptok"
        return self.order_result, "tok", "ptok"

    def close(self):
        pass


@pytest.fixture
def fake_api():
    return FakeAPI()


class StockClient(FakeClient):
    """按 stockStatus 返回库存接口响应的客户端。"""

    def __init__(self, stock_status):
        super().__init__()
        self.stock_status = stock_status

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse({"code": 0, "data": {"stockStatus": self.stock_status}})


@pytest.fixture
def make_fake_api():
    """构造带自定义行为的 BilibiliAPI 替身。"""

    def _make(**kwargs):
        return FakeAPI(**kwargs)

    return _make


@pytest.fixture
def make_stock_api():
    """构造库存接口返回指定 stockStatus 的替身。"""

    def _make(stock_status):
        return FakeAPI(client=StockClient(stock_status))

    return _make


@pytest.fixture
def no_sleep(monkeypatch):
    """跳过所有 sleep，让抢票循环测试瞬间完成。"""
    monkeypatch.setattr(time, "sleep", lambda *args, **kwargs: None)
