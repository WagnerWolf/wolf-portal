import inspect
import os
import sys
import tempfile

import app.database as database

from app.discovery_cycle import DiscoveryCycle
from app.network_monitor import Neighbor, Presence
from app.presence_manager import (
    PresenceEventType,
)
from app.database import get_connection


MAC = "40:ff:a1:20:eb:92"
IP = "10.0.69.197"


class FakeNetworkMonitor:

    def __init__(self, neighbors=None):
        self.neighbors = neighbors or []

    def get_neighbors(self):
        return self.neighbors


def neighbor(
    presence=Presence.PRESENT,
    mac=MAC,
    ip=IP,
    state="REACHABLE",
):
    return Neighbor(
        ip=ip,
        mac=mac,
        state=state,
        presence=presence,
    )


def test_new_device_is_discovered():
    monitor = FakeNetworkMonitor([
        neighbor(),
    ])

    cycle = DiscoveryCycle(
        network_monitor=monitor,
    )

    result = cycle.run_once()

    assert len(result.events) == 1
    assert result.events[0].event_type == PresenceEventType.DEVICE_ONLINE

    assert len(result.discoveries) == 1

    discovery = result.discoveries[0]

    assert discovery.new_device is True
    assert discovery.mac == MAC
    assert discovery.ip == IP
    assert discovery.status == "PENDING"

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


def test_continuous_presence_does_not_rediscover_device():
    monitor = FakeNetworkMonitor([
        neighbor(),
    ])

    cycle = DiscoveryCycle(
        network_monitor=monitor,
    )

    first = cycle.run_once()
    second = cycle.run_once()
    third = cycle.run_once()

    # Presença gera evento somente na primeira observação.
    assert len(first.events) == 1
    assert second.events == []
    assert third.events == []

    # Discovery observa o dispositivo em todos os ciclos.
    assert len(first.discoveries) == 1
    assert len(second.discoveries) == 1
    assert len(third.discoveries) == 1

    # Somente o primeiro ciclo cria o dispositivo.
    assert first.discoveries[0].new_device is True
    assert second.discoveries[0].new_device is False
    assert third.discoveries[0].new_device is False

    # Todos os ciclos devem apontar para o mesmo dispositivo.
    assert (
        first.discoveries[0].device_id
        == second.discoveries[0].device_id
        == third.discoveries[0].device_id
    )

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


def test_device_offline_is_not_sent_to_discovery():
    monitor = FakeNetworkMonitor([
        neighbor(),
    ])

    cycle = DiscoveryCycle(
        network_monitor=monitor,
    )

    first = cycle.run_once()

    assert len(first.discoveries) == 1

    monitor.neighbors = []

    cycle.presence_manager = type(cycle.presence_manager)(
        absent_threshold=1
    )

    # Recria a presença inicial no novo manager para controlar
    # explicitamente o ciclo deste teste.
    cycle.presence_manager.process([
        neighbor(),
    ])

    result = cycle.presence_manager.process([])

    assert len(result) == 1
    assert result[0].event_type == PresenceEventType.DEVICE_OFFLINE


def test_ip_change_is_discovered():
    monitor = FakeNetworkMonitor([
        neighbor(ip="10.0.69.197"),
    ])

    cycle = DiscoveryCycle(
        network_monitor=monitor,
    )

    first = cycle.run_once()

    assert len(first.discoveries) == 1
    assert first.discoveries[0].ip_changed is False

    monitor.neighbors = [
        neighbor(ip="10.0.69.198"),
    ]

    second = cycle.run_once()

    assert len(second.discoveries) == 1
    assert second.discoveries[0].ip_changed is True
    assert second.discoveries[0].ip == "10.0.69.198"


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

        database.DATABASE_PATH = database.Path(test_database)

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