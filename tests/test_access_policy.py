from app.access_policy import AccessDecision, AccessPolicy
from app.models import DeviceStatus


def test_pending_is_denied():
    policy = AccessPolicy()

    decision = policy.evaluate(DeviceStatus.PENDING)

    assert decision == AccessDecision.DENY


def test_authorized_is_allowed():
    policy = AccessPolicy()

    decision = policy.evaluate(DeviceStatus.AUTHORIZED)

    assert decision == AccessDecision.ALLOW


def test_blocked_is_denied():
    policy = AccessPolicy()

    decision = policy.evaluate(DeviceStatus.BLOCKED)

    assert decision == AccessDecision.DENY


def test_disabled_is_denied():
    policy = AccessPolicy()

    decision = policy.evaluate(DeviceStatus.DISABLED)

    assert decision == AccessDecision.DENY


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
            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: {exc!r}"
            )

    print()
    print(f"Testes: {len(tests)}")
    print(f"Falhas: {failed}")

    sys.exit(1 if failed else 0)
