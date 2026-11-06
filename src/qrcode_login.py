"""
二维码登录模块
实现B站二维码登录流程
"""

import time
import httpx
import qrcode
import io
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class LoginResult:
    """登录结果"""
    success: bool
    sessdata: str = ""
    bili_jct: str = ""
    dede_user_id: str = ""
    dede_user_id_ckmd5: str = ""
    message: str = ""


# B站 cookie 名 -> LoginResult 字段名
_COOKIE_FIELDS = {
    "SESSDATA": "sessdata",
    "bili_jct": "bili_jct",
    "DedeUserID": "dede_user_id",
    "DedeUserID__ckMd5": "dede_user_id_ckmd5",
}


def extract_login_cookies(cookie_items) -> Dict[str, str]:
    """
    把 cookie 列表 [{name, value}, ...] 或字典 {name: value} 解析为登录字段。

    按 cookie 名字匹配而不是数组下标 —— B站不保证返回顺序，
    下标取值一旦顺序变化就会静默取错（例如把 bili_jct 当成 SESSDATA）。
    """
    if isinstance(cookie_items, dict):
        pairs = cookie_items
    else:
        pairs = {
            item.get("name", ""): item.get("value", "")
            for item in (cookie_items or [])
            if isinstance(item, dict)
        }

    return {
        field_name: pairs.get(cookie_name, "")
        for cookie_name, field_name in _COOKIE_FIELDS.items()
    }


