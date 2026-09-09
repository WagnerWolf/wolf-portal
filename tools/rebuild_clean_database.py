from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DATABASE = Path(
    "/etc/wolf-portal/data/wolf-portal.db"
)

DEFAULT_TELEGRAM_STATE = Path(
    "/etc/wolf-portal/data/telegram-bot-state.json"
)


def normalize_mac(mac: str) -> str:
    return mac.strip().lower()


def now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def timestamp_for_filename() -> str:
    return datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )


def read_devices(
    database_path: Path,
) -> list[sqlite3.Row]:

    conn = sqlite3.connect(
        database_path
    )

    conn.row_factory = sqlite3.Row

    try:
        return conn.execute(
            """
            SELECT *
            FROM devices
            ORDER BY id ASC
            """
        ).fetchall()

    finally:
        conn.close()


def show_plan(
    devices: list[sqlite3.Row],
    excluded_macs: set[str],
) -> list[sqlite3.Row]:

    kept = []

    print()
    print(
        "=============================================="
    )
    print(
        " PLANO DE RECONSTRUCAO"
    )
    print(
        "=============================================="
    )
    print()

    for row in devices:

        mac = normalize_mac(
            row["mac"]
        )

        excluded = (
            mac in excluded_macs
        )

        action = (
            "EXCLUIR"
            if excluded
            else "MANTER "
        )

        print(
            f"[{action}] "
            f"ID antigo={row['id']:>3}  "
            f"MAC={mac}  "
            f"STATUS={row['status']}  "
            f"IP={row['ip'] or '-'}  "
            f"HOST={row['hostname'] or '-'}"
        )

        if not excluded:
            kept.append(
                row
            )

    print()
    print(
        f"Total atual : {len(devices)}"
    )
    print(
        f"Manter      : {len(kept)}"
    )
    print(
        f"Excluir     : {len(devices) - len(kept)}"
    )

    return kept


def create_empty_database(
    database_path: Path,
) -> None:

    if database_path.exists():
        database_path.unlink()

    previous_database = os.environ.get(
        "WOLF_PORTAL_DATABASE"
    )

    os.environ[
        "WOLF_PORTAL_DATABASE"
    ] = str(
        database_path
    )

    try:
        import app.database as database_module

        # Garante que DATABASE_PATH seja recalculado
        # utilizando o caminho temporário acima.
        database_module = importlib.reload(
            database_module
        )

        database_module.initialize_database()

    finally:

        if previous_database is None:
            os.environ.pop(
                "WOLF_PORTAL_DATABASE",
                None,
            )
        else:
            os.environ[
                "WOLF_PORTAL_DATABASE"
            ] = previous_database


def import_devices(
    database_path: Path,
    devices: list[sqlite3.Row],
) -> None:

    conn = sqlite3.connect(
        database_path
    )

    conn.row_factory = sqlite3.Row

    try:

        for old_row in devices:

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
                    normalize_mac(
                        old_row["mac"]
                    ),
                    old_row["hostname"],
                    old_row["ip"],
                    old_row["status"],
                    old_row["first_seen"],
                    old_row["last_seen"],
                    old_row["authorized_at"],
                    old_row["disabled_at"],
                    old_row["blocked_at"],
                    old_row["created_at"],
                    old_row["updated_at"],
                ),
            )

            new_id = cursor.lastrowid

            event_time = now()

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
                    new_id,
                    event_time,
                    "DEVICE_IMPORTED",
                    None,
                    old_row["status"],
                    (
                        "Dispositivo importado durante "
                        "reconstrução limpa do banco. "
                        f"ID anterior={old_row['id']}"
                    ),
                    "database-rebuild",
                ),
            )

        conn.commit()

    finally:
        conn.close()


def verify_new_database(
    database_path: Path,
    expected_count: int,
    excluded_macs: set[str],
) -> None:

    conn = sqlite3.connect(
        database_path
    )

    conn.row_factory = sqlite3.Row

    try:

        rows = conn.execute(
            """
            SELECT
                id,
                mac,
                hostname,
                ip,
                status
            FROM devices
            ORDER BY id ASC
            """
        ).fetchall()

        if len(rows) != expected_count:
            raise RuntimeError(
                "Quantidade inesperada de dispositivos "
                "no banco reconstruído."
            )

        ids = [
            int(row["id"])
            for row in rows
        ]

        expected_ids = list(
            range(
                1,
                expected_count + 1,
            )
        )

        if ids != expected_ids:
            raise RuntimeError(
                "IDs do novo banco não são sequenciais: "
                f"{ids}"
            )

        present_macs = {
            normalize_mac(
                row["mac"]
            )
            for row in rows
        }

        unexpected = (
            present_macs
            & excluded_macs
        )

        if unexpected:
            raise RuntimeError(
                "MAC excluído apareceu no banco novo: "
                + ", ".join(
                    sorted(
                        unexpected
                    )
                )
            )

        print()
        print(
            "=============================================="
        )
        print(
            " NOVO BANCO"
        )
        print(
            "=============================================="
        )
        print()

        for row in rows:

            print(
                f"ID={row['id']:>2}  "
                f"MAC={row['mac']}  "
                f"STATUS={row['status']:<10}  "
                f"IP={row['ip'] or '-':<15}  "
                f"HOST={row['hostname'] or '-'}"
            )

    finally:
        conn.close()


