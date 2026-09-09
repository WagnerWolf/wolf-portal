from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.database import get_connection
from app.models import DeviceStatus, EventType
from app.network_monitor import NetworkMonitor


class AccessRequestResult(str, Enum):
    REQUEST_RECORDED = "REQUEST_RECORDED"
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    ALREADY_AUTHORIZED = "ALREADY_AUTHORIZED"
    BLOCKED = "BLOCKED"
    DISABLED = "DISABLED"
    DEVICE_UNKNOWN = "DEVICE_UNKNOWN"


@dataclass(frozen=True)
class PortalClient:
    ip: str
    mac: str | None
    device_id: int | None
    hostname: str | None
    status: str | None

    @property
    def identified(self) -> bool:
        return (
            self.mac is not None
            and self.device_id is not None
            and self.status is not None
        )


class PortalService:
    """
    Camada de negócio da página pública do Wolf Portal.

    Responsabilidades:

        IP remoto
            ↓
        tabela neighbor do Linux
            ↓
        MAC
            ↓
        banco SQLite
            ↓
        estado do dispositivo

    A página pública NÃO:

        - recebe MAC informado pelo navegador;
        - autoriza dispositivos;
        - altera nftables;
        - altera status do dispositivo.

    Um cliente PENDING pode somente registrar
    ACCESS_REQUESTED.
    """

    DEFAULT_REQUEST_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        network_monitor: NetworkMonitor | None = None,
        request_cooldown_seconds: int = DEFAULT_REQUEST_COOLDOWN_SECONDS,
    ):
        if request_cooldown_seconds < 0:
            raise ValueError(
                "request_cooldown_seconds deve ser >= 0"
            )

        self.network_monitor = (
            network_monitor
            if network_monitor is not None
            else NetworkMonitor()
        )

        self.request_cooldown_seconds = (
            request_cooldown_seconds
        )

    # ================================================================
    # IP -> MAC
    # ================================================================

    def _find_mac_by_ip(
        self,
        ip: str,
    ) -> str | None:
        """
        Procura o IP na tabela neighbor da interface LAN.

        Não importa se a entrada está REACHABLE, STALE etc.;
        para o portal precisamos apenas que ela possua MAC.
        """

        for neighbor in self.network_monitor.get_neighbors():
            if (
                neighbor.ip == ip
                and neighbor.mac
            ):
                return neighbor.mac.lower()

        return None

    # ================================================================
    # Identificação
    # ================================================================

    def identify_client(
        self,
        ip: str,
    ) -> PortalClient:

        mac = self._find_mac_by_ip(ip)

        if mac is None:
            return PortalClient(
                ip=ip,
                mac=None,
                device_id=None,
                hostname=None,
                status=None,
            )

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    mac,
                    hostname,
                    ip,
                    status
                FROM devices
                WHERE lower(mac) = ?
                """,
                (mac,),
            ).fetchone()

        if row is None:
            return PortalClient(
                ip=ip,
                mac=mac,
                device_id=None,
                hostname=None,
                status=None,
            )

        return PortalClient(
            ip=ip,
            mac=row["mac"],
            device_id=row["id"],
            hostname=row["hostname"],
            status=row["status"],
        )

    # ================================================================
    # Cooldown
    # ================================================================

    @staticmethod
    def _parse_timestamp(
        value: str | None,
    ) -> datetime | None:

        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(value)

        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    def _request_is_in_cooldown(
        self,
        device_id: int,
    ) -> bool:

        if self.request_cooldown_seconds == 0:
            return False

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT timestamp
                FROM events
                WHERE
                    device_id = ?
                    AND event_type = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    device_id,
                    EventType.ACCESS_REQUESTED.value,
                ),
            ).fetchone()

        if row is None:
            return False

        timestamp = self._parse_timestamp(
            row["timestamp"]
        )

        if timestamp is None:
            return False

        age = (
            datetime.now(timezone.utc)
            - timestamp.astimezone(timezone.utc)
        ).total_seconds()

        return (
            0 <= age
            < self.request_cooldown_seconds
        )

    # ================================================================
    # Pedido de acesso
    # ================================================================

    def request_access(
        self,
        ip: str,
    ) -> AccessRequestResult:

        client = self.identify_client(ip)

        if not client.identified:
            return AccessRequestResult.DEVICE_UNKNOWN

        try:
            status = DeviceStatus(
                client.status
            )

        except ValueError:
            return AccessRequestResult.DEVICE_UNKNOWN

        if status == DeviceStatus.AUTHORIZED:
            return AccessRequestResult.ALREADY_AUTHORIZED

        if status == DeviceStatus.BLOCKED:
            return AccessRequestResult.BLOCKED

        if status == DeviceStatus.DISABLED:
            return AccessRequestResult.DISABLED

        if status != DeviceStatus.PENDING:
            return AccessRequestResult.DEVICE_UNKNOWN

        assert client.device_id is not None
        assert client.mac is not None

        if self._request_is_in_cooldown(
            client.device_id
        ):
            return AccessRequestResult.ALREADY_REQUESTED

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with get_connection() as conn:
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
                    client.device_id,
                    timestamp,
                    EventType.ACCESS_REQUESTED.value,
                    DeviceStatus.PENDING.value,
                    DeviceStatus.PENDING.value,
                    (
                        "Solicitação de acesso via portal. "
                        f"MAC={client.mac} IP={client.ip}"
                    ),
                    "portal",
                ),
            )

        return AccessRequestResult.REQUEST_RECORDED