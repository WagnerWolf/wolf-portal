import inspect
import sys

from app.nftables_controller import NftablesController


MAC = "40:ff:a1:20:eb:92"
MAC_UPPER = "40:FF:A1:20:EB:92"
MAC_2 = "70:08:10:b3:3f:71"


def test_new_controller_has_no_authorized_macs():
    controller = NftablesController()

    assert controller.authorized_macs == set()


def test_add_authorized_mac():
    controller = NftablesController()

    controller.add_authorized_mac(MAC)

    assert MAC in controller.authorized_macs


def test_mac_is_normalized():
    controller = NftablesController()

    controller.add_authorized_mac(MAC_UPPER)

    assert MAC in controller.authorized_macs
    assert MAC_UPPER not in controller.authorized_macs


def test_add_same_mac_is_idempotent():
    controller = NftablesController()

    controller.add_authorized_mac(MAC)
    controller.add_authorized_mac(MAC)

    assert controller.authorized_macs == {MAC}


def test_remove_authorized_mac():
    controller = NftablesController()

    controller.add_authorized_mac(MAC)
    controller.remove_authorized_mac(MAC)

    assert controller.authorized_macs == set()


def test_remove_unknown_mac_does_not_fail():
    controller = NftablesController()

    controller.remove_authorized_mac(MAC)

    assert controller.authorized_macs == set()


def test_multiple_authorized_macs_are_kept():
    controller = NftablesController()

    controller.add_authorized_mac(MAC)
    controller.add_authorized_mac(MAC_2)

    assert controller.authorized_macs == {
        MAC,
        MAC_2,
    }


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

    return failed


if __name__ == "__main__":
    failed = run_tests()
    sys.exit(1 if failed else 0)