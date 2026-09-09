import inspect
import sys
import tempfile

from contextlib import contextmanager
from pathlib import Path

import app.database as database

from app.database import initialize_database
from app import device_manager

from app.device_access_service import (
    DeviceAccessService,
    DeviceAccessSyncError,
)


MAC = "40:ff:a1:20:eb:92"


class SyncSpy:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def __call__(self):
        self.calls += 1

        if self.fail:
            raise RuntimeError(
                "Falha simulada no firewall"
            )

        return {
            "sync": self.calls
        }


@contextmanager
def temporary_database():
    original_path = database.DATABASE_PATH

    with tempfile.TemporaryDirectory() as temp_dir:

        database.DATABASE_PATH = (
            Path(temp_dir)
            / "wolf-portal-test.db"
        )

        initialize_database()

        try:
            yield

        finally:
            database.DATABASE_PATH = (
                original_path
            )


def create_device(
    mac=MAC,
):
    return device_manager.discover_device(
        mac=mac,
        ip="10.0.69.197",
        hostname="Teste",
    )


def test_new_device_triggers_firewall_sync():
    with temporary_database():

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        device = service.discover_device(
            mac=MAC,
            ip="10.0.69.197",
        )

        assert (
            device["status"]
            == "PENDING"
        )

        assert spy.calls == 1


def test_existing_device_does_not_reload_firewall():
    with temporary_database():

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        service.discover_device(
            mac=MAC,
            ip="10.0.69.197",
        )

        assert spy.calls == 1

        service.discover_device(
            mac=MAC,
            ip="10.0.69.198",
        )

        assert spy.calls == 1

        device = (
            device_manager.get_device(
                MAC
            )
        )

        assert (
            device["ip"]
            == "10.0.69.198"
        )


def test_authorize_device_updates_database_and_syncs():
    with temporary_database():

        create_device()

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        device = (
            service.authorize_device(
                MAC,
                source="test",
            )
        )

        assert (
            device["status"]
            == "AUTHORIZED"
        )

        assert spy.calls == 1


def test_block_device_updates_database_and_syncs():
    with temporary_database():

        create_device()

        device_manager.authorize_device(
            MAC
        )

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        device = (
            service.block_device(
                MAC,
                source="test",
            )
        )

        assert (
            device["status"]
            == "BLOCKED"
        )

        assert spy.calls == 1


def test_disable_device_updates_database_and_syncs():
    with temporary_database():

        create_device()

        device_manager.authorize_device(
            MAC
        )

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        device = (
            service.disable_device(
                MAC,
                source="test",
            )
        )

        assert (
            device["status"]
            == "DISABLED"
        )

        assert spy.calls == 1


def test_reauthorize_device_updates_database_and_syncs():
    with temporary_database():

        create_device()

        device_manager.block_device(
            MAC
        )

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        device = (
            service.reauthorize_device(
                MAC,
                source="test",
            )
        )

        assert (
            device["status"]
            == "AUTHORIZED"
        )

        assert spy.calls == 1


def test_explicit_resync_calls_firewall():
    with temporary_database():

        spy = SyncSpy()

        service = DeviceAccessService(
            sync_callback=spy
        )

        result = (
            service.resync_firewall()
        )

        assert spy.calls == 1

        assert result == {
            "sync": 1
        }


def test_firewall_failure_is_reported():
    with temporary_database():

        create_device()

        spy = SyncSpy()
        spy.fail = True

        service = DeviceAccessService(
            sync_callback=spy
        )

        try:
            service.authorize_device(
                MAC,
                source="test",
            )

        except DeviceAccessSyncError as exc:

            assert (
                exc.operation
                == "authorize_device"
            )

            assert (
                exc.mac
                == MAC
            )

        else:
            raise AssertionError(
                "DeviceAccessSyncError esperado."
            )

        # O banco continua sendo a fonte da verdade.
        #
        # Mesmo se a aplicação do firewall falhar, a alteração
        # persistida não é escondida do restante do sistema.
        device = (
            device_manager.get_device(
                MAC
            )
        )

        assert (
            device["status"]
            == "AUTHORIZED"
        )

        assert spy.calls == 1


def run_tests():
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

            print(
                f"[PASS] {test.__name__}"
            )

        except Exception as exc:
            failed += 1

            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: "
                f"{exc!r}"
            )

    print()
    print(
        f"Testes: {len(tests)}"
    )
    print(
        f"Falhas: {failed}"
    )

    return failed


if __name__ == "__main__":
    sys.exit(
        run_tests()
    )
