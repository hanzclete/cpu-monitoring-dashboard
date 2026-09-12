import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_database_settings(dbname=None):
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": dbname or os.getenv("DB_NAME", "cpu_monitor"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "1234"),
    }


def get_database_url(dbname=None):
    settings = get_database_settings(dbname)
    return (
        f"host={settings['host']} "
        f"port={settings['port']} "
        f"dbname={settings['dbname']} "
        f"user={settings['user']} "
        f"password={settings['password']}"
    )


@contextmanager
def get_connection():
    conn = psycopg.connect(get_database_url())
    try:
        yield conn
    finally:
        conn.close()
