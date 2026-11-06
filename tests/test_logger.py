"""日志模块的测试。"""
import logging
import uuid

import pytest

from src.logger import Logger


@pytest.fixture
def unique_name():
    return f"test-logger-{uuid.uuid4().hex}"


class TestFileOutput:
    def test_writes_to_configured_path(self, tmp_path, unique_name):
        log_file = tmp_path / "custom" / "app.log"
        lg = Logger(name=unique_name, log_dir=str(tmp_path / "logs"),
                    file_path=str(log_file), level="DEBUG")
        lg.info("hello world")
        lg.success("done")

        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "hello world" in content
        assert "[OK]" in content

    def test_default_path_when_not_configured(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path / "logs"))
        lg.info("default path")
        files = list((tmp_path / "logs").glob("*.log"))
        assert len(files) == 1
        assert "default path" in files[0].read_text(encoding="utf-8")

    def test_save_to_file_false_creates_no_handler(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path / "logs"),
                    save_to_file=False)
        lg.info("not persisted")
        assert lg._file_handler is None
        assert not (tmp_path / "logs").exists() or not list(
            (tmp_path / "logs").glob("*.log"))

    def test_reconfigure_switches_file(self, tmp_path, unique_name):
        first = tmp_path / "first.log"
        second = tmp_path / "second.log"
        lg = Logger(name=unique_name, log_dir=str(tmp_path), file_path=str(first))
        lg.info("to first")

        lg.configure(file_path=str(second))
        lg.info("to second")

        assert "to first" in first.read_text(encoding="utf-8")
        assert "to second" in second.read_text(encoding="utf-8")
        assert "to second" not in first.read_text(encoding="utf-8")

    def test_reconfigure_does_not_stack_handlers(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path))
        baseline = len(lg.logger.handlers)
        lg.configure(file_path=str(tmp_path / "a.log"))
        lg.configure(file_path=str(tmp_path / "b.log"))
        assert len(lg.logger.handlers) == baseline

    def test_reconfigure_removes_empty_previous_file(self, tmp_path, unique_name):
        """切换日志路径后不应残留导入时创建的空文件。"""
        lg = Logger(name=unique_name, log_dir=str(tmp_path / "logs"))
        first = lg.log_file
        assert first.exists()

        lg.configure(file_path=str(tmp_path / "second.log"))
        assert not first.exists()
        assert (tmp_path / "second.log").exists()

    def test_reconfigure_keeps_non_empty_previous_file(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path / "logs"))
        first = lg.log_file
        lg.info("written")

        lg.configure(file_path=str(tmp_path / "second.log"))
        assert first.exists()

    def test_relative_path_resolves_against_cwd(self, tmp_path, unique_name,
                                                monkeypatch):
        monkeypatch.chdir(tmp_path)
        lg = Logger(name=unique_name, log_dir="logs",
                    file_path="logs/relative.log")
        lg.info("relative")
        assert (tmp_path / "logs" / "relative.log").exists()


class TestLevels:
    def test_console_level_applied(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path), level="WARNING",
                    save_to_file=False)
        assert lg._console_handler.level == logging.WARNING

    def test_unknown_level_falls_back_to_info(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path),
                    level="NOT_A_LEVEL", save_to_file=False)
        assert lg._console_handler.level == logging.INFO

    def test_debug_and_error_are_written(self, tmp_path, unique_name):
        log_file = tmp_path / "levels.log"
        lg = Logger(name=unique_name, log_dir=str(tmp_path),
                    file_path=str(log_file), level="DEBUG")
        lg.debug("dbg")
        lg.error("err")
        content = log_file.read_text(encoding="utf-8")
        assert "dbg" in content
        assert "err" in content


class TestConvenienceMethods:
    def test_success_and_fail_tags(self, tmp_path, unique_name):
        log_file = tmp_path / "tags.log"
        lg = Logger(name=unique_name, log_dir=str(tmp_path),
                    file_path=str(log_file))
        lg.success("ok")
        lg.fail("bad")
        content = log_file.read_text(encoding="utf-8")
        assert "[OK]" in content
        assert "[FAIL]" in content

    def test_hot_and_time_do_not_crash(self, tmp_path, unique_name):
        lg = Logger(name=unique_name, log_dir=str(tmp_path),
                    file_path=str(tmp_path / "hot.log"))
        lg.hot("热闹")
        lg.time("时间")
        content = (tmp_path / "hot.log").read_text(encoding="utf-8")
        assert "[HOT]" in content
