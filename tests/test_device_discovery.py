import inspect
import sys

from tests.test_helpers import isolated_database


MAC = "40:ff:a1:20:eb:92"
IP = "10.0.69.197"


def make_event(
    mac=MAC,
    ip=IP,
):
    from app.network_monitor import Presence
    from app.presence_manager import (
        PresenceEvent,
        PresenceEventType,
    )

    return PresenceEvent(
        event_type=PresenceEventType.DEVICE_ONLINE,
        mac=mac,
        ip=ip,
        presence=Presence.PRESENT,
    )


@isolated_database
def test_new_device_is_created_as_pending():
    from app.database import get_connection
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    result = discovery.process_event(
        make_event()
    )

    assert result.new_device is True
    assert result.status == "PENDING"
    assert result.mac == MAC
    assert result.ip == IP

    with get_connection() as conn:
        device = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE mac = ?
            """,
            (MAC,),
        ).fetchone()

        assert device is not None
        assert device["status"] == "PENDING"
        assert device["ip"] == IP

        events = conn.execute(
            """
            SELECT *
            FROM events
            WHERE device_id = ?
            """,
            (device["id"],),
        ).fetchall()

        assert len(events) == 1
        assert events[0]["event_type"] == "DEVICE_DETECTED"


@isolated_database
def test_existing_device_does_not_create_new_device():
    from app.database import get_connection
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    first = discovery.process_event(
        make_event()
    )

    second = discovery.process_event(
        make_event()
    )

    assert first.device_id == second.device_id
    assert second.new_device is False

    with get_connection() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM devices
            WHERE mac = ?
            """,
            (MAC,),
        ).fetchone()[0]

        assert count == 1


@isolated_database
def test_existing_device_updates_last_seen():
    from app.database import get_connection
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    result = discovery.process_event(
        make_event()
    )

    with get_connection() as conn:
        before = conn.execute(
            """
            SELECT last_seen
            FROM devices
            WHERE id = ?
            """,
            (result.device_id,),
        ).fetchone()["last_seen"]

    result = discovery.process_event(
        make_event()
    )

    with get_connection() as conn:
        after = conn.execute(
            """
            SELECT last_seen
            FROM devices
            WHERE id = ?
            """,
            (result.device_id,),
        ).fetchone()["last_seen"]

    assert after >= before


@isolated_database
def test_ip_change_is_recorded():
    from app.database import get_connection
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    result = discovery.process_event(
        make_event(
            ip="10.0.69.197",
        )
    )

    result = discovery.process_event(
        make_event(
            ip="10.0.69.198",
        )
    )

    assert result.ip_changed is True

    with get_connection() as conn:
        device = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE id = ?
            """,
            (result.device_id,),
        ).fetchone()

        assert device["ip"] == "10.0.69.198"

        events = conn.execute(
            """
            SELECT *
            FROM events
            WHERE device_id = ?
            ORDER BY id
            """,
            (result.device_id,),
        ).fetchall()

        assert len(events) == 2
        assert events[1]["event_type"] == "IP_CHANGED"


@isolated_database
def test_same_ip_does_not_create_ip_event():
    from app.database import get_connection
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    result = discovery.process_event(
        make_event(
            ip="10.0.69.197",
        )
    )

    discovery.process_event(
        make_event(
            ip="10.0.69.197",
        )
    )

    with get_connection() as conn:
        events = conn.execute(
            """
            SELECT *
            FROM events
            WHERE device_id = ?
            """,
            (result.device_id,),
        ).fetchall()

        assert len(events) == 1


@isolated_database
def test_offline_event_is_ignored():
    from app.network_monitor import Presence
    from app.presence_manager import (
        PresenceEvent,
        PresenceEventType,
    )
    from app.device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()

    event = PresenceEvent(
        event_type=PresenceEventType.DEVICE_OFFLINE,
        mac=MAC,
        ip=IP,
        presence=Presence.ABSENT,
    )

    result = discovery.process_event(event)

    assert result is None


if __name__ == "__main__":
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
