import inspect
import subprocess
import sys

from app.nftables_rules import (
    NftablesRules,
)


ADMIN = "70:08:10:b3:3f:71"
PHONE = "40:ff:a1:20:eb:92"
AUTHORIZED = "aa:bb:cc:dd:ee:ff"


def make_ruleset(
    *,
    authorized=None,
    blocked=None,
):
    rules = NftablesRules()

    for mac in authorized or []:
        rules.add_authorized_mac(
            mac
        )

    for mac in blocked or []:
        rules.add_blocked_mac(
            mac
        )

    return rules.generate_ruleset()


def assert_contains(
    ruleset: str,
    text: str,
    description: str,
):
    assert text in ruleset, (
        f"{description}: trecho não encontrado:\n"
        f"{text}"
    )


def get_chain_block(
    ruleset: str,
    chain: str,
) -> str:

    marker = (
        f"chain {chain} {{"
    )

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

    marker = (
        f"set {set_name} {{"
    )

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
# ARQUITETURA DO FRAGMENTO
# ====================================================================

def test_ruleset_is_fragment_not_table():
    ruleset = make_ruleset()

    assert (
        "table inet wolf_portal"
        not in ruleset
    )

    assert (
        "table inet fw4"
        not in ruleset
    )


def test_failsafe_set_is_generated():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "set wolf_portal_failsafe_macs",
        "set failsafe",
    )

    assert ADMIN in ruleset


def test_authorized_set_is_generated():
    ruleset = make_ruleset(
        authorized=[
            AUTHORIZED
        ]
    )

    assert_contains(
        ruleset,
        "set wolf_portal_authorized_macs",
        "set autorizados",
    )

    assert AUTHORIZED in ruleset


def test_blocked_set_is_generated():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        "set wolf_portal_blocked_macs",
        "set bloqueados",
    )

    assert PHONE in ruleset


# ====================================================================
# CHAINS
# ====================================================================

def test_ruleset_contains_prerouting_chain():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "chain wolf_portal_prerouting {",
        "chain prerouting Wolf Portal",
    )


def test_ruleset_contains_input_chain():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "chain wolf_portal_input {",
        "chain input Wolf Portal",
    )


def test_ruleset_contains_forward_chain():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "chain wolf_portal_forward {",
        "chain forward Wolf Portal",
    )


# ====================================================================
# POLICIES / HOOKS
# ====================================================================

def test_prerouting_policy_is_accept():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "type nat hook prerouting "
        "priority dstnat - 1; policy accept;",
        "policy PREROUTING",
    )


def test_input_policy_is_accept():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "type filter hook input "
        "priority filter - 1; policy accept;",
        "policy INPUT",
    )


def test_forward_policy_is_accept():
    ruleset = make_ruleset()

    assert_contains(
        ruleset,
        "type filter hook forward "
        "priority filter - 1; policy accept;",
        "policy FORWARD",
    )


def test_all_three_chains_are_fail_open():
    ruleset = make_ruleset()

    assert (
        ruleset.count(
            "policy accept;"
        )
        == 3
    )


def test_policy_drop_does_not_exist():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert (
        "policy drop;"
        not in ruleset
    )


# ====================================================================
# CAPTIVE PORTAL / INTERCEPTAÇÃO HTTP
# ====================================================================

def test_blocked_device_http_is_redirected():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'meta nfproto ipv4 '
        'iifname "br-lan" '
        'ether saddr @wolf_portal_blocked_macs '
        'tcp dport 80 '
        'counter redirect to :81',
        "redirect HTTP",
    )


def test_http_interception_is_ipv4_only():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    prerouting = get_chain_block(
        ruleset,
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


def test_http_interception_is_lan_only():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    prerouting = get_chain_block(
        ruleset,
        "wolf_portal_prerouting",
    )

    assert (
        'iifname "br-lan"'
        in prerouting
    )


def test_http_interception_targets_only_blocked_set():
    ruleset = make_ruleset(
        authorized=[
            AUTHORIZED
        ],
        blocked=[
            PHONE
        ],
    )

    prerouting = get_chain_block(
        ruleset,
        "wolf_portal_prerouting",
    )

    assert (
        "@wolf_portal_blocked_macs"
        in prerouting
    )

    assert (
        "@wolf_portal_authorized_macs"
        not in prerouting
    )

    assert (
        "@wolf_portal_failsafe_macs"
        not in prerouting
    )


def test_no_generic_http_redirect_exists():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    redirect_lines = [
        line.strip()
        for line in ruleset.splitlines()
        if "redirect" in line
    ]

    assert (
        len(redirect_lines)
        == 1
    )

    redirect = (
        redirect_lines[0]
    )

    assert (
        "@wolf_portal_blocked_macs"
        in redirect
    )

    assert (
        'iifname "br-lan"'
        in redirect
    )

    assert (
        "tcp dport 80"
        in redirect
    )


def test_https_is_not_redirected():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    for line in ruleset.splitlines():

        if "redirect" not in line:
            continue

        assert (
            "tcp dport 443"
            not in line
        )


def test_authorized_device_cannot_be_in_redirect_set():
    rules = NftablesRules()

    rules.add_blocked_mac(
        AUTHORIZED
    )

    rules.add_authorized_mac(
        AUTHORIZED
    )

    ruleset = (
        rules.generate_ruleset()
    )

    blocked_set = get_set_block(
        ruleset,
        "wolf_portal_blocked_macs",
    )

    assert (
        AUTHORIZED
        not in blocked_set
    )


def test_admin_cannot_be_in_redirect_set():
    rules = NftablesRules()

    rules.add_blocked_mac(
        ADMIN
    )

    ruleset = (
        rules.generate_ruleset()
    )

    blocked_set = get_set_block(
        ruleset,
        "wolf_portal_blocked_macs",
    )

    assert (
        ADMIN
        not in blocked_set
    )


# ====================================================================
# INPUT LOCAL
# ====================================================================

def test_blocked_device_can_use_dns_udp():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'iifname "br-lan" '
        "ether saddr @wolf_portal_blocked_macs "
        "udp dport 53 "
        "counter accept",
        "DNS UDP",
    )


def test_blocked_device_can_use_dns_tcp():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'iifname "br-lan" '
        "ether saddr @wolf_portal_blocked_macs "
        "tcp dport 53 "
        "counter accept",
        "DNS TCP",
    )


def test_blocked_device_can_access_portal():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'iifname "br-lan" '
        "ether saddr @wolf_portal_blocked_macs "
        "tcp dport 81 "
        "counter accept",
        "portal HTTP 81",
    )


def test_blocked_device_cannot_access_router_https():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'iifname "br-lan" '
        "ether saddr @wolf_portal_blocked_macs "
        "tcp dport 443 "
        "counter drop",
        "HTTPS administrativo",
    )


# ====================================================================
# FORWARD
# ====================================================================

def test_blocked_device_is_dropped_on_forward():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    assert_contains(
        ruleset,
        'iifname "br-lan" '
        "ether saddr @wolf_portal_blocked_macs "
        "counter drop",
        "DROP de forwarding",
    )


def test_no_generic_lan_drop_exists():
    ruleset = make_ruleset(
        blocked=[
            PHONE
        ]
    )

    for line in ruleset.splitlines():

        stripped = (
            line.strip()
        )

        if " drop" not in stripped:
            continue

        assert (
            "@wolf_portal_blocked_macs"
            in stripped
        ), (
            "Encontrado DROP não vinculado "
            "ao conjunto de bloqueados: "
            f"{stripped}"
        )


# ====================================================================
# EXCLUSIVIDADE DE ESTADO
# ====================================================================

def test_admin_cannot_enter_blocked_set():
    rules = NftablesRules()

    rules.add_blocked_mac(
        ADMIN
    )

    assert (
        ADMIN
        not in rules.blocked_macs
    )


def test_authorized_mac_is_removed_from_blocked():
    rules = NftablesRules()

    rules.add_blocked_mac(
        PHONE
    )

    assert (
        PHONE
        in rules.blocked_macs
    )

    rules.add_authorized_mac(
        PHONE
    )

    assert (
        PHONE
        in rules.authorized_macs
    )

    assert (
        PHONE
        not in rules.blocked_macs
    )


def test_blocked_mac_is_removed_from_authorized():
    rules = NftablesRules()

    rules.add_authorized_mac(
        PHONE
    )

    assert (
        PHONE
        in rules.authorized_macs
    )

    rules.add_blocked_mac(
        PHONE
    )

    assert (
        PHONE
        not in rules.authorized_macs
    )

    assert (
        PHONE
        in rules.blocked_macs
    )


# ====================================================================
# FAIL OPEN
# ====================================================================

def test_empty_dynamic_state_is_fail_open():
    ruleset = make_ruleset()

    # Agora existem três chains próprias:
    #
    #   prerouting
    #   input
    #   forward
    #
    # todas deliberadamente com policy ACCEPT.
    assert (
        ruleset.count(
            "policy accept;"
        )
        == 3
    )

    assert (
        "policy drop;"
        not in ruleset
    )

    blocked = get_set_block(
        ruleset,
        "wolf_portal_blocked_macs",
    )

    # Sem elementos no set, o redirect e os DROPs
    # não podem casar com nenhum dispositivo.
    assert (
        "elements"
        not in blocked
    )


# ====================================================================
# SEGURANÇA ESTRUTURAL
# ====================================================================

def test_no_native_fw4_chains_are_generated():
    ruleset = make_ruleset()

    assert (
        "\nchain input {"
        not in ruleset
    )

    assert (
        "\nchain forward {"
        not in ruleset
    )

    assert (
        "\nchain output {"
        not in ruleset
    )

    assert (
        "\nchain prerouting {"
        not in ruleset
    )


# ====================================================================
# SINTAXE NFT
# ====================================================================

def test_ruleset_is_valid_nft_syntax():
    ruleset = make_ruleset(
        authorized=[
            AUTHORIZED
        ],
        blocked=[
            PHONE
        ],
    )

    wrapped = (
        "table inet wolf_portal_policy_validation {\n"
        + ruleset
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
            "Ruleset inválido:\n"
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
                f"{exc}"
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