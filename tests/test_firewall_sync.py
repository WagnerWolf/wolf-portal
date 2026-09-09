import inspect
import sys

from app.firewall_manager import (
    PROTECTED_ADMIN_MAC,
)
from app.firewall_sync import (
    FirewallSyncError,
    build_firewall_from_devices,
)


NORMAL_MAC = "40:ff:a1:20:eb:92"


def device(
    mac: str,
    status: str,
):
    return {
        "mac": mac,
        "status": status,
    }


def test_authorized_device_is_authorized():
    firewall = build_firewall_from_devices(
        [
            device(
                NORMAL_MAC,
                "AUTHORIZED",
            ),
        ]
    )

    assert firewall.is_authorized(
        NORMAL_MAC
    )

    assert not firewall.is_blocked(
        NORMAL_MAC
    )


def test_pending_device_is_blocked():
    firewall = build_firewall_from_devices(
        [
            device(
                NORMAL_MAC,
                "PENDING",
            ),
        ]
    )

    assert firewall.is_blocked(
        NORMAL_MAC
    )

    assert not firewall.is_authorized(
        NORMAL_MAC
    )


def test_blocked_device_is_blocked():
    firewall = build_firewall_from_devices(
        [
            device(
                NORMAL_MAC,
                "BLOCKED",
            ),
        ]
    )

    assert firewall.is_blocked(
        NORMAL_MAC
    )


def test_disabled_device_is_blocked():
    firewall = build_firewall_from_devices(
        [
            device(
                NORMAL_MAC,
                "DISABLED",
            ),
        ]
    )

    assert firewall.is_blocked(
        NORMAL_MAC
    )


def test_protected_admin_is_never_blocked():
    firewall = build_firewall_from_devices(
        [
            device(
                PROTECTED_ADMIN_MAC,
                "PENDING",
            ),
        ]
    )

    assert firewall.is_authorized(
        PROTECTED_ADMIN_MAC
    )

    assert not firewall.is_blocked(
        PROTECTED_ADMIN_MAC
    )


def test_protected_admin_disabled_is_still_safe():
    firewall = build_firewall_from_devices(
        [
            device(
                PROTECTED_ADMIN_MAC,
                "DISABLED",
            ),
        ]
    )

    assert firewall.is_authorized(
        PROTECTED_ADMIN_MAC
    )

    assert not firewall.is_blocked(
        PROTECTED_ADMIN_MAC
    )


def test_authorized_and_blocked_sets_are_exclusive():
    firewall = build_firewall_from_devices(
        [
            device(
                "00:11:22:33:44:55",
                "AUTHORIZED",
            ),
            device(
                "00:11:22:33:44:66",
                "PENDING",
            ),
        ]
    )

    authorized = set(
        firewall.list_authorized()
    )

    blocked = set(
        firewall.list_blocked()
    )

    assert authorized.isdisjoint(
        blocked
    )


def test_all_supported_statuses_are_accepted():
    firewall = build_firewall_from_devices(
        [
            device(
                "00:11:22:33:44:01",
                "AUTHORIZED",
            ),
            device(
                "00:11:22:33:44:02",
                "PENDING",
            ),
            device(
                "00:11:22:33:44:03",
                "BLOCKED",
            ),
            device(
                "00:11:22:33:44:04",
                "DISABLED",
            ),
        ]
    )

    assert firewall.is_authorized(
        "00:11:22:33:44:01"
    )

    assert firewall.is_blocked(
        "00:11:22:33:44:02"
    )

    assert firewall.is_blocked(
        "00:11:22:33:44:03"
    )

    assert firewall.is_blocked(
        "00:11:22:33:44:04"
    )


def test_unknown_status_is_rejected():
    try:
        build_firewall_from_devices(
            [
                device(
                    NORMAL_MAC,
                    "QUALQUER_COISA",
                ),
            ]
        )

    except FirewallSyncError:
        return

    raise AssertionError(
        "Status desconhecido deveria gerar "
        "FirewallSyncError."
    )


def test_empty_device_list_is_fail_open():
    firewall = (
        build_firewall_from_devices(
            []
        )
    )

    assert (
        firewall.list_blocked()
        == []
    )

    assert (
        firewall.list_authorized()
        == []
    )


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