class QRCodeLogin:
    """B站二维码登录"""
    
    QR_GET_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    
    STATUS_SUCCESS = 0
    STATUS_EXPIRED = 86038
    STATUS_SCANNED = 86090
    STATUS_NOT_SCANNED = 86101
    
    def __init__(self, timeout: int = 180):
        """
        初始化登录模块
        
        Args:
            timeout: 二维码有效期（秒）
        """
        self.timeout = timeout
        self.qrcode_key: Optional[str] = None
        self.qrcode_url: Optional[str] = None
        
    def get_qrcode_url(self) -> Tuple[str, str]:
        """获取二维码URL，返回 (url, qrcode_key)"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        
        with httpx.Client() as client:
            response = client.get(self.QR_GET_URL, headers=headers)
            data = response.json()
            
            if data["code"] != 0:
                raise Exception(f"获取二维码失败: {data['message']}")
            
            self.qrcode_url = data["data"]["url"]
            self.qrcode_key = data["data"]["qrcode_key"]
            
            return self.qrcode_url, self.qrcode_key
    
    def generate_qrcode_image(self, url: str) -> bytes:
        """
        生成二维码图片
        
        Args:
            url: 二维码内容
            
        Returns:
            PNG图片数据
        """
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 转换为PNG字节
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    
    def display_qrcode(self, url: str, show_window: bool = True) -> None:
        """显示二维码：终端 ASCII + 图片窗口弹出"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)

        if show_window:
            try:
                img = qr.make_image(fill_color="black", back_color="white")
                img = img.resize((img.width * 8, img.height * 8))
                img.show()
            except Exception:
                pass
    
    def poll_scan_status(self) -> Dict:
        """轮询扫码状态"""
        if not self.qrcode_key:
            raise Exception("请先获取二维码")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        
        params = {
            "qrcode_key": self.qrcode_key,
        }
        
        with httpx.Client(follow_redirects=True) as client:
            response = client.get(self.QR_POLL_URL, params=params, headers=headers)
            result = response.json()
            # 保存响应头，用于获取cookie
            result["_headers"] = dict(response.headers)
            result["_cookies"] = dict(response.cookies)
            return result
    
    def _build_login_result(self, data: Dict, raw_result: Dict):
        """
        从扫码成功响应中提取登录凭据。

        优先 cookie_info.cookies（按名字匹配），
        其次响应头 Set-Cookie（_cookies）。
        都拿不到时返回 None，由调用方决定如何提示。
        """
        cookie_info = data.get("cookie_info", {}) or {}
        cookies = cookie_info.get("cookies", []) or []
        if cookies:
            extracted = extract_login_cookies(cookies)
            if extracted.get("sessdata"):
                return LoginResult(success=True, message="登录成功", **extracted)

        header_cookies = raw_result.get("_cookies", {}) or {}
        if header_cookies:
            extracted = extract_login_cookies(header_cookies)
            if extracted.get("sessdata"):
                return LoginResult(success=True, message="登录成功", **extracted)

        return None

    def login(self, display_qrcode: bool = True) -> LoginResult:
        """执行登录流程"""
        try:
            # 获取二维码
            print("正在获取二维码...")
            url, key = self.get_qrcode_url()
            
            # 显示二维码
            if display_qrcode:
                print("\n请使用B站APP扫描以下二维码：\n")
                self.display_qrcode(url)
                print(f"\n二维码链接: {url}")
                print(f"\n二维码有效期: {self.timeout}秒")
                print("请尽快扫描...\n")
            
            # 轮询扫码状态
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                result = self.poll_scan_status()
                # 状态码在 data.code 中，不是顶层 code
                data = result.get("data", {})
                code = data.get("code", -1)
                
                if code == self.STATUS_SUCCESS:
                    login_result = self._build_login_result(data, result)
                    if login_result is not None:
                        return login_result
                    # 调试信息：便于定位 B站接口字段变化
                    print(f"[调试] 完整data: {data}")
                    return LoginResult(
                        success=False,
                        message="登录成功但未获取到cookie，请重试",
                    )
                elif code == self.STATUS_EXPIRED:
                    return LoginResult(success=False, message="二维码已过期，请重新获取")
                elif code == self.STATUS_SCANNED:
                    print("已扫码，请在手机上确认登录...")
                elif code == self.STATUS_NOT_SCANNED:
                    # 等待扫码
                    pass
                else:
                    return LoginResult(success=False, message=f"未知状态: {code}")
                
                # 等待1秒再轮询
                time.sleep(1)
            
            return LoginResult(success=False, message="登录超时")
            
        except Exception as e:
            return LoginResult(success=False, message=f"登录失败: {str(e)}")
    
    def login_with_browser(self) -> LoginResult:
        """
        使用浏览器打开二维码（可选）
        
        Returns:
            LoginResult对象
        """
        try:
            import webbrowser
            
            # 获取二维码URL
            url, key = self.get_qrcode_url()
            
            # 打开浏览器
            webbrowser.open(url)
            
            print("已在浏览器中打开二维码链接")
            print("请使用B站APP扫描浏览器中的二维码")
            
            # 轮询扫码状态
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                result = self.poll_scan_status()
                # 状态码在 data.code 中，不是顶层 code
                data = result.get("data", {})
                code = data.get("code", -1)
                
                if code == self.STATUS_SUCCESS:
                    login_result = self._build_login_result(data, result)
                    if login_result is not None:
                        return login_result
                    print(f"[调试] 完整data: {data}")
                    return LoginResult(
                        success=False,
                        message="登录成功但未获取到cookie",
                    )
                elif code == self.STATUS_EXPIRED:
                    return LoginResult(success=False, message="二维码已过期，请重新获取")
                elif code == self.STATUS_SCANNED:
                    print("已扫码，请在手机上确认登录...")
                
                time.sleep(1)
            
            return LoginResult(success=False, message="登录超时")
            
        except Exception as e:
            return LoginResult(success=False, message=f"登录失败: {str(e)}")


def login_interactive() -> LoginResult:
    """
    交互式登录
    
    Returns:
        LoginResult对象
    """
    loginer = QRCodeLogin()
    
    print("=" * 50)
    print("B站二维码登录")
    print("=" * 50)
    
    result = loginer.login(display_qrcode=True)
    
    if result.success:
        print("\n" + "=" * 50)
        print("登录成功！")
        print("=" * 50)
        print(f"SESSDATA: {result.sessdata[:20]}...")
        print(f"bili_jct: {result.bili_jct[:20]}...")
        print(f"DedeUserID: {result.dede_user_id}")
    else:
        print(f"\n登录失败: {result.message}")
    
    return result


if __name__ == "__main__":
    # 测试登录
    result = login_interactive()
