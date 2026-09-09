import os
import tempfile


class TestDatabase:
    def __init__(self):
        self.file = tempfile.NamedTemporaryFile(
            prefix="wolf-portal-test-",
            suffix=".db",
            delete=False,
        )

        self.path = self.file.name
        self.file.close()

    def __enter__(self):
        os.environ["WOLF_PORTAL_DATABASE"] = self.path
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        os.environ.pop("WOLF_PORTAL_DATABASE", None)

        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
