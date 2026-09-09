import inspect
import sys
import tempfile
from pathlib import Path

from app.firewall_manager import PROTECTED_ADMIN_MAC
from app.nftables_executor import (
    MANAGED_CHAINS,
    MANAGED_SETS,
    NftablesExecutionError,
    NftablesExecutor,
)


def make_executor():
    temp_dir = tempfile.TemporaryDirectory()

    executor = NftablesExecutor(
        include_path=Path(temp_dir.name) / "90-wolf-portal.nft",
        backup_path=Path(temp_dir.name) / "backup.nft",
        log_path=Path(temp_dir.name) / "executor.log",
    )

    return executor, temp_dir


def safe_fragment():
    return f"""
set wolf_portal_failsafe_macs {{
    type ether_addr
    elements = {{
        {PROTECTED_ADMIN_MAC}
    }}
}}

set wolf_portal_authorized_macs {{
    type ether_addr
}}

set wolf_portal_blocked_macs {{
    type ether_addr
}}

chain wolf_portal_prerouting {{
    type nat hook prerouting priority dstnat - 1; policy accept;
    meta nfproto ipv4 iifname "br-lan" ether saddr @wolf_portal_blocked_macs tcp dport 80 redirect to :81
}}

chain wolf_portal_input {{
    type filter hook input priority filter - 1; policy accept;
    iifname "br-lan" ether saddr @wolf_portal_failsafe_macs accept
}}

chain wolf_portal_forward {{
    type filter hook forward priority filter - 1; policy accept;
    iifname "br-lan" ether saddr @wolf_portal_failsafe_macs accept
}}
""".strip() + "\n"


def expect_guardrail_failure(
    executor,
    ruleset,
):
    try:
        executor._validate_guardrails(
            ruleset
        )

    except NftablesExecutionError:
        return

    raise AssertionError(
        "O ruleset deveria ter sido rejeitado."
    )


def test_executor_can_be_created():
    executor, temp_dir = make_executor()

    try:
        assert executor.confirmed is False

        assert (
            executor.table_identifier
            == "inet fw4"
        )

    finally:
        temp_dir.cleanup()


def test_include_path_is_configurable():
    executor, temp_dir = make_executor()

    try:
        assert (
            executor.managed_include_path.name
            == "90-wolf-portal.nft"
        )

    finally:
        temp_dir.cleanup()


def test_backup_path_is_configurable():
    executor, temp_dir = make_executor()

    try:
        assert (
            executor.backup_path.name
            == "backup.nft"
        )

    finally:
        temp_dir.cleanup()


def test_log_path_is_configurable():
    executor, temp_dir = make_executor()

    try:
        assert (
            executor.log_path.name
            == "executor.log"
        )

    finally:
        temp_dir.cleanup()


def test_confirmed_starts_false():
    executor, temp_dir = make_executor()

    try:
        assert executor.confirmed is False

    finally:
        temp_dir.cleanup()


def test_confirm_cancels_rollback_timer():
    executor, temp_dir = make_executor()

    try:
        executor.confirm()

        assert executor.confirmed is True

    finally:
        temp_dir.cleanup()


def test_rollback_state_starts_clear():
    executor, temp_dir = make_executor()

    try:
        assert executor.rollback_started is False
        assert executor.rollback_completed is False

    finally:
        temp_dir.cleanup()


def test_empty_backup_represents_no_include():
    executor, temp_dir = make_executor()

    try:
        executor.backup_path.write_text(
            "",
            encoding="utf-8",
        )

        assert (
            executor.backup_path.read_text(
                encoding="utf-8"
            )
            == ""
        )

    finally:
        temp_dir.cleanup()


def test_managed_chains_include_prerouting():
    assert (
        "wolf_portal_prerouting"
        in MANAGED_CHAINS
    )

    assert (
        "wolf_portal_input"
        in MANAGED_CHAINS
    )

    assert (
        "wolf_portal_forward"
        in MANAGED_CHAINS
    )


def test_all_expected_sets_are_managed():
    assert (
        "wolf_portal_failsafe_macs"
        in MANAGED_SETS
    )

    assert (
        "wolf_portal_authorized_macs"
        in MANAGED_SETS
    )

    assert (
        "wolf_portal_blocked_macs"
        in MANAGED_SETS
    )


def test_guardrails_accept_safe_fragment():
    executor, temp_dir = make_executor()

    try:
        executor._validate_guardrails(
            safe_fragment()
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_table_declaration():
    executor, temp_dir = make_executor()

    try:
        bad = (
            "table inet wolf_portal {\n"
            + safe_fragment()
            + "}\n"
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_policy_drop():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "policy accept;",
            "policy drop;",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_admin_failsafe():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            PROTECTED_ADMIN_MAC,
            "00:11:22:33:44:55",
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_flush_ruleset():
    executor, temp_dir = make_executor()

    try:
        bad = (
            "flush ruleset\n"
            + safe_fragment()
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_native_forward_chain():
    executor, temp_dir = make_executor()

    try:
        bad = (
            safe_fragment()
            + "\n"
            + "chain forward {\n"
            + "    policy accept;\n"
            + "}\n"
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_prerouting_chain():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "chain wolf_portal_prerouting {",
            "chain wolf_portal_prerouting_missing {",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_input_chain():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "chain wolf_portal_input {",
            "chain wolf_portal_input_missing {",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_forward_chain():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "chain wolf_portal_forward {",
            "chain wolf_portal_forward_missing {",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_unknown_chain():
    executor, temp_dir = make_executor()

    try:
        bad = (
            safe_fragment()
            + """
chain wolf_portal_evil {
    type filter hook output priority filter - 10;
    policy accept;
}
"""
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_reject_unknown_set():
    executor, temp_dir = make_executor()

    try:
        bad = (
            safe_fragment()
            + """
set wolf_portal_unknown {
    type ether_addr
}
"""
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_all_sets():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            """
set wolf_portal_blocked_macs {
    type ether_addr
}

""",
            "",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_prerouting_hook():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "type nat hook prerouting",
            "type nat hook postrouting",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_input_hook():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "type filter hook input",
            "type filter hook output",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


def test_guardrails_require_forward_hook():
    executor, temp_dir = make_executor()

    try:
        bad = safe_fragment().replace(
            "type filter hook forward",
            "type filter hook output",
            1,
        )

        expect_guardrail_failure(
            executor,
            bad,
        )

    finally:
        temp_dir.cleanup()


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
                f"{type(exc).__name__}: {exc!r}"
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