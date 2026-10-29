from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA busy_timeout = 30000;")
            cursor.execute("PRAGMA temp_store = MEMORY;")
            cursor.execute("PRAGMA mmap_size = 268435456;")


class PortalConfig(AppConfig):
    name = "portal"

    def ready(self):
        connection_created.connect(configure_sqlite_wal)
