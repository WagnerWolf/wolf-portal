import inspect
import sys

from app.firewall_manager import FirewallManager


MAC = "40:FF:A1:20:EB:92"


def test_new_manager_has_no_authorized_devices():
    manager = FirewallManager()

    assert manager.list_authorized() == []


def test_authorize_adds_device():
    manager = FirewallManager()

    manager.authorize(MAC)

    assert manager.is_authorized(MAC) is True


def test_mac_is_normalized():
    manager = FirewallManager()

    manager.authorize("  40:FF:A1:20:EB:92  ")

    assert manager.is_authorized(
        "40:ff:a1:20:eb:92"
    ) is True


def test_authorize_twice_does_not_duplicate():
    manager = FirewallManager()

    manager.authorize(MAC)
    manager.authorize(MAC)

    assert manager.list_authorized() == [
        "40:ff:a1:20:eb:92"
    ]


def test_revoke_removes_device():
    manager = FirewallManager()

    manager.authorize(MAC)
    manager.revoke(MAC)

    assert manager.is_authorized(MAC) is False
    assert manager.list_authorized() == []


def test_revoke_unknown_device_does_not_fail():
    manager = FirewallManager()

    manager.revoke(MAC)

    assert manager.list_authorized() == []


def test_multiple_devices_are_kept():
    manager = FirewallManager()

    manager.authorize("AA:BB:CC:DD:EE:FF")
    manager.authorize("11:22:33:44:55:66")

    assert manager.list_authorized() == [
        "11:22:33:44:55:66",
        "aa:bb:cc:dd:ee:ff",
    ]


def test_clear_removes_all_devices():
    manager = FirewallManager()

    manager.authorize(MAC)
    manager.authorize("AA:BB:CC:DD:EE:FF")

    manager.clear()

    assert manager.list_authorized() == []


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
            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: {exc!r}"
            )

    print()
    print(f"Testes: {len(tests)}")
    print(f"Falhas: {failed}")

    sys.exit(1 if failed else 0)