"""Tests for slash command parsing."""

from app.command_parser import parse_slash_command


def test_parse_slash_command_with_args() -> None:
    parsed = parse_slash_command("/resume thr_123")
    assert parsed is not None
    assert parsed.name == "resume"
    assert parsed.args == "thr_123"


def test_parse_slash_command_lowercases_name() -> None:
    parsed = parse_slash_command("/NeW my topic")
    assert parsed is not None
    assert parsed.name == "new"
    assert parsed.args == "my topic"


def test_parse_non_command_returns_none() -> None:
    assert parse_slash_command("hello") is None


def test_parse_empty_command_returns_none() -> None:
    assert parse_slash_command("/") is None


def test_parse_command_without_args() -> None:
    parsed = parse_slash_command("/help")
    assert parsed is not None
    assert parsed.name == "help"
    assert parsed.args == ""


def test_parse_command_with_whitespace() -> None:
    parsed = parse_slash_command("  /sessions  5  ")
    assert parsed is not None
    assert parsed.name == "sessions"
    assert parsed.args == "5"
