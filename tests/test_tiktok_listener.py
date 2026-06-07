import time
import types


def test_fetch_events_drains_event_queue(app_module):
    listener = app_module.TikTokListener(unique_id="@example")
    listener.event_queue.put({"type": "comment", "user": "alice", "text": "hello"})
    listener.event_queue.put({"type": "follow", "user": "bob"})

    events = listener.fetch_events()

    assert events == [
        {"type": "comment", "user": "alice", "text": "hello"},
        {"type": "follow", "user": "bob"},
    ]
    assert listener.event_queue.empty()


def test_fetch_events_groups_three_or_more_joined_users(app_module):
    listener = app_module.TikTokListener(unique_id="@example")
    listener.join_buffer = ["alice", "bob", "carol"]

    events = listener.fetch_events()

    assert events == [{"type": "join_bulk", "users": "alice, bob, carol", "count": 3}]
    assert listener.join_buffer == []


def test_fetch_events_groups_stale_join_buffer(app_module):
    listener = app_module.TikTokListener(unique_id="@example")
    listener.join_buffer = ["alice"]
    listener.last_join_time = time.time() - 11

    events = listener.fetch_events()

    assert events == [{"type": "join_bulk", "users": "alice", "count": 1}]
    assert listener.join_buffer == []


def test_fetch_events_keeps_recent_small_join_buffer(app_module):
    listener = app_module.TikTokListener(unique_id="@example")
    listener.join_buffer = ["alice", "bob"]
    listener.last_join_time = time.time()

    events = listener.fetch_events()

    assert events == []
    assert listener.join_buffer == ["alice", "bob"]


def test_extract_gift_name_uses_canonical_gift_name(app_module):
    event = types.SimpleNamespace(gift=types.SimpleNamespace(name="Rose"))

    assert app_module.TikTokListener.extract_gift_name(event) == "Rose"


def test_extract_gift_name_falls_back_to_legacy_info_name(app_module):
    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(info=types.SimpleNamespace(name="Rose"))
    )

    assert app_module.TikTokListener.extract_gift_name(event) == "Rose"


def test_extract_gift_name_returns_none_when_missing(app_module):
    event = types.SimpleNamespace(gift=types.SimpleNamespace())

    assert app_module.TikTokListener.extract_gift_name(event) is None
