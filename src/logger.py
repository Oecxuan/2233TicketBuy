"""
日志模块
提供统一的日志记录功能，支持 rich 彩色输出
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    def __init__(self, name: str = "2233TicketBuy", log_dir: str = "logs",
                 file_path: Optional[str] = None, level: str = "INFO",
                 save_to_file: bool = True):
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.console = Console(theme=RICH_THEME)
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self._file_handler = None
        self.log_file = None

        # 控制台 handler：同名 logger 只挂一次
        self._console_handler = None
        for handler in self.logger.handlers:
            if isinstance(handler, MillisecondRichHandler):
                self._console_handler = handler
                break

        if self._console_handler is None:
            # 控制台 - Rich 彩色 + 蓝色毫秒时间
            self._console_handler = MillisecondRichHandler(
                console=self.console,
                show_time=True,
                show_level=True,
                show_path=False,
                rich_tracebacks=True,
            )
            self._console_handler.setLevel(logging.INFO)
            self._console_handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(self._console_handler)

        self.configure(file_path=file_path, level=level,
                       save_to_file=save_to_file)

    def configure(self, file_path: Optional[str] = None,
                  level: Optional[str] = None,
                  save_to_file: bool = True) -> None:
        """
        按用户配置调整日志级别与文件输出，可重复调用。

        file_path 为相对路径时相对当前工作目录；
        未提供时沿用 logs/{name}_{时间戳}.log 的默认行为。
        """
        # 控制台级别
        if level:
            console_level = getattr(logging, str(level).upper(), logging.INFO)
            if not isinstance(console_level, int):
                console_level = logging.INFO
            self._console_handler.setLevel(console_level)

        # 先移除旧文件 handler，避免多次 configure 叠加
        if self._file_handler is not None:
            old_path = getattr(self._file_handler, "baseFilename", None)
            self.logger.removeHandler(self._file_handler)
            try:
                self._file_handler.close()
            except Exception:
                pass
            self._file_handler = None
            # 切换路径后清理掉上次留下的空日志（导入时建的那份）
            if old_path:
                try:
                    previous = Path(old_path)
                    if previous.exists() and previous.stat().st_size == 0:
                        previous.unlink()
                except Exception:
                    pass

        if not save_to_file:
            return

        if file_path:
            log_file = Path(file_path)
        else:
            log_file = self.log_dir / (
                f"{self.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding='utf-8')
        except Exception:
            return

        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.logger.addHandler(fh)
        self._file_handler = fh
        self.log_file = log_file

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


def configure_logging(file_path: Optional[str] = None,
                      level: Optional[str] = None,
                      save_to_file: bool = True) -> "Logger":
    """
    按 config.logging 初始化/更新全局 logger。

    在加载完配置后调用即可让 file_path / level / save_to_file 生效。
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(file_path=file_path, level=level,
                                  save_to_file=save_to_file)
    else:
        _logger_instance.configure(file_path=file_path, level=level,
                                   save_to_file=save_to_file)
    return _logger_instance


logger = get_logger()