def reset_telegram_event_cursors(
    state_path: Path,
) -> None:
    """
    Preserva telegram_update_offset para impedir que
    comandos antigos do Telegram sejam processados novamente.

    Remove apenas cursores relacionados aos IDs de eventos
    do banco antigo.

    Quando o bot iniciar, esses cursores serão inicializados
    novamente utilizando o banco reconstruído.
    """

    if not state_path.exists():
        return

    try:
        state = json.loads(
            state_path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as exc:
        raise RuntimeError(
            "Não foi possível ler o estado do Telegram: "
            f"{exc}"
        ) from exc

    keys_to_remove = [
        key
        for key in state
        if (
            key.startswith("last_")
            and key.endswith("_event_id")
        )
    ]

    for key in keys_to_remove:
        state.pop(
            key,
            None,
        )

    temp_path = state_path.with_name(
        state_path.name + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    os.chmod(
        temp_path,
        0o600,
    )

    os.replace(
        temp_path,
        state_path,
    )

    print()
    print(
        "Cursores de eventos do Telegram reinicializados."
    )

    if (
        "telegram_update_offset"
        in state
    ):
        print(
            "telegram_update_offset preservado: "
            f"{state['telegram_update_offset']}"
        )


def rebuild(
    database_path: Path,
    telegram_state_path: Path,
    excluded_macs: set[str],
) -> None:

    if not database_path.exists():
        raise RuntimeError(
            f"Banco não encontrado: {database_path}"
        )

    devices = read_devices(
        database_path
    )

    kept = show_plan(
        devices,
        excluded_macs,
    )

    stamp = timestamp_for_filename()

    database_backup = (
        database_path.parent
        / (
            database_path.name
            + f".pre-clean-{stamp}.bak"
        )
    )

    state_backup = (
        telegram_state_path.parent
        / (
            telegram_state_path.name
            + f".pre-clean-{stamp}.bak"
        )
    )

    print()
    print(
        "=============================================="
    )
    print(
        " BACKUP"
    )
    print(
        "=============================================="
    )

    shutil.copy2(
        database_path,
        database_backup,
    )

    print(
        f"Banco: {database_backup}"
    )

    if telegram_state_path.exists():

        shutil.copy2(
            telegram_state_path,
            state_backup,
        )

        print(
            f"Telegram: {state_backup}"
        )

    temporary_database = (
        database_path.parent
        / (
            database_path.name
            + ".rebuild.tmp"
        )
    )

    if temporary_database.exists():
        temporary_database.unlink()

    print()
    print(
        "Criando banco novo..."
    )

    create_empty_database(
        temporary_database
    )

    import_devices(
        temporary_database,
        kept,
    )

    verify_new_database(
        temporary_database,
        len(kept),
        excluded_macs,
    )

    os.chmod(
        temporary_database,
        0o600,
    )

    # Troca atômica:
    # o banco antigo só deixa de ser o arquivo principal
    # depois de o banco novo ter sido criado e validado.
    os.replace(
        temporary_database,
        database_path,
    )

    os.chmod(
        database_path,
        0o600,
    )

    reset_telegram_event_cursors(
        telegram_state_path
    )

    print()
    print(
        "=============================================="
    )
    print(
        " RECONSTRUCAO CONCLUIDA"
    )
    print(
        "=============================================="
    )
    print()
    print(
        f"Banco ativo: {database_path}"
    )
    print(
        f"Backup     : {database_backup}"
    )


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Reconstrói o banco Wolf Portal do zero, "
            "mantendo os dispositivos desejados e "
            "reiniciando os IDs."
        )
    )

    parser.add_argument(
        "--database",
        default=str(
            DEFAULT_DATABASE
        ),
    )

    parser.add_argument(
        "--telegram-state",
        default=str(
            DEFAULT_TELEGRAM_STATE
        ),
    )

    parser.add_argument(
        "--exclude-mac",
        action="append",
        default=[],
        help=(
            "MAC que não deve ser importado. "
            "Pode ser utilizado várias vezes."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Executa efetivamente a reconstrução. "
            "Sem esta opção apenas exibe o plano."
        ),
    )

    args = parser.parse_args()

    database_path = Path(
        args.database
    )

    telegram_state_path = Path(
        args.telegram_state
    )

    excluded_macs = {
        normalize_mac(
            mac
        )
        for mac in args.exclude_mac
    }

    devices = read_devices(
        database_path
    )

    show_plan(
        devices,
        excluded_macs,
    )

    if not args.apply:

        print()
        print(
            "DRY-RUN: nenhuma alteração foi realizada."
        )
        print()
        print(
            "Para executar de verdade, adicione --apply."
        )

        return 0

    rebuild(
        database_path,
        telegram_state_path,
        excluded_macs,
    )

    return 0


if __name__ == "__main__":

    try:
        raise SystemExit(
            main()
        )

    except Exception as exc:

        print(
            f"\nERRO: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(
            1
        )