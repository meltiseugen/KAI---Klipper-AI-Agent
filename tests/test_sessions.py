from datetime import datetime, timezone

from klipperai_agent.application.sessions import InMemorySessionStore


def test_session_roundtrip() -> None:
    store = InMemorySessionStore(ttl_seconds=60)
    session = store.create()
    assert store.exists(session.session_id)
    loaded = store.get(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id


def test_expired_sessions_are_purged() -> None:
    store = InMemorySessionStore(ttl_seconds=60)
    session = store.create()
    session.expires_at = datetime.now(timezone.utc)
    assert store.get(session.session_id) is None
