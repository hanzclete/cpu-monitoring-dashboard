from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.errors import DuplicateDatabase, InvalidCatalogName

from db import get_connection
from db import get_database_settings
from db import get_database_url


def create_database_if_missing():
    settings = get_database_settings()

    try:
        with psycopg.connect(get_database_url()) as conn:
            return
    except InvalidCatalogName:
        pass

    with psycopg.connect(get_database_url("postgres"), autocommit=True) as conn:
        try:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(settings["dbname"])
                )
            )
            print(f"Database {settings['dbname']} created successfully.")
        except DuplicateDatabase:
            pass


def init_database():
    create_database_if_missing()

    schema_path = Path(__file__).with_name("schema.sql")
    schema = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()

    print("Database table initialized successfully.")


if __name__ == "__main__":
    init_database()
