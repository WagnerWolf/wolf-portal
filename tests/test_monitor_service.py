from types import SimpleNamespace

from app.monitor_service import MonitorService


# ====================================================================
# HELPERS
# ====================================================================

class FakeDiscoveryCycle:
    def __init__(
        self,
        results,
    ):
        self.results = list(
            results
        )

        self.calls = 0

    def run_once(
        self,
    ):
        self.calls += 1

        if not self.results:
            return SimpleNamespace(
                events=[],
                discoveries=[],
            )

        return self.results.pop(0)


def discovery_result(
    *,
    mac="40:ff:a1:20:eb:92",
    ip="10.0.69.197",
    status="PENDING",
    new_device=False,
):
    return SimpleNamespace(
        mac=mac,
        ip=ip,
        status=status,
        new_device=new_device,
        ip_changed=False,
    )


def cycle_result(
    *discoveries,
):
    return SimpleNamespace(
        events=[],
        discoveries=list(
            discoveries
        ),
    )


# ====================================================================
# TESTES
# ====================================================================

def test_existing_device_does_not_sync():
    sync_calls = []

    cycle = FakeDiscoveryCycle(
        [
            cycle_result(
                discovery_result(
                    new_device=False
                )
            )
        ]
    )

    service = MonitorService(
        discovery_cycle=cycle,
        sync_callback=lambda: sync_calls.append(
            True
        ),
    )

    service.run_once()

    assert sync_calls == []
    assert service.firewall_dirty is False


def test_new_device_triggers_sync():
    sync_calls = []

    cycle = FakeDiscoveryCycle(
        [
            cycle_result(
                discovery_result(
                    new_device=True
                )
            )
        ]
    )

    service = MonitorService(
        discovery_cycle=cycle,
        sync_callback=lambda: sync_calls.append(
            True
        ),
    )

    service.run_once()

    assert len(sync_calls) == 1
    assert service.firewall_dirty is False


def test_multiple_new_devices_trigger_single_sync():
    sync_calls = []

    cycle = FakeDiscoveryCycle(
        [
            cycle_result(
                discovery_result(
                    mac="10:10:10:10:10:10",
                    new_device=True,
                ),
                discovery_result(
                    mac="20:20:20:20:20:20",
                    new_device=True,
                ),
                discovery_result(
                    mac="30:30:30:30:30:30",
                    new_device=True,
                ),
            )
        ]
    )

    service = MonitorService(
        discovery_cycle=cycle,
        sync_callback=lambda: sync_calls.append(
            True
        ),
    )

    service.run_once()

    assert len(sync_calls) == 1
    assert service.firewall_dirty is False


def test_sync_failure_keeps_firewall_dirty():
    cycle = FakeDiscoveryCycle(
        [
            cycle_result(
                discovery_result(
                    new_device=True
                )
            )
        ]
    )

    def failing_sync():
        raise RuntimeError(
            "Falha simulada"
        )

    service = MonitorService(
        discovery_cycle=cycle,
        sync_callback=failing_sync,
    )

    try:
        service.run_once()

    except RuntimeError:
        pass

    else:
        raise AssertionError(
            "Era esperado RuntimeError."
        )

    assert service.firewall_dirty is True


def test_failed_sync_is_retried_next_cycle():
    sync_calls = []

    cycle = FakeDiscoveryCycle(
        [
            cycle_result(
                discovery_result(
                    new_device=True
                )
            ),
            cycle_result(
                discovery_result(
                    new_device=False
                )
            ),
        ]
    )

    def sync():
        sync_calls.append(
            True
        )

        if len(sync_calls) == 1:
            raise RuntimeError(
                "Falha simulada"
            )

    service = MonitorService(
        discovery_cycle=cycle,
        sync_callback=sync,
    )

    try:
        service.run_once()

    except RuntimeError:
        pass

    assert service.firewall_dirty is True
    assert len(sync_calls) == 1

    service.run_once()

    assert len(sync_calls) == 2
    assert service.firewall_dirty is False


def test_invalid_interval_is_rejected():
    try:
        MonitorService(
            interval_seconds=0
        )

    except ValueError:
        return

    raise AssertionError(
        "Intervalo zero deveria ser rejeitado."
    )


# ====================================================================
# RUNNER
# ====================================================================

TESTS = [
    test_existing_device_does_not_sync,
    test_new_device_triggers_sync,
    test_multiple_new_devices_trigger_single_sync,
    test_sync_failure_keeps_firewall_dirty,
    test_failed_sync_is_retried_next_cycle,
    test_invalid_interval_is_rejected,
]


if __name__ == "__main__":

    failures = 0

    for test in TESTS:

        try:
            test()

            print(
                f"[PASS] {test.__name__}"
            )

        except Exception as exc:

            failures += 1

            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: {exc}"
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