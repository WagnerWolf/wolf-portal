from app.nftables_rules import NftablesRules


MAC1 = "AA:BB:CC:DD:EE:01"
MAC2 = "AA:BB:CC:DD:EE:02"


def test_empty_ruleset_is_valid():
    rules = NftablesRules()

    ruleset = rules.generate_ruleset()

    assert "table inet wolf_portal" in ruleset
    assert "set authorized_macs" in ruleset
    assert "type ether_addr" in ruleset


def test_authorized_macs_are_present():
    rules = NftablesRules()

    rules.add_authorized_mac(MAC1)
    rules.add_authorized_mac(MAC2)

    ruleset = rules.generate_ruleset()

    assert MAC1.lower() in ruleset
    assert MAC2.lower() in ruleset


def test_authorized_set_is_generated():
    rules = NftablesRules()

    rules.add_authorized_mac(MAC1)

    ruleset = rules.generate_ruleset()

    assert "authorized_macs" in ruleset
    assert "ether saddr @authorized_macs" in ruleset


def test_ruleset_contains_forward_chain():
    rules = NftablesRules()

    ruleset = rules.generate_ruleset()

    assert "chain forward" in ruleset


def test_ruleset_contains_input_chain():
    rules = NftablesRules()

    ruleset = rules.generate_ruleset()

    assert "chain input" in ruleset


def test_ruleset_is_valid_nft_syntax():
    import subprocess

    rules = NftablesRules()

    rules.add_authorized_mac(MAC1)

    ruleset = rules.generate_ruleset()

    result = subprocess.run(
        ["nft", "-c", "-f", "-"],
        input=ruleset,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, (
        f"Ruleset inválido:\n"
        f"{result.stderr}\n\n"
        f"Ruleset:\n{ruleset}"
    )


if __name__ == "__main__":
    tests = [
        test_empty_ruleset_is_valid,
        test_authorized_macs_are_present,
        test_authorized_set_is_generated,
        test_ruleset_contains_forward_chain,
        test_ruleset_contains_input_chain,
        test_ruleset_is_valid_nft_syntax,
    ]

    failures = 0

    for test in tests:
        try:
            test()
            print(f"[PASS] {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {test.__name__}: {exc!r}")

    print()
    print(f"Testes: {len(tests)}")
    print(f"Falhas: {failures}")

    raise SystemExit(1 if failures else 0)
