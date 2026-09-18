from __future__ import annotations

import re

from core.logger import Logger


def test_writes_formatted_line_to_daily_file(tmp_path):
    logger = Logger(log_dir=str(tmp_path))
    logger.info("hello")
    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] INFO  hello\n$", content)


def test_level_names_and_padding(tmp_path):
    logger = Logger(log_dir=str(tmp_path))
    logger.warning("w")
    logger.error("e")
    logger.state("s")
    content = next(tmp_path.glob("*.log")).read_text(encoding="utf-8")
    assert "WARN  w" in content
    assert "ERROR e" in content
    assert "STATE s" in content


def test_creates_log_dir(tmp_path):
    target = tmp_path / "nested" / "logs"
    Logger(log_dir=str(target))
    assert target.is_dir()


def test_callback_delivered_only_on_flush(tmp_path):
    logger = Logger(log_dir=str(tmp_path))
    received = []
    logger.on_log(received.append)
    logger.info("x")
    assert received == []
    logger.flush()
    assert len(received) == 1
    assert "x" in received[0]


def test_flush_isolates_raising_callback(tmp_path):
    logger = Logger(log_dir=str(tmp_path))
    good = []

    def bad(line):
        raise RuntimeError("boom")

    logger.on_log(bad)
    logger.on_log(good.append)
    logger.info("x")
    logger.flush()
    assert len(good) == 1


def test_multiple_callbacks_all_receive(tmp_path):
    logger = Logger(log_dir=str(tmp_path))
    a, b = [], []
    logger.on_log(a.append)
    logger.on_log(b.append)
    logger.info("x")
    logger.flush()
    assert len(a) == 1
    assert len(b) == 1
