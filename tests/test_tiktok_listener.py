import asyncio
import time
import types


def make_listener(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    return LocalTikTokListener(unique_id="@example")


def test_fetch_events_drains_event_queue(app_module):
    listener = make_listener(app_module)
    listener.event_queue.put({"type": "comment", "user": "alice", "text": "hello"})
    listener.event_queue.put({"type": "follow", "user": "bob"})

    events = listener.fetch_events()

    assert events == [
        {"type": "comment", "user": "alice", "text": "hello"},
        {"type": "follow", "user": "bob"},
    ]
    assert listener.event_queue.empty()


def test_enqueue_status_adds_tiktok_status_event(app_module):
    listener = make_listener(app_module)

    listener.enqueue_status("error", "TikTokLive接続エラー: boom")

    assert listener.fetch_events() == [
        {
            "type": "tiktok_status",
            "status": "error",
            "label": "接続エラー",
            "message": "TikTokLive接続エラー: boom",
        }
    ]


def test_fetch_events_groups_three_or_more_joined_users(app_module):
    listener = make_listener(app_module)
    listener.join_buffer = ["alice", "bob", "carol"]

    events = listener.fetch_events()

    assert events == [{"type": "join_bulk", "users": "alice, bob, carol", "count": 3}]
    assert listener.join_buffer == []


def test_fetch_events_groups_stale_small_join_buffer(app_module):
    listener = make_listener(app_module)
    listener.join_buffer = ["alice"]
    listener.join_seen_at = {"alice": time.time() - listener.join_flush_after_seconds}

    events = listener.fetch_events()

    assert events == [{"type": "join_bulk", "users": "alice", "count": 1}]
    assert listener.join_buffer == []


def test_fetch_events_keeps_recent_small_join_buffer(app_module):
    listener = make_listener(app_module)
    listener.join_buffer = ["alice", "bob"]
    listener.join_seen_at = {"alice": time.time(), "bob": time.time()}

    events = listener.fetch_events()

    assert events == []
    assert listener.join_buffer == ["alice", "bob"]


def test_fetch_events_limits_join_names_to_four(app_module):
    listener = make_listener(app_module)
    listener.join_buffer = ["alice", "bob", "carol", "dave", "erin"]
    listener.join_seen_at = {user: time.time() for user in listener.join_buffer}

    events = listener.fetch_events()

    assert events == [
        {"type": "join_bulk", "users": "alice, bob, carol, dave", "count": 4}
    ]
    assert listener.join_buffer == ["erin"]


def test_leave_event_removes_user_from_join_buffer(app_module):
    listener = make_listener(app_module)
    join_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "JoinEvent"
    )
    leave_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "LeaveEvent"
    )

    asyncio.run(join_handler(types.SimpleNamespace(user=types.SimpleNamespace(nickname="alice"))))
    asyncio.run(leave_handler(types.SimpleNamespace(user=types.SimpleNamespace(nickname="alice"))))

    assert listener.join_buffer == []
    assert listener.join_seen_at == {}


def test_extract_gift_name_uses_canonical_gift_name(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(gift=types.SimpleNamespace(name="Rose"))

    assert LocalTikTokListener.extract_gift_name(event) == "Rose"


def test_extract_gift_name_falls_back_to_legacy_info_name(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(info=types.SimpleNamespace(name="Rose"))
    )

    assert LocalTikTokListener.extract_gift_name(event) == "Rose"


def test_extract_gift_name_returns_none_when_missing(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(gift=types.SimpleNamespace())

    assert LocalTikTokListener.extract_gift_name(event) is None


def test_extract_diamond_count_uses_canonical_value(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(name="Rose", diamond_count=10)
    )

    assert LocalTikTokListener.extract_diamond_count(event) == 10


def test_extract_diamond_count_falls_back_to_legacy_info(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(
            name="Rose",
            info=types.SimpleNamespace(diamond_count="25"),
        )
    )

    assert LocalTikTokListener.extract_diamond_count(event) == 25


def test_extract_diamond_count_ignores_missing_or_invalid_values(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(diamond_count=0, info=types.SimpleNamespace())
    )

    assert LocalTikTokListener.extract_diamond_count(event) is None


def test_gift_handler_enqueues_repeat_and_value_metrics(app_module):
    listener = make_listener(app_module)
    gift_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "GiftEvent"
    )
    event = types.SimpleNamespace(
        user=types.SimpleNamespace(nickname="alice"),
        gift=types.SimpleNamespace(name="Rose", type=1, diamond_count=10),
        repeat_count=5,
        streaking=False,
    )

    asyncio.run(gift_handler(event))

    assert listener.fetch_events() == [
        {
            "type": "gift",
            "user": "alice",
            "gift_name": "Rose",
            "repeat_count": 5,
            "diamond_count": 10,
            "total_diamonds": 50,
        }
    ]


def test_streaking_gift_event_is_in_progress(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        streaking=True,
        gift=types.SimpleNamespace(name="Rose", type=1),
    )

    assert LocalTikTokListener.is_streak_in_progress(event) is True


def test_finished_streak_gift_event_is_not_in_progress(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        streaking=False,
        repeat_count=5,
        gift=types.SimpleNamespace(name="Rose", type=1),
    )

    assert LocalTikTokListener.is_streak_in_progress(event) is False
    assert LocalTikTokListener.extract_repeat_count(event) == 5


def test_repeat_end_zero_gift_event_is_in_progress(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        repeat_end=0,
        gift=types.SimpleNamespace(name="Rose", type=1),
    )

    assert LocalTikTokListener.is_streak_in_progress(event) is True


def test_non_streakable_gift_event_is_not_in_progress(app_module):
    from local_agent.tiktok.listener import LocalTikTokListener

    event = types.SimpleNamespace(
        gift=types.SimpleNamespace(name="Gift", type=0),
    )

    assert LocalTikTokListener.is_streak_in_progress(event) is False


def test_own_comment_is_silently_dropped(app_module):
    listener = make_listener(app_module)
    comment_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "CommentEvent"
    )

    asyncio.run(comment_handler(types.SimpleNamespace(
        user=types.SimpleNamespace(nickname="Example", unique_id="example"),
        comment="hello",
    )))

    assert listener.event_queue.empty()


def test_comment_with_unknown_unique_id_is_not_dropped(app_module):
    listener = make_listener(app_module)
    comment_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "CommentEvent"
    )

    asyncio.run(comment_handler(types.SimpleNamespace(
        user=types.SimpleNamespace(nickname="viewer", unique_id=""),
        comment="nice",
    )))

    assert listener.fetch_events() == [
        {"type": "comment", "user": "viewer", "text": "nice"}
    ]


def test_other_user_comment_is_enqueued(app_module):
    listener = make_listener(app_module)
    comment_handler = next(
        handler
        for event_type, handler in listener.client.handlers
        if event_type.__name__ == "CommentEvent"
    )

    asyncio.run(comment_handler(types.SimpleNamespace(
        user=types.SimpleNamespace(nickname="viewer", unique_id="viewer123"),
        comment="good game",
    )))

    assert listener.fetch_events() == [
        {"type": "comment", "user": "viewer", "text": "good game"}
    ]
