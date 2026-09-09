from dataclasses import dataclass
from typing import Optional

from app.database import get_connection
from app.network_monitor import Presence
from app.presence_manager import PresenceEvent, PresenceEventType


@dataclass
class DiscoveryResult:
    mac: str
    ip: Optional[str]
    device_id: int
    status: str
    new_device: bool
    ip_changed: bool


class DeviceDiscovery:
    """
    Conecta os eventos de presença ao cadastro persistente de dispositivos.

    Responsabilidades:
    - descobrir novos dispositivos;
    - criar dispositivos PENDING;
    - atualizar last_seen;
    - atualizar IP;
    - registrar mudanças relevantes no histórico.

    Não é responsável por:
    - autorizar;
    - bloquear;
    - desabilitar;
    - enviar Telegram;
    - configurar firewall.
    """

    def process_event(self, event: PresenceEvent) -> Optional[DiscoveryResult]:
        if event.event_type != PresenceEventType.DEVICE_ONLINE:
            return None

        if event.presence != Presence.PRESENT:
            return None

        return self._process_online(
            mac=event.mac,
            ip=event.ip,
        )

    def observe(
        self,
        mac: str,
        ip: Optional[str],
    ) -> DiscoveryResult:
        """
        Processa uma observação atual de um dispositivo presente.

        Diferentemente de process_event(), este método pode ser
        chamado em todos os ciclos em que o dispositivo estiver
        presente.

        Isso permite:
        - atualizar last_seen continuamente;
        - detectar mudança de IP;
        - descobrir novos dispositivos;
        - sem gerar eventos de presença duplicados.
        """
        return self._process_online(
            mac=mac,
            ip=ip,
        )
    
    def _process_online(
        self,
        mac: str,
        ip: Optional[str],
    ) -> DiscoveryResult:

        mac = mac.lower()

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM devices
                WHERE lower(mac) = ?
                """,
                (mac,),
            ).fetchone()

            if row is None:
                return self._create_device(
                    conn=conn,
                    mac=mac,
                    ip=ip,
                )

            return self._update_existing_device(
                conn=conn,
                row=row,
                ip=ip,
            )

    def _create_device(
        self,
        conn,
        mac: str,
        ip: Optional[str],
    ) -> DiscoveryResult:

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

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
            VALUES (?, ?, ?, 'PENDING', ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                mac,
                None,
                ip,
                now,
                now,
                now,
                now,
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
                now,
                "DEVICE_DETECTED",
                None,
                "PENDING",
                f"Novo dispositivo detectado: {mac}",
                "system",
            ),
        )

        return DiscoveryResult(
            mac=mac,
            ip=ip,
            device_id=device_id,
            status="PENDING",
            new_device=True,
            ip_changed=False,
        )

    def _update_existing_device(
    self,
    conn,
    row,
    ip: Optional[str],
) -> DiscoveryResult:

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        old_ip = row["ip"]

        ip_changed = (
            ip is not None
            and old_ip is not None
            and ip != old_ip
        )

        if ip is not None and ip != old_ip:
            new_ip = ip
        else:
            new_ip = old_ip

        conn.execute(
            """
            UPDATE devices
            SET
                ip = ?,
                last_seen = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_ip,
                now,
                now,
                row["id"],
            ),
        )

        if ip_changed:
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
                    row["id"],
                    now,
                    "IP_CHANGED",
                    row["status"],
                    row["status"],
                    f"IP alterado: {old_ip} -> {ip}",
                    "system",
                ),
            )

        return DiscoveryResult(
            mac=row["mac"],
            ip=new_ip,
            device_id=row["id"],
            status=row["status"],
            new_device=False,
            ip_changed=ip_changed,
    )