# 2233TicketBuy

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Build](https://github.com/Oecxuan/2233TicketBuy/actions/workflows/build.yml/badge.svg)](https://github.com/Oecxuan/2233TicketBuy/actions)
[![Release](https://img.shields.io/github/v/release/Oecxuan/2233TicketBuy)](https://github.com/Oecxuan/2233TicketBuy/releases)

B站会员购抢票工具，仅供学习参考和研究使用。

本项目不开源任何账号信息，不上传任何数据。

> **免责声明：请遵守当地法律法规及B站相关规定，自行承担使用风险。严禁将本项目用于任何商业盈利行为。严禁进行任何形式的倒卖或违规行为。违反平台规则和法律所造成的一切后果由使用者自行承担，与本项目无关。**

## 感谢

- [biliTickerBuy](https://github.com/mikumifa/biliTickerBuy) 
- [BHYG](https://github.com/ZianTT/BHYG) 
- 本项目暂时没有找到能够自动完善所需cookies的办法，推荐使用上面两者。

## 功能

- 扫码登录（SESSDATA 持久化）
- 交互式选择活动 / 场次 / 票档 / 观演人
- 双服务器时间同步，开售前精确等待
- 蹲票模式：无票时监控库存，有票立即下单
- 智能降速：412/429 自适应间隔 + 拥堵阶梯变速
- 下单成功：Windows 弹窗+声音 / Linux 终端响铃 / 支付二维码

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置（复制示例文件并填入你的信息）
copy config_example.yaml config.yaml

# 3. 运行
python main.py
```

交互模式：登录 → 选活动 → 选票档 → 抢票。

也可直接 `python main.py --grab`（需已配置完成）。

> **注意**：Hot 项目需在 `config.yaml` 的 `user.cookies` 中填入浏览器指纹 cookie，格式如下：
> ```yaml
> user:
>   cookies:
>     buvid3: ""           # 必填
>     buvid4: ""           # 必填
>     buvid_fp: ""         # 必填
>     deviceFingerprint: ""# 必填
>     _uuid: ""            # 必填
>     b_nut: ""            # 必填
>     b_lsid: ""           # 必填
>     rpdid: ""            # 选填
>     LIVE_BUVID: ""       # 选填
>     PVID: ""             # 选填
>     kfcFrom: ""          # 选填
>     kfcSource: ""        # 选填
>     kfcTime: ""          # 选填
>     bp_t_offset_0: ""    # 选填（0 替换为你的 UID）
> ```
> 获取方式：浏览器登录 B站 → F12 → Application → Cookies → `show.bilibili.com`，复制对应值。一次配置长期有效。

## 命令行参数

| 参数 | 说明 |
|------|------|
| `python main.py` | 交互模式（推荐） |
| `python main.py --grab` | 直接抢票（需已配置） |
| `python main.py --login` | 仅登录 |
| `python main.py -c config.yaml` | 指定配置文件 |

## 下载

前往 [Releases](https://github.com/Oecxuan/2233TicketBuy/releases) 下载对应平台版本：

- `2233TicketBuy_v*_Windows.exe`
- `2233TicketBuy_v*_Linux`

## 构建

```bash
pip install -r requirements.txt pyinstaller
python -m PyInstaller --clean 2233TicketBuy.spec
```

## 测试

```bash
pip install -r requirements-dev.txt

python -m pytest              # 全部测试
python -m pytest -m smoke     # 仅入口冒烟测试
python -m pytest -v tests/test_config.py   # 单个文件
```

测试全部使用替身与 mock，**不会访问 B站接口**，也不会读写你的 `config.yaml`。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_config.py` | 配置读写往返、未知键容错、保存不丢字段、校验规则 |
| `tests/test_cptoken.py` | ctoken 字节布局、随机化边界、状态演化 |
| `tests/test_api_client.py` | cookie 装配、prepare/下单参数、错误响应处理 |
| `tests/test_ticket_grabber.py` | 错误码分派、库存检测、抢票主循环、开售等待 |
| `tests/test_qrcode_login.py` | 扫码状态机、cookie 按名字解析 |
| `tests/test_logger.py` | 日志落盘、级别切换、handler 不重复挂载 |
| `tests/test_main_helpers.py` | 票档状态描述、观演人选择与缓存 |
| `tests/test_smoke_cli.py` | `main.py --help` / `--create-example` 冒烟 |

## 已知限制

| 场景 | 现状 |
| --- | --- |
| **选座项目** | 不支持。`prepare` 返回 `80110000 座位信息为空`，程序会立即停止并提示改用 B站 App 手动选座 |
| **实体票收货地址** | 未实现 `deliver_info`。需要填写收货地址的项目可能下单失败 |
| 强实名项目 | 已支持（`prepare` 传观演人列表、`createV2` 传 JSON 字符串），但仅在无 hot 的真实活动上验证过 |
| gaia 极验 / `biliword` | 未实现，仅支持 `empty` 类型自动通过 |

## 许可证

MIT License

## 联系

- [提交 Issue](../../issues)
- 如本项目存在侵犯 Bilibili 公司合法权益的内容，请提交 Issue 联系删除。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Oecxuan/2233TicketBuy&type=Date)](https://star-history.com/#Oecxuan/2233TicketBuy&Date)
