import os
import tempfile
import importlib


def create_test_database():
    """
    Cria um banco SQLite temporário e configura o ambiente
    para que os módulos da aplicação utilizem esse banco.
    """

    db = tempfile.NamedTemporaryFile(
        prefix="wolf-portal-test-",
        suffix=".db",
        delete=False,
    )

    db_path = db.name
    db.close()

    os.environ["WOLF_PORTAL_DATABASE"] = db_path

    import app.database as database

    database.DATABASE_PATH = database.Path(db_path)

    database.initialize_database()

    return db_path


def cleanup_test_database(db_path):
    """
    Remove o banco temporário e limpa a configuração do ambiente.
    """

    os.environ.pop("WOLF_PORTAL_DATABASE", None)

    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


def isolated_database(test_function):
    """
    Executa um teste utilizando um banco SQLite completamente isolado.
    """

    def wrapper(*args, **kwargs):
        db_path = create_test_database()

        try:
            return test_function(*args, **kwargs)
        finally:
            cleanup_test_database(db_path)

    wrapper.__name__ = test_function.__name__
    wrapper.__doc__ = test_function.__doc__

    return wrapper
