from __future__ import annotations

import logging

from agents.common.logging import (
    bind_session_id,
    configure_logging,
    get_session_id,
)


def test_bind_session_id_restores_default():
    assert get_session_id() == "-"
    with bind_session_id("sess-1"):
        assert get_session_id() == "sess-1"
    assert get_session_id() == "-"


def test_configure_logging_is_idempotent():
    configure_logging()
    n_handlers = len(logging.getLogger().handlers)
    configure_logging()
    assert len(logging.getLogger().handlers) == n_handlers
