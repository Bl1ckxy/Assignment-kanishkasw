"""Thin MySQL helpers: one connection factory + small query utilities.

Aggregation happens in SQL; only small result sets reach Python (keeps memory bounded).
"""
from contextlib import contextmanager

import pymysql

from config import DB_HOST, DB_PORT, DB_USER, DB_NAME, IST_OFFSET, require_password


def connect(db: str = DB_NAME, time_zone: str = IST_OFFSET, autocommit: bool = True):
    """Open a connection.

    time_zone:
      IST_OFFSET  -> session renders/derives IST parts (default for analysis).
      UTC_OFFSET  -> session matches the import session (raw dump semantics).
    """
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=require_password(),
        database=db,
        charset="utf8mb4",
        autocommit=autocommit,
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION time_zone = %s", (time_zone,))
    return conn


@contextmanager
def query(conn, sql: str, args=None):
    """Run a query, return rows as tuples; caller only fetches small results."""
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    yield rows


def fetch_df(conn, sql: str, args=None, columns=None):
    """Fetch a SMALL aggregate result into a DataFrame (small tables only)."""
    import pandas as pd

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
        cols = columns or [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def scalar(conn, sql: str, args=None):
    """Return the first column of the first row."""
    with conn.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
    return row[0] if row else None


def execute(conn, sql: str, args=None) -> int:
    """Execute DDL/DML, return affected row count."""
    with conn.cursor() as cur:
        n = cur.execute(sql, args)
    return n
