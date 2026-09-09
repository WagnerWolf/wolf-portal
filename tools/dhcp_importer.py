import re
from pathlib import Path

from app.database import get_connection
from app.device_manager import normalize_mac, now
from app.models import EventType


DHCP_CONFIG = Path("/etc/config/dhcp")


def parse_dhcp_hosts(path=DHCP_CONFIG):
    """
    Lê as reservas DHCP estáticas de /etc/config/dhcp.

    Esta função é somente leitura.
    Nenhuma alteração é feita no arquivo.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    content = path.read_text(encoding="utf-8")

    hosts = []
    current = None

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if line == "config host":
            if current is not None:
                hosts.append(current)

            current = {}
            continue

        if current is None:
            continue

        match = re.match(
            r"^(?:option|list)\s+(\S+)\s+'([^']*)'",
            line,
        )

        if not match:
            continue

        key, value = match.groups()

        if key in {"name", "ip", "mac"}:
            current[key] = value

    if current is not None:
        hosts.append(current)

    result = []

    for host in hosts:
        if "mac" not in host:
            continue

        result.append(
            {
                "name": host.get("name"),
                "ip": host.get("ip"),
                "mac": normalize_mac(host["mac"]),
            }
        )

    return result


def import_dhcp_hosts(path=DHCP_CONFIG):
    """
    Importa reservas DHCP existentes para o banco.

    Dispositivos já existentes não são duplicados.

    O arquivo /etc/config/dhcp nunca é modificado.
    """

    hosts = parse_dhcp_hosts(path)

    imported = []
    existing = []

    with get_connection() as conn:

        for host in hosts:

            mac = host["mac"]

            device = conn.execute(
                """
                SELECT *
                FROM devices
                WHERE mac = ?
                """,
                (mac,),
            ).fetchone()

            if device is not None:
                existing.append(device)
                continue

            timestamp = now()

            cursor = conn.execute(
                """
                INSERT INTO devices (
                    mac,
                    hostname,
                    ip,
                    status,
                    first_seen,
                    last_seen,
                    authorized_at,
                    disabled_at,
                    blocked_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mac,
                    host["name"],
                    host["ip"],
                    "AUTHORIZED",
                    timestamp,
                    timestamp,
                    timestamp,
                    None,
                    None,
                    timestamp,
                    timestamp,
                ),
            )

            device_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO events (
                    device_id,
                    timestamp,
                    event_type,
                    old_status,
                    new_status,
                    details,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    timestamp,
                    EventType.DEVICE_IMPORTED.value,
                    None,
                    "AUTHORIZED",
                    (
                        "Dispositivo importado da reserva DHCP: "
                        f"{host['name'] or '(sem hostname)'} "
                        f"({mac})"
                    ),
                    "dhcp",
                ),
            )

            device = conn.execute(
                """
                SELECT *
                FROM devices
                WHERE id = ?
                """,
                (device_id,),
            ).fetchone()

            imported.append(device)

    return {
        "imported": imported,
        "existing": existing,
        "total": len(hosts),
    }


if __name__ == "__main__":
    result = import_dhcp_hosts()

    print("=== IMPORTAÇÃO DHCP ===")
    print(f"Reservas encontradas: {result['total']}")
    print(f"Novos dispositivos:   {len(result['imported'])}")
    print(f"Já existentes:        {len(result['existing'])}")

    print()

    for device in result["imported"]:
        print(
            f"[IMPORTADO] "
            f"{device['hostname'] or '(sem hostname)'} | "
            f"{device['mac']} | "
            f"{device['ip']} | "
            f"{device['status']}"
        )

    for device in result["existing"]:
        print(
            f"[EXISTENTE] "
            f"{device['hostname'] or '(sem hostname)'} | "
            f"{device['mac']} | "
            f"{device['ip']} | "
            f"{device['status']}"
        )