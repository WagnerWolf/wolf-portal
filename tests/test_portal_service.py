import tempfile
from pathlib import Path

from app import database
from app.database import initialize_database
from app.models import DeviceStatus, EventType
from app.network_monitor import Neighbor, Presence
from app.portal_service import (
    AccessRequestResult,
    PortalService,
)


TEST_MAC = "40:ff:a1:20:eb:92"
TEST_IP = "10.0.69.197"


class FakeNetworkMonitor:
    def __init__(
        self,
        neighbors=None,
    ):
        self.neighbors = (
            neighbors
            if neighbors is not None
            else []
        )

    def get_neighbors(self):
        return list(
            self.neighbors
        )


def make_neighbor():
    return Neighbor(
        ip=TEST_IP,
        mac=TEST_MAC,
        state="REACHABLE",
        presence=Presence.PRESENT,
    )


def create_device(
    status=DeviceStatus.PENDING,
):
    with database.get_connection() as conn:
        now = "2026-09-09T00:00:00+00:00"

        conn.execute(
            """
            INSERT INTO devices (
                mac,
                hostname,
                ip,
                status,
                first_seen,
                last_seen,
                authorized_at,
                disabled_at,
                blocked_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                TEST_MAC,
                None,
                TEST_IP,
                status.value,
                now,
                now,
                now,
                now,
            ),
        )


def count_access_requests():
    with database.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM events
            WHERE event_type = ?
            """,
            (
                EventType.ACCESS_REQUESTED.value,
            ),
        ).fetchone()

        return row["total"]


def setup_database():
    tmpdir = tempfile.TemporaryDirectory()

    old_path = database.DATABASE_PATH

    database.DATABASE_PATH = (
        Path(tmpdir.name)
        / "wolf-portal-test.db"
    )

    initialize_database()

    return tmpdir, old_path


def restore_database(
    tmpdir,
    old_path,
):
    database.DATABASE_PATH = old_path
    tmpdir.cleanup()


def test_client_is_resolved():
    tmpdir, old_path = setup_database()

    try:
        create_device()

        service = PortalService(
            network_monitor=FakeNetworkMonitor(
                [make_neighbor()]
            )
        )

        client = service.identify_client(
            TEST_IP
        )

        assert client.identified
        assert client.mac == TEST_MAC
        assert client.ip == TEST_IP
        assert client.status == DeviceStatus.PENDING.value

    finally:
        restore_database(
            tmpdir,
            old_path,
        )


def test_pending_device_can_request_access():
    tmpdir, old_path = setup_database()

    try:
        create_device()

        service = PortalService(
            network_monitor=FakeNetworkMonitor(
                [make_neighbor()]
            ),
            request_cooldown_seconds=60,
        )

        result = service.request_access(
            TEST_IP
        )

        assert (
            result
            == AccessRequestResult.REQUEST_RECORDED
        )

        assert count_access_requests() == 1

    finally:
        restore_database(
            tmpdir,
            old_path,
        )


def test_duplicate_request_is_throttled():
    tmpdir, old_path = setup_database()

    try:
        create_device()

        service = PortalService(
            network_monitor=FakeNetworkMonitor(
                [make_neighbor()]
            ),
            request_cooldown_seconds=60,
        )

        first = service.request_access(
            TEST_IP
        )

        second = service.request_access(
            TEST_IP
        )

        assert (
            first
            == AccessRequestResult.REQUEST_RECORDED
        )

        assert (
            second
            == AccessRequestResult.ALREADY_REQUESTED
        )

        assert count_access_requests() == 1

    finally:
        restore_database(
            tmpdir,
            old_path,
        )


def test_authorized_device_cannot_create_request():
    tmpdir, old_path = setup_database()

    try:
        create_device(
            DeviceStatus.AUTHORIZED
        )

        service = PortalService(
            network_monitor=FakeNetworkMonitor(
                [make_neighbor()]
            )
        )

        result = service.request_access(
            TEST_IP
        )

        assert (
            result
            == AccessRequestResult.ALREADY_AUTHORIZED
        )

        assert count_access_requests() == 0

    finally:
        restore_database(
            tmpdir,
            old_path,
        )


def test_unknown_client_is_rejected():
    tmpdir, old_path = setup_database()

    try:
        service = PortalService(
            network_monitor=FakeNetworkMonitor(
                []
            )
        )

        result = service.request_access(
            TEST_IP
        )

        assert (
            result
            == AccessRequestResult.DEVICE_UNKNOWN
        )

    finally:
        restore_database(
            tmpdir,
            old_path,
        )


TESTS = [
    test_client_is_resolved,
    test_pending_device_can_request_access,
    test_duplicate_request_is_throttled,
    test_authorized_device_cannot_create_request,
    test_unknown_client_is_rejected,
]


def main():
    failures = 0

    for test in TESTS:
        try:
            test()

        except Exception as exc:
            failures += 1

            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: {exc!r}"
            )

        else:
            print(
                f"[PASS] {test.__name__}"
            )

    print()
    print(
        f"Testes: {len(TESTS)}"
    )
    print(
        f"Falhas: {failures}"
    )

    raise SystemExit(
        1 if failures else 0
    )


if __name__ == "__main__":
    main()