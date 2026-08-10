"""Tests for structured logging configuration."""

import json

import pytest
import structlog

from app.logging.setup import configure_logging


def test_json_logging_emits_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_level="INFO", log_format="json")
    structlog.get_logger("test").info("test_event", key="value")

    out = capsys.readouterr().out.strip()
    record = json.loads(out.splitlines()[-1])
    assert record["event"] == "test_event"
    assert record["key"] == "value"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_console_logging_emits_event(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_level="INFO", log_format="console")
    structlog.get_logger("test").info("console_event")

    out = capsys.readouterr().out
    assert "console_event" in out
