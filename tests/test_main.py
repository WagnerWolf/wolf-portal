import inspect
import sqlite3
import sys
import tempfile

from contextlib import contextmanager
from pathlib import Path

import app.database as database

from app.main import (
    main,
    startup,
)


@contextmanager
def temporary_database():
    original_path = database.DATABASE_PATH

    with tempfile.TemporaryDirectory() as temp_dir:

        database.DATABASE_PATH = (
            Path(temp_dir)
            / "wolf-portal-main-test.db"
        )

        try:
            yield database.DATABASE_PATH

        finally:
            database.DATABASE_PATH = (
                original_path
            )


def test_startup_initializes_database_before_sync():
    with temporary_database() as db_path:

        state = {
            "sync_called": False,
            "devices_table_exists": False,
        }

        def fake_sync():
            state["sync_called"] = True

            assert db_path.exists()

            with sqlite3.connect(
                db_path
            ) as conn:

                row = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE
                        type = 'table'
                        AND name = 'devices'
                    """
                ).fetchone()

            state[
                "devices_table_exists"
            ] = row is not None

            return "SYNC_OK"

        result = startup(
            sync_callback=fake_sync
        )

        assert (
            state["sync_called"]
            is True
        )

        assert (
            state[
                "devices_table_exists"
            ]
            is True
        )

        assert result == "SYNC_OK"


def test_startup_returns_sync_result():
    with temporary_database():

        marker = object()

        def fake_sync():
            return marker

        result = startup(
            sync_callback=fake_sync
        )

        assert result is marker


def test_main_returns_zero_on_success():
    with temporary_database():

        calls = {
            "count": 0
        }

        def fake_sync():
            calls["count"] += 1

        result = main(
            sync_callback=fake_sync
        )

        assert result == 0
        assert calls["count"] == 1


def test_main_returns_nonzero_on_sync_failure():
    with temporary_database():

        def fake_sync():
            raise RuntimeError(
                "Falha simulada"
            )

        result = main(
            sync_callback=fake_sync
        )

        assert result == 1


def run_tests():
    tests = [
        obj
        for name, obj in globals().items()
        if name.startswith("test_")
        and inspect.isfunction(obj)
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
