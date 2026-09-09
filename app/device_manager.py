from datetime import datetime, timezone
import sqlite3

from .database import get_connection
from .models import DeviceStatus, EventType


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_mac(mac: str) -> str:
    return mac.strip().lower()


def get_device(mac: str):
    mac = normalize_mac(mac)

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM devices
            WHERE mac = ?
            """,
            (mac,),
        ).fetchone()


def _create_event(
    conn,
    device_id: int,
    event_type: EventType,
    old_status=None,
    new_status=None,
    details=None,
    source="system",
):
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
            now(),
            event_type.value,
            old_status,
            new_status,
            details,
            source,
        ),
    )


def discover_device(
    mac: str,
    ip: str | None = None,
    hostname: str | None = None,
):
    """
    Registra ou atualiza um dispositivo detectado.

    Dispositivo novo sempre começa como PENDING.
    Nunca é autorizado automaticamente.
    """

    mac = normalize_mac(mac)
    timestamp = now()

    with get_connection() as conn:

        device = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE mac = ?
            """,
            (mac,),
        ).fetchone()

        if device is None:
            cursor = conn.execute(
                """
                INSERT INTO devices (
                    mac,
                    hostname,
                    ip,
                    status,
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mac,
                    hostname,
                    ip,
                    DeviceStatus.PENDING.value,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )

            device_id = cursor.lastrowid

            _create_event(
                conn,
                device_id,
                EventType.DEVICE_DETECTED,
                new_status=DeviceStatus.PENDING.value,
                details=f"Novo dispositivo detectado: {mac}",
            )

        else:
            device_id = device["id"]

            conn.execute(
                """
                UPDATE devices
                SET
                    ip = COALESCE(?, ip),
                    hostname = COALESCE(?, hostname),
                    last_seen = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    ip,
                    hostname,
                    timestamp,
                    timestamp,
                    device_id,
                ),
            )

        return conn.execute(
            """
            SELECT *
            FROM devices
            WHERE id = ?
            """,
            (device_id,),
        ).fetchone()


def _change_status(
    mac: str,
    new_status: DeviceStatus,
    event_type: EventType,
    source: str = "system",
    details: str | None = None,
):
    mac = normalize_mac(mac)

    with get_connection() as conn:

        device = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE mac = ?
            """,
            (mac,),
        ).fetchone()

        if device is None:
            raise ValueError(f"Dispositivo não encontrado: {mac}")

        old_status = device["status"]

        if old_status == new_status.value:
            return device

        timestamp = now()

        authorized_at = device["authorized_at"]
        disabled_at = device["disabled_at"]
        blocked_at = device["blocked_at"]

        if new_status == DeviceStatus.AUTHORIZED:
            authorized_at = timestamp
            disabled_at = None
            blocked_at = None

        elif new_status == DeviceStatus.DISABLED:
            disabled_at = timestamp

        elif new_status == DeviceStatus.BLOCKED:
            blocked_at = timestamp

        conn.execute(
            """
            UPDATE devices
            SET
                status = ?,
                authorized_at = ?,
                disabled_at = ?,
                blocked_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_status.value,
                authorized_at,
                disabled_at,
                blocked_at,
                timestamp,
                device["id"],
            ),
        )

        _create_event(
            conn,
            device["id"],
            event_type,
            old_status=old_status,
            new_status=new_status.value,
            details=details,
            source=source,
        )

        return conn.execute(
            """
            SELECT *
            FROM devices
            WHERE id = ?
            """,
            (device["id"],),
        ).fetchone()


def authorize_device(mac: str, source="system"):
    return _change_status(
        mac,
        DeviceStatus.AUTHORIZED,
        EventType.DEVICE_AUTHORIZED,
        source,
    )


def block_device(mac: str, source="system"):
    return _change_status(
        mac,
        DeviceStatus.BLOCKED,
        EventType.DEVICE_BLOCKED,
        source,
    )


def disable_device(mac: str, source="system"):
    return _change_status(
        mac,
        DeviceStatus.DISABLED,
        EventType.DEVICE_DISABLED,
        source,
    )


def reauthorize_device(mac: str, source="system"):
    return _change_status(
        mac,
        DeviceStatus.AUTHORIZED,
        EventType.DEVICE_REAUTHORIZED,
        source,
    )


def rename_device(mac: str, hostname: str, source="system"):
    mac = normalize_mac(mac)
    hostname = hostname.strip()

    with get_connection() as conn:

        device = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE mac = ?
            """,
            (mac,),
        ).fetchone()

        if device is None:
            raise ValueError(f"Dispositivo não encontrado: {mac}")

        old_hostname = device["hostname"]

        conn.execute(
            """
            UPDATE devices
            SET
                hostname = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                hostname,
                now(),
                device["id"],
            ),
        )

        _create_event(
            conn,
            device["id"],
            EventType.HOSTNAME_CHANGED,
            details=f"Hostname: {old_hostname!r} -> {hostname!r}",
            source=source,
        )

        return conn.execute(
            """
            SELECT *
            FROM devices
            WHERE id = ?
            """,
            (device["id"],),
        ).fetchone()


def list_devices():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM devices
            ORDER BY hostname, mac
            """
        ).fetchall()



def list_events(mac: str | None = None):
    with get_connection() as conn:

        if mac is None:
            return conn.execute(
                """
                SELECT
                    events.*,
                    devices.mac,
                    devices.hostname
                FROM events
                JOIN devices
                    ON devices.id = events.device_id
                ORDER BY events.id ASC
                """
            ).fetchall()

        mac = normalize_mac(mac)

        return conn.execute(
            """
            SELECT
                events.*,
                devices.mac,
                devices.hostname
            FROM events
            JOIN devices
                ON devices.id = events.device_id
            WHERE devices.mac = ?
            ORDER BY events.id ASC
            """,
            (mac,),
        ).fetchall()