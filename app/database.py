import os
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATABASE_PATH = Path(
    os.environ.get(
        "WOLF_PORTAL_DATABASE",
        str(DATA_DIR / "wolf-portal.db"),
    )
)


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def initialize_database() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                mac TEXT NOT NULL UNIQUE,

                hostname TEXT,
                ip TEXT,

                status TEXT NOT NULL DEFAULT 'PENDING',

                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,

                authorized_at TEXT,
                disabled_at TEXT,
                blocked_at TEXT,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                device_id INTEGER NOT NULL,

                timestamp TEXT NOT NULL,

                event_type TEXT NOT NULL,

                old_status TEXT,
                new_status TEXT,

                details TEXT,

                source TEXT NOT NULL DEFAULT 'system',

                FOREIGN KEY (device_id)
                    REFERENCES devices(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_devices_mac
                ON devices(mac);

            CREATE INDEX IF NOT EXISTS idx_devices_status
                ON devices(status);

            CREATE INDEX IF NOT EXISTS idx_events_device
                ON events(device_id);

            CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp);
            """
        )
