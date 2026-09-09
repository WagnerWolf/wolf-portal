import inspect
import sys

from app.access_controller import AccessController
from app.access_policy import AccessDecision
from app.firewall_manager import FirewallManager
from app.models import DeviceStatus


MAC = "40:FF:A1:20:EB:92"


def make_controller():
    firewall = FirewallManager()

    controller = AccessController(
        firewall=firewall,
    )

    return controller, firewall


def test_pending_is_denied():
    controller, firewall = make_controller()

    decision = controller.apply(
        DeviceStatus.PENDING,
        MAC,
    )

    assert decision == AccessDecision.DENY
    assert firewall.is_authorized(MAC) is False


def test_authorized_is_allowed():
    controller, firewall = make_controller()

    decision = controller.apply(
        DeviceStatus.AUTHORIZED,
        MAC,
    )

    assert decision == AccessDecision.ALLOW
    assert firewall.is_authorized(MAC) is True


def test_blocked_is_denied():
    controller, firewall = make_controller()

    firewall.authorize(MAC)

    decision = controller.apply(
        DeviceStatus.BLOCKED,
        MAC,
    )

    assert decision == AccessDecision.DENY
    assert firewall.is_authorized(MAC) is False


def test_disabled_is_denied():
    controller, firewall = make_controller()

    firewall.authorize(MAC)

    decision = controller.apply(
        DeviceStatus.DISABLED,
        MAC,
    )

    assert decision == AccessDecision.DENY
    assert firewall.is_authorized(MAC) is False


def test_reapplying_authorized_is_idempotent():
    controller, firewall = make_controller()

    controller.apply(
        DeviceStatus.AUTHORIZED,
        MAC,
    )

    controller.apply(
        DeviceStatus.AUTHORIZED,
        MAC,
    )

    assert firewall.list_authorized() == [
        "40:ff:a1:20:eb:92"
    ]


def test_reapplying_denied_is_idempotent():
    controller, firewall = make_controller()

    controller.apply(
        DeviceStatus.PENDING,
        MAC,
    )

    controller.apply(
        DeviceStatus.PENDING,
        MAC,
    )

    assert firewall.list_authorized() == []


def test_status_transition_is_applied():
    controller, firewall = make_controller()

    controller.apply(
        DeviceStatus.AUTHORIZED,
        MAC,
    )

    assert firewall.is_authorized(MAC) is True

    controller.apply(
        DeviceStatus.BLOCKED,
        MAC,
    )

    assert firewall.is_authorized(MAC) is False

    controller.apply(
        DeviceStatus.AUTHORIZED,
        MAC,
    )

    assert firewall.is_authorized(MAC) is True


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