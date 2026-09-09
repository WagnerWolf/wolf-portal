import inspect
import subprocess
import sys

from app.nftables_rules import (
    NftRule,
    NftablesRules,
)


ADMIN = "70:08:10:b3:3f:71"
PHONE = "40:ff:a1:20:eb:92"
OTHER = "aa:bb:cc:dd:ee:ff"


def get_chain_block(
    ruleset: str,
    chain: str,
) -> str:
    marker = f"chain {chain} {{"

    assert marker in ruleset

    return (
        ruleset.split(
            marker,
            1,
        )[1]
        .split(
            "}",
            1,
        )[0]
    )


def get_set_block(
    ruleset: str,
    set_name: str,
) -> str:
    marker = f"set {set_name} {{"

    assert marker in ruleset

    return (
        ruleset.split(
            marker,
            1,
        )[1]
        .split(
            "}",
            1,
        )[0]
    )


# ====================================================================
# ESTADO INICIAL
# ====================================================================

def test_new_rules_has_no_authorized_macs():
    rules = NftablesRules()

    assert rules.authorized_macs == set()


def test_new_rules_has_no_blocked_macs():
    rules = NftablesRules()

    assert rules.blocked_macs == set()


# ====================================================================
# AUTORIZADOS
# ====================================================================

def test_add_authorized_mac():
    rules = NftablesRules()

    rules.add_authorized_mac(OTHER)

    assert OTHER in rules.authorized_macs


def test_authorized_mac_is_normalized():
    rules = NftablesRules()

    rules.add_authorized_mac(
        "AA:BB:CC:DD:EE:FF"
    )

    assert OTHER in rules.authorized_macs


def test_add_authorized_twice_is_idempotent():
    rules = NftablesRules()

    rules.add_authorized_mac(OTHER)
    rules.add_authorized_mac(OTHER)

    assert rules.authorized_macs == {
        OTHER
    }


def test_remove_authorized_mac():
    rules = NftablesRules()

    rules.add_authorized_mac(OTHER)
    rules.remove_authorized_mac(OTHER)

    assert OTHER not in rules.authorized_macs


def test_remove_unknown_authorized_mac_does_not_fail():
    rules = NftablesRules()

    rules.remove_authorized_mac(OTHER)

    assert rules.authorized_macs == set()


# ====================================================================
# BLOQUEADOS
# ====================================================================

def test_add_blocked_mac():
    rules = NftablesRules()

    rules.add_blocked_mac(PHONE)

    assert PHONE in rules.blocked_macs


def test_blocked_mac_is_normalized():
    rules = NftablesRules()

    rules.add_blocked_mac(
        "40:FF:A1:20:EB:92"
    )

    assert PHONE in rules.blocked_macs


def test_failsafe_mac_cannot_be_blocked():
    rules = NftablesRules()

    rules.add_blocked_mac(ADMIN)

    assert ADMIN not in rules.blocked_macs


def test_authorizing_removes_mac_from_blocked():
    rules = NftablesRules()

    rules.add_blocked_mac(PHONE)

    assert PHONE in rules.blocked_macs

    rules.add_authorized_mac(PHONE)

    assert PHONE in rules.authorized_macs
    assert PHONE not in rules.blocked_macs


def test_blocking_removes_mac_from_authorized():
    rules = NftablesRules()

    rules.add_authorized_mac(PHONE)

    assert PHONE in rules.authorized_macs

    rules.add_blocked_mac(PHONE)

    assert PHONE not in rules.authorized_macs
    assert PHONE in rules.blocked_macs


def test_clear_removes_all_dynamic_macs():
    rules = NftablesRules()

    rules.add_authorized_mac(OTHER)
    rules.add_blocked_mac(PHONE)

    rules.clear()

    assert rules.authorized_macs == set()
    assert rules.blocked_macs == set()


# ====================================================================
# REGRAS LÓGICAS
# ====================================================================

def test_failsafe_rule_is_accept():
    rules = NftablesRules()

    rule = rules.build_failsafe_rule()

    assert isinstance(
        rule,
        NftRule,
    )

    assert (
        rule.chain
        == "wolf_portal_forward"
    )

    assert ADMIN in rule.expression

    assert rule.action == "accept"


def test_authorized_rule_uses_authorized_set():
    rules = NftablesRules()

    rule = rules.build_authorized_rule()

    assert (
        rule.chain
        == "wolf_portal_forward"
    )

    assert (
        "@wolf_portal_authorized_macs"
        in rule.expression
    )

    assert rule.action == "accept"


def test_block_rule_uses_blocked_set():
    rules = NftablesRules()

    rule = rules.build_block_rule()

    assert (
        rule.chain
        == "wolf_portal_forward"
    )

    assert (
        'iifname "br-lan"'
        in rule.expression
    )

    assert (
        "@wolf_portal_blocked_macs"
        in rule.expression
    )

    assert rule.action == "drop"


# ====================================================================
# REGRA LÓGICA DO CAPTIVE PORTAL
# ====================================================================

def test_http_redirect_rule_uses_prerouting_chain():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert isinstance(
        rule,
        NftRule,
    )

    assert (
        rule.chain
        == "wolf_portal_prerouting"
    )


def test_http_redirect_rule_is_ipv4_only():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert (
        "meta nfproto ipv4"
        in rule.expression
    )


def test_http_redirect_rule_uses_lan_interface():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert (
        'iifname "br-lan"'
        in rule.expression
    )


def test_http_redirect_rule_uses_blocked_set():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert (
        "@wolf_portal_blocked_macs"
        in rule.expression
    )

    assert (
        "@wolf_portal_authorized_macs"
        not in rule.expression
    )


def test_http_redirect_rule_targets_port_80():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert (
        "tcp dport 80"
        in rule.expression
    )


def test_http_redirect_rule_redirects_to_port_81():
    rules = NftablesRules()

    rule = (
        rules.build_http_redirect_rule()
    )

    assert (
        rule.action
        == "redirect to :81"
    )


# ====================================================================
# GERAÇÃO DO FRAGMENTO
# ====================================================================

def test_generated_ruleset_is_fw4_fragment():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "table inet wolf_portal"
        not in generated
    )

    assert (
        "table inet fw4"
        not in generated
    )

    assert (
        "chain wolf_portal_prerouting"
        in generated
    )

    assert (
        "chain wolf_portal_input"
        in generated
    )

    assert (
        "chain wolf_portal_forward"
        in generated
    )


def test_generated_ruleset_contains_prerouting_chain():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "chain wolf_portal_prerouting {"
        in generated
    )


def test_generated_prerouting_is_nat_hook():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    prerouting = get_chain_block(
        generated,
        "wolf_portal_prerouting",
    )

    assert (
        "type nat hook prerouting "
        "priority dstnat - 1; policy accept;"
        in prerouting
    )


def test_generated_prerouting_redirects_http():
    rules = NftablesRules()

    rules.add_blocked_mac(
        PHONE
    )

    generated = (
        rules.generate_ruleset()
    )

    prerouting = get_chain_block(
        generated,
        "wolf_portal_prerouting",
    )

    expected = (
        'meta nfproto ipv4 '
        'iifname "br-lan" '
        'ether saddr @wolf_portal_blocked_macs '
        'tcp dport 80 '
        'counter redirect to :81'
    )

    assert expected in prerouting


def test_generated_http_redirect_is_ipv4_only():
    rules = NftablesRules()

    rules.add_blocked_mac(
        PHONE
    )

    generated = (
        rules.generate_ruleset()
    )

    prerouting = get_chain_block(
        generated,
        "wolf_portal_prerouting",
    )

    assert (
        "meta nfproto ipv4"
        in prerouting
    )

    assert (
        "meta nfproto ipv6"
        not in prerouting
    )


def test_generated_redirect_is_bound_to_blocked_set():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    for line in generated.splitlines():

        if "redirect" not in line:
            continue

        assert (
            "@wolf_portal_blocked_macs"
            in line
        ), (
            "Encontrado redirect não vinculado "
            "ao conjunto de bloqueados: "
            f"{line.strip()}"
        )


def test_generated_redirect_is_not_bound_to_authorized_set():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    prerouting = get_chain_block(
        generated,
        "wolf_portal_prerouting",
    )

    assert (
        "@wolf_portal_authorized_macs"
        not in prerouting
    )


def test_generated_redirect_is_not_bound_to_failsafe_set():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    prerouting = get_chain_block(
        generated,
        "wolf_portal_prerouting",
    )

    assert (
        "@wolf_portal_failsafe_macs"
        not in prerouting
    )


def test_authorized_device_is_not_in_redirect_target_set():
    rules = NftablesRules()

    rules.add_blocked_mac(
        PHONE
    )

    rules.add_authorized_mac(
        PHONE
    )

    generated = (
        rules.generate_ruleset()
    )

    blocked = get_set_block(
        generated,
        "wolf_portal_blocked_macs",
    )

    assert (
        PHONE
        not in blocked
    )


def test_failsafe_device_is_not_in_redirect_target_set():
    rules = NftablesRules()

    rules.add_blocked_mac(
        ADMIN
    )

    generated = (
        rules.generate_ruleset()
    )

    blocked = get_set_block(
        generated,
        "wolf_portal_blocked_macs",
    )

    assert (
        ADMIN
        not in blocked
    )


def test_no_generic_http_redirect_exists():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    for line in generated.splitlines():

        stripped = line.strip()

        if "redirect to :81" not in stripped:
            continue

        assert (
            "@wolf_portal_blocked_macs"
            in stripped
        )

        assert (
            'iifname "br-lan"'
            in stripped
        )

        assert (
            "tcp dport 80"
            in stripped
        )


def test_https_is_not_redirected_to_portal():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    for line in generated.splitlines():

        if "redirect" not in line:
            continue

        assert (
            "tcp dport 443"
            not in line
        )


# ====================================================================
# SETS GERADOS
# ====================================================================

def test_generated_ruleset_contains_failsafe():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "set wolf_portal_failsafe_macs"
        in generated
    )

    assert ADMIN in generated


def test_generated_ruleset_contains_authorized_mac():
    rules = NftablesRules()

    rules.add_authorized_mac(
        OTHER
    )

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "set wolf_portal_authorized_macs"
        in generated
    )

    assert OTHER in generated


def test_generated_ruleset_contains_blocked_mac():
    rules = NftablesRules()

    rules.add_blocked_mac(
        PHONE
    )

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "set wolf_portal_blocked_macs"
        in generated
    )

    assert PHONE in generated


def test_generated_ruleset_never_blocks_admin():
    rules = NftablesRules()

    rules.add_blocked_mac(
        ADMIN
    )

    generated = (
        rules.generate_ruleset()
    )

    blocked_section = get_set_block(
        generated,
        "wolf_portal_blocked_macs",
    )

    assert (
        ADMIN
        not in blocked_section
    )


# ====================================================================
# POLÍTICAS DE SEGURANÇA
# ====================================================================

def test_generated_ruleset_uses_accept_policy():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "policy accept;"
        in generated
    )

    assert (
        "policy drop;"
        not in generated
    )


def test_generated_ruleset_has_three_accept_policies():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        generated.count(
            "policy accept;"
        )
        == 3
    )


def test_generated_ruleset_contains_no_native_fw4_chain():
    rules = NftablesRules()

    generated = (
        rules.generate_ruleset()
    )

    assert (
        "\nchain input {"
        not in generated
    )

    assert (
        "\nchain forward {"
        not in generated
    )

    assert (
        "\nchain output {"
        not in generated
    )

    assert (
        "\nchain prerouting {"
        not in generated
    )


# ====================================================================
# SINTAXE NFT
# ====================================================================

def test_generated_ruleset_is_valid_nft_syntax():
    rules = NftablesRules()

    rules.add_authorized_mac(
        OTHER
    )

    rules.add_blocked_mac(
        PHONE
    )

    generated = (
        rules.generate_ruleset()
    )

    wrapped = (
        "table inet wolf_portal_test_validation {\n"
        + generated
        + "\n}\n"
    )

    result = subprocess.run(
        [
            "nft",
            "-c",
            "-f",
            "-",
        ],
        input=wrapped,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise AssertionError(
            "Fragmento nftables inválido:\n"
            + result.stderr
        )


def run_tests():
    tests = [
        obj
        for name, obj in globals().items()
        if (
            name.startswith("test_")
            and inspect.isfunction(obj)
        )
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