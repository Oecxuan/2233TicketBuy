import sys, logging, os, datetime

# 确保 logs 目录存在
os.makedirs("logs", exist_ok=True)

BLUE = '\x1b[34m'
RESET = '\x1b[0m'

class ColoredFormatter(logging.Formatter):
    COLORS = {'DEBUG':'\x1b[36m','INFO':'\x1b[32m','WARNING':'\x1b[33m','ERROR':'\x1b[31m','CRITICAL':'\x1b[35m','HOT':'\x1b[1;35m'}

    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created)
        s = ct.strftime("%H:%M:%S") + f".{int(ct.microsecond / 1000):03d}"
        return f"{BLUE}{s}{RESET}"

    def format(self, record):
        c = self.COLORS.get(record.levelname, '')
        record.levelname = f"{c}{record.levelname}{RESET}"
        return super().format(record)

class PlainFormatter(logging.Formatter):
    """文件日志格式（无颜色）"""
    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created)
        return ct.strftime("%H:%M:%S") + f".{int(ct.microsecond / 1000):03d}"

    def __init__(self):
        super().__init__("[%(asctime)s] %(levelname)-7s %(message)s")

HOT_LEVEL = 25
logging.addLevelName(HOT_LEVEL, "HOT")

class HotLogger(logging.Logger):
    def hot(self, msg, *args, **kwargs):
        if self.isEnabledFor(HOT_LEVEL): self._log(HOT_LEVEL, msg, args, **kwargs)
    def success(self, msg, *args, **kwargs):
        self.info(msg, *args, **kwargs)
    def fail(self, msg, *args, **kwargs):
        self.error(msg, *args, **kwargs)
    def time(self, msg, *args, **kwargs):
        self.debug(msg, *args, **kwargs)

logging.setLoggerClass(HotLogger)

_log = None

def get_logger(name="2233"):
    global _log
    if _log is None:
        _log = logging.getLogger(name)
        _log.setLevel(logging.INFO)
        if not _log.handlers:
            # 控制台 handler（带颜色，时间蓝色 + 毫秒）
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(ColoredFormatter("[%(asctime)s] %(levelname)-7s %(message)s"))
            _log.addHandler(h)
            # 文件 handler（无颜色，保存到 logs/）
            fh = logging.FileHandler("logs/ticket_grabber.log", encoding="utf-8")
            fh.setFormatter(PlainFormatter())
            _log.addHandler(fh)
    return _log

logger = get_logger()
