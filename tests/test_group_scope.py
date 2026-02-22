"""Tests for inbound access policy and group rejection."""

from app.main import _parse_approved_sender_identities, _should_process_inbound
from app.models import InboundMessage


def _payload(
    from_id: str,
    *,
    text: str = "/help",
    from_me: bool = False,
    is_group: bool,
    self_jid: str | None = "12345@s.whatsapp.net",
    from_identity: str | None = None,
) -> InboundMessage:
    return InboundMessage.model_validate(
        {
            "from": from_id,
            "text": text,
            "from_me": from_me,
            "is_group": is_group,
            "self_jid": self_jid,
            "from_identity": from_identity,
        }
    )


def _approved(*values: str) -> set[str]:
    return _parse_approved_sender_identities(list(values))


def test_allows_approved_dm_sender() -> None:
    payload = _payload("12345@s.whatsapp.net", is_group=False)
    assert (
        _should_process_inbound(
            payload,
            access_mode="approved_senders",
            approved_sender_identities=_approved("+12345"),
        )
        is True
    )


def test_allows_approved_dm_sender_with_device_suffix() -> None:
    payload = _payload("12345:17@s.whatsapp.net", is_group=False)
    assert (
        _should_process_inbound(
            payload,
            access_mode="approved_senders",
            approved_sender_identities=_approved("12345@s.whatsapp.net"),
        )
        is True
    )


def test_rejects_unapproved_dm_sender() -> None:
    payload = _payload("99999@s.whatsapp.net", is_group=False)
    assert (
        _should_process_inbound(
            payload,
            access_mode="approved_senders",
            approved_sender_identities=_approved("+12345"),
        )
        is False
    )


def test_rejects_groups_even_for_approved_sender() -> None:
    group_payload = _payload("12345@g.us", is_group=True)
    assert (
        _should_process_inbound(
            group_payload,
            access_mode="approved_senders",
            approved_sender_identities=_approved("+12345"),
        )
        is False
    )


def test_rejects_from_me_when_identity_differs() -> None:
    payload = _payload(
        "12345@s.whatsapp.net",
        is_group=False,
        from_me=True,
    )
    assert (
        _should_process_inbound(
            payload,
            access_mode="approved_senders",
            approved_sender_identities=_approved("+12345"),
        )
        is False
    )


def test_rejects_when_allowlist_empty() -> None:
    payload = _payload("12345@s.whatsapp.net", is_group=False)
    assert (
        _should_process_inbound(
            payload,
            access_mode="approved_senders",
            approved_sender_identities=set(),
        )
        is False
    )


def test_self_chat_mode_allows_strict_self_only() -> None:
    payload = _payload(
        "12345:17@s.whatsapp.net",
        is_group=False,
        from_me=True,
        self_jid="12345@s.whatsapp.net",
    )
    assert (
        _should_process_inbound(
            payload,
            access_mode="self_chat",
            approved_sender_identities=set(),
        )
        is True
    )


def test_self_chat_mode_rejects_non_self_sender() -> None:
    payload = _payload(
        "99999@s.whatsapp.net",
        is_group=False,
        from_me=True,
        self_jid="12345@s.whatsapp.net",
    )
    assert (
        _should_process_inbound(
            payload,
            access_mode="self_chat",
            approved_sender_identities=_approved("+99999"),
        )
        is False
    )


def test_self_chat_mode_allows_self_identity_when_not_from_me() -> None:
    payload = _payload(
        "12345@s.whatsapp.net",
        is_group=False,
        from_me=False,
        self_jid="12345@s.whatsapp.net",
    )
    assert (
        _should_process_inbound(
            payload,
            access_mode="self_chat",
            approved_sender_identities=set(),
        )
        is True
    )


def test_parse_approved_senders_from_comma_separated_string() -> None:
    parsed = _parse_approved_sender_identities("+12345, 67890@s.whatsapp.net, whatsapp:+441234")
    assert parsed == {"12345", "67890", "441234"}


def test_parse_approved_senders_from_list_and_newlines() -> None:
    parsed = _parse_approved_sender_identities(["+12345\n+67890", "99999@lid", "  "])
    assert parsed == {"12345", "67890", "99999"}


def test_self_chat_uses_from_identity_when_provided() -> None:
    payload = _payload(
        "someother@lid",
        is_group=False,
        from_me=True,
        self_jid="12345@s.whatsapp.net",
        from_identity="12345@s.whatsapp.net",
    )
    assert (
        _should_process_inbound(
            payload,
            access_mode="self_chat",
            approved_sender_identities=set(),
        )
        is True
    )
