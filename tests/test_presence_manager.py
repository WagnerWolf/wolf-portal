from app.network_monitor import Neighbor, Presence
from app.presence_manager import (
    PresenceEventType,
    PresenceManager,
)


MAC = "40:ff:a1:20:eb:92"
IP = "10.0.69.197"


def neighbor(
    presence=Presence.PRESENT,
    mac=MAC,
    ip=IP,
):
    return Neighbor(
        ip=ip,
        mac=mac,
        state="REACHABLE",
        presence=presence,
    )


def test_new_device_generates_online_event():
    manager = PresenceManager()

    events = manager.process([
        neighbor(),
    ])

    assert len(events) == 1
    assert events[0].event_type == PresenceEventType.DEVICE_ONLINE
    assert events[0].mac == MAC
    assert events[0].ip == IP


def test_continuous_presence_does_not_generate_duplicate_events():
    manager = PresenceManager()

    events = manager.process([
        neighbor(),
    ])

    assert len(events) == 1

    events = manager.process([
        neighbor(),
    ])

    assert len(events) == 0

    events = manager.process([
        neighbor(),
    ])

    assert len(events) == 0


def test_device_must_be_absent_for_threshold_cycles():
    manager = PresenceManager(absent_threshold=3)

    manager.process([
        neighbor(),
    ])

    assert manager.get_state(MAC).presence == Presence.PRESENT

    events = manager.process([])
    assert events == []
    assert manager.get_state(MAC).presence == Presence.PRESENT

    events = manager.process([])
    assert events == []
    assert manager.get_state(MAC).presence == Presence.PRESENT

    events = manager.process([])

    assert len(events) == 1
    assert events[0].event_type == PresenceEventType.DEVICE_OFFLINE
    assert manager.get_state(MAC).presence == Presence.ABSENT


def test_device_reappearing_generates_online_event_again():
    manager = PresenceManager(absent_threshold=2)

    manager.process([
        neighbor(),
    ])

    manager.process([])
    manager.process([])

    assert manager.get_state(MAC).presence == Presence.ABSENT

    events = manager.process([
        neighbor(),
    ])

    assert len(events) == 1
    assert events[0].event_type == PresenceEventType.DEVICE_ONLINE
    assert manager.get_state(MAC).presence == Presence.PRESENT


def test_reappearance_is_not_a_new_device():
    manager = PresenceManager(absent_threshold=2)

    manager.process([
        neighbor(),
    ])

    manager.process([])
    manager.process([])

    manager.process([
        neighbor(),
    ])

    states = manager.get_states()

    assert len(states) == 1
    assert states[0].mac == MAC


def test_unknown_does_not_generate_online_event():
    manager = PresenceManager()

    events = manager.process([
        neighbor(
            presence=Presence.UNKNOWN,
        ),
    ])

    assert events == []

    assert manager.get_state(MAC).presence == Presence.UNKNOWN


def test_unknown_followed_by_present_generates_online_event():
    manager = PresenceManager()

    events = manager.process([
        neighbor(
            presence=Presence.UNKNOWN,
        ),
    ])

    assert events == []

    events = manager.process([
        neighbor(
            presence=Presence.PRESENT,
        ),
    ])

    assert len(events) == 1
    assert events[0].event_type == PresenceEventType.DEVICE_ONLINE


def test_clear_removes_all_states():
    manager = PresenceManager()

    manager.process([
        neighbor(),
    ])

    assert len(manager.get_states()) == 1

    manager.clear()

    assert len(manager.get_states()) == 0


if __name__ == "__main__":
    import inspect
    import sys

    tests = [
        obj
        for name, obj in globals().items()
        if name.startswith("test_")
        and inspect.isfunction(obj)
    ]

    failed = 0

    for test in tests:
        try:
            test()
            print(f"[PASS] {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {test.__name__}: {exc}")

    print()
    print(f"Testes: {len(tests)}")
    print(f"Falhas: {failed}")

    sys.exit(1 if failed else 0)
