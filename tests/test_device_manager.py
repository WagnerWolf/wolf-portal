import inspect
import os
import sys
import tempfile
from pathlib import Path

import app.database as database
from app.device_manager import (
    discover_device,
    authorize_device,
    block_device,
    disable_device,
    reauthorize_device,
    rename_device,
    list_events,
)
from app.models import DeviceStatus


MAC = "aa:bb:cc:dd:ee:ff"


def test_discover_device():
    device = discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    assert device["status"] == DeviceStatus.PENDING.value
    assert device["mac"] == MAC
    assert device["ip"] == "10.0.69.230"


def test_authorize_device():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    device = authorize_device(
        MAC,
        source="telegram",
    )

    assert device["status"] == DeviceStatus.AUTHORIZED.value

    with database.get_connection() as conn:
        events = conn.execute(
            """
            SELECT *
            FROM events
            WHERE device_id = ?
            ORDER BY id
            """,
            (device["id"],),
        ).fetchall()

        assert len(events) == 2
        assert events[0]["event_type"] == "DEVICE_DETECTED"
        assert events[1]["event_type"] == "DEVICE_AUTHORIZED"
        assert events[1]["source"] == "telegram"


def test_disable_device():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    authorize_device(
        MAC,
        source="telegram",
    )

    device = disable_device(
        MAC,
        source="telegram",
    )

    assert device["status"] == DeviceStatus.DISABLED.value


def test_reauthorize_device():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    authorize_device(
        MAC,
        source="telegram",
    )

    disable_device(
        MAC,
        source="telegram",
    )

    device = reauthorize_device(
        MAC,
        source="telegram",
    )

    assert device["status"] == DeviceStatus.AUTHORIZED.value


def test_rename_device():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    device = rename_device(
        MAC,
        "celular-filha",
        source="telegram",
    )

    assert device["hostname"] == "celular-filha"

    with database.get_connection() as conn:
        events = conn.execute(
            """
            SELECT *
            FROM events
            WHERE device_id = ?
            ORDER BY id
            """,
            (device["id"],),
        ).fetchall()

        assert events[-1]["event_type"] == "HOSTNAME_CHANGED"
        assert events[-1]["source"] == "telegram"


def test_block_device():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    authorize_device(
        MAC,
        source="telegram",
    )

    device = block_device(
        MAC,
        source="telegram",
    )

    assert device["status"] == DeviceStatus.BLOCKED.value


def test_full_status_cycle():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    device = authorize_device(
        MAC,
        source="telegram",
    )
    assert device["status"] == DeviceStatus.AUTHORIZED.value

    device = disable_device(
        MAC,
        source="telegram",
    )
    assert device["status"] == DeviceStatus.DISABLED.value

    device = reauthorize_device(
        MAC,
        source="telegram",
    )
    assert device["status"] == DeviceStatus.AUTHORIZED.value

    device = block_device(
        MAC,
        source="telegram",
    )
    assert device["status"] == DeviceStatus.BLOCKED.value

    device = reauthorize_device(
        MAC,
        source="telegram",
    )
    assert device["status"] == DeviceStatus.AUTHORIZED.value


def test_history():
    discover_device(
        MAC,
        ip="10.0.69.230",
        hostname="Samsung",
    )

    authorize_device(
        MAC,
        source="telegram",
    )

    disable_device(
        MAC,
        source="telegram",
    )

    events = list_events(MAC)

    assert len(events) == 3

    assert events[0]["event_type"] == "DEVICE_DETECTED"
    assert events[1]["event_type"] == "DEVICE_AUTHORIZED"
    assert events[2]["event_type"] == "DEVICE_DISABLED"


def run_tests():
    tests = [
        obj
        for name, obj in globals().items()
        if name.startswith("test_")
        and inspect.isfunction(obj)
    ]

    failed = 0

    for test in tests:
        with tempfile.NamedTemporaryFile(
            prefix="wolf-portal-test-",
            suffix=".db",
            delete=False,
        ) as tmp:
            test_database = tmp.name

        database.DATABASE_PATH = Path(test_database)

        try:
            database.initialize_database()

            test()

            print(f"[PASS] {test.__name__}")

        except Exception as exc:
            failed += 1
            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: {exc!r}"
            )

        finally:
            try:
                os.unlink(test_database)
            except FileNotFoundError:
                pass

    print()
    print(f"Testes: {len(tests)}")
    print(f"Falhas: {failed}")

    return failed


if __name__ == "__main__":
    failed = run_tests()
    sys.exit(1 if failed else 0)