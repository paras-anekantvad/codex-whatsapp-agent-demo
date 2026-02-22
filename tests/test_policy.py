"""Tests for policy enforcement."""

from app.policy import is_allowed_item_type, should_auto_decline_server_request


def test_policy_allows_web_search_items() -> None:
    assert is_allowed_item_type("webSearch")


def test_policy_allows_agent_message() -> None:
    assert is_allowed_item_type("agentMessage")


def test_policy_allows_user_message() -> None:
    assert is_allowed_item_type("userMessage")


def test_policy_allows_reasoning() -> None:
    assert is_allowed_item_type("reasoning")


def test_policy_allows_context_compaction() -> None:
    assert is_allowed_item_type("contextCompaction")


def test_policy_blocks_command_execution_items() -> None:
    assert not is_allowed_item_type("commandExecution")


def test_policy_blocks_file_change_items() -> None:
    assert not is_allowed_item_type("fileChange")


def test_policy_auto_declines_approval_requests() -> None:
    assert should_auto_decline_server_request("item/commandExecution/requestApproval")
    assert should_auto_decline_server_request("item/fileChange/requestApproval")


def test_policy_does_not_decline_non_approval_requests() -> None:
    assert not should_auto_decline_server_request("thread/start")
    assert not should_auto_decline_server_request("turn/start")
