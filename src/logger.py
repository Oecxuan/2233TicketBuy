"""
日志模块
提供统一的日志记录功能，支持 rich 彩色输出
"""

import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.theme import Theme
from rich.logging import RichHandler
from rich.text import Text


RICH_THEME = Theme({
    "logging.level.info": "green",
    "logging.level.warning": "yellow",
    "logging.level.error": "red bold",
    "logging.level.debug": "dim",
    "time": "blue",
})


class MillisecondRichHandler(RichHandler):
    """时间戳精确到毫秒（蓝色）"""

    def get_time_text(self, record):
        dt = datetime.fromtimestamp(record.created)
        ts = dt.strftime('%H:%M:%S') + f'.{record.msecs:03d}'
        return Text(f"[{ts}]", style="time")


class Logger:
    def __init__(self, name: str = "2233TicketBuy", log_dir: str = "logs"):
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        self.console = Console(theme=RICH_THEME)
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            # 控制台 - Rich 彩色 + 蓝色毫秒时间
            ch = MillisecondRichHandler(
                console=self.console,
                show_time=True,
                show_level=True,
                show_path=False,
                rich_tracebacks=True,
            )
            ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(ch)

            # 文件 - 每次运行一个文件
            log_file = self.log_dir / f"{self.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            self.logger.addHandler(fh)

    def debug(self, msg): self.logger.debug(msg)
    def info(self, msg): self.logger.info(msg)
    def warning(self, msg): self.logger.warning(msg)
    def error(self, msg): self.logger.error(msg)

    def success(self, msg):
        self.logger.info(f"[green][OK][/green] {msg}")

    def fail(self, msg):
        self.logger.error(f"[red][FAIL][/red] {msg}")

    def hot(self, msg):
        ts = datetime.now().strftime('%H:%M:%S') + f'.{datetime.now().microsecond // 1000:03d}'
        self.console.print(f"[dim][{ts}][/dim] [bold yellow]🔥 {msg}[/bold yellow]")
        self.logger.debug(f"[HOT] {msg}")

    def time(self, msg):
        ts = datetime.now().strftime('%H:%M:%S') + f'.{datetime.now().microsecond // 1000:03d}'
        self.console.print(f"[dim][{ts}][/dim] [time]{msg}[/time]")


_logger_instance = None

def get_logger(name="2233"):
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name)
    return _logger_instance

logger = get_logger()
