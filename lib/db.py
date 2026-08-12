import pymysql

from .config import Settings


def ro_connection(settings: Settings):
    """Skybear MySQL slave 只读连接。复用 webuy-data-platform/sync/skybear_sync/db.py 的风格。"""
    return pymysql.connect(
        host=settings.ro_mysql_host,
        port=settings.ro_mysql_port,
        user=settings.ro_mysql_user,
        password=settings.ro_mysql_password,
        database=settings.ro_mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
        read_timeout=60,
    )
