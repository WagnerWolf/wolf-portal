from app.network_monitor import NetworkMonitor, Presence


def test_reachable_is_present():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.224 lladdr 70:08:10:b3:3f:71 REACHABLE"
    )

    assert neighbor.ip == "10.0.69.224"
    assert neighbor.mac == "70:08:10:b3:3f:71"
    assert neighbor.state == "REACHABLE"
    assert neighbor.presence == Presence.PRESENT


def test_delay_is_present():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.224 lladdr 70:08:10:b3:3f:71 DELAY"
    )

    assert neighbor.presence == Presence.PRESENT


def test_probe_is_present():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.69 lladdr 3e:cd:68:01:b6:17 PROBE"
    )

    assert neighbor.presence == Presence.PRESENT


def test_stale_is_unknown():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.197 lladdr 40:ff:a1:20:eb:92 STALE"
    )

    assert neighbor.ip == "10.0.69.197"
    assert neighbor.mac == "40:ff:a1:20:eb:92"
    assert neighbor.presence == Presence.UNKNOWN


def test_failed_is_absent():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.197 lladdr 40:ff:a1:20:eb:92 FAILED"
    )

    assert neighbor.presence == Presence.ABSENT


def test_failed_without_mac_is_parsed():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.197 FAILED"
    )

    assert neighbor.ip == "10.0.69.197"
    assert neighbor.mac == ""
    assert neighbor.presence == Presence.ABSENT


def test_mac_is_normalized():
    neighbor = NetworkMonitor._parse_line(
        "10.0.69.224 lladdr 70:08:10:B3:3F:71 REACHABLE"
    )

    assert neighbor.mac == "70:08:10:b3:3f:71"
