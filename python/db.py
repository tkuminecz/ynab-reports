"""
SQLite database module for storing historical payoff timeline snapshots.

This provides persistence for reconstructed historical data and ongoing tracking.
"""

import sqlite3
import json
import os
from datetime import date, datetime
from typing import List, Dict, Optional
from contextlib import contextmanager


DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "payoff_history.db")


@contextmanager
def get_connection(db_path: str = DEFAULT_DB_PATH):
    """Get a database connection with automatic cleanup."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH):
    """Initialize the database schema."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Main snapshots table - one row per month
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payoff_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date DATE NOT NULL UNIQUE,
                snapshot_month TEXT NOT NULL,
                total_balance REAL NOT NULL,
                months_to_payoff INTEGER NOT NULL,
                projected_debt_free_date DATE NOT NULL,
                total_payments REAL,
                total_interest REAL,
                snowball_amount REAL,
                snowball_increase REAL,
                strategy TEXT,
                num_accounts INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT DEFAULT 'reconstructed'
            )
        """)

        # Account-level snapshots
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                account_name TEXT NOT NULL,
                balance REAL NOT NULL,
                interest_rate REAL,
                min_payment REAL,
                projected_payoff_month INTEGER,
                FOREIGN KEY (snapshot_id) REFERENCES payoff_snapshots(id)
            )
        """)

        # Payment history (for tracking actual vs projected)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_date DATE NOT NULL,
                account_name TEXT NOT NULL,
                total_payment REAL NOT NULL,
                min_payment REAL,
                snowball_payment REAL,
                interest_paid REAL,
                principal_paid REAL,
                balance_after REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(payment_date, account_name)
            )
        """)

        # Indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_date
            ON payoff_snapshots(snapshot_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_month
            ON payoff_snapshots(snapshot_month)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_account_snapshots_snapshot
            ON account_snapshots(snapshot_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_history_date
            ON payment_history(payment_date)
        """)

        conn.commit()


def save_snapshot(
    snapshot_date: date,
    total_balance: float,
    months_to_payoff: int,
    projected_debt_free_date: date,
    accounts: List[Dict],
    total_payments: float = None,
    total_interest: float = None,
    snowball_amount: float = None,
    snowball_increase: float = None,
    strategy: str = None,
    source: str = "reconstructed",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """
    Save a payoff snapshot to the database.

    Returns the snapshot ID.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Insert or replace main snapshot
        cursor.execute("""
            INSERT OR REPLACE INTO payoff_snapshots (
                snapshot_date, snapshot_month, total_balance, months_to_payoff,
                projected_debt_free_date, total_payments, total_interest,
                snowball_amount, snowball_increase, strategy, num_accounts, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_date.isoformat(),
            snapshot_date.strftime("%Y-%m"),
            total_balance,
            months_to_payoff,
            projected_debt_free_date.isoformat(),
            total_payments,
            total_interest,
            snowball_amount,
            snowball_increase,
            strategy,
            len(accounts),
            source,
        ))

        snapshot_id = cursor.lastrowid

        # Delete any existing account snapshots for this snapshot
        cursor.execute("""
            DELETE FROM account_snapshots
            WHERE snapshot_id IN (
                SELECT id FROM payoff_snapshots
                WHERE snapshot_date = ?
            )
        """, (snapshot_date.isoformat(),))

        # Insert account snapshots
        for account in accounts:
            cursor.execute("""
                INSERT INTO account_snapshots (
                    snapshot_id, account_name, balance, interest_rate,
                    min_payment, projected_payoff_month
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id,
                account.get("account"),
                account.get("balance"),
                account.get("interest_rate"),
                account.get("min_payment"),
                account.get("payoff_month"),
            ))

        conn.commit()
        return snapshot_id


def save_projections(
    projections: List[Dict],
    snowball_amount: float,
    snowball_increase: float,
    strategy: str,
    db_path: str = DEFAULT_DB_PATH,
):
    """
    Save multiple projections from historical reconstruction.
    """
    for projection in projections:
        save_snapshot(
            snapshot_date=projection["snapshot_date"],
            total_balance=projection["total_balance"],
            months_to_payoff=projection["months_to_payoff"],
            projected_debt_free_date=projection["projected_debt_free_date"],
            accounts=[],  # Account details not stored for historical
            total_payments=projection.get("total_payments"),
            total_interest=projection.get("total_interest"),
            snowball_amount=snowball_amount,
            snowball_increase=snowball_increase,
            strategy=strategy,
            source="reconstructed",
            db_path=db_path,
        )


def get_all_snapshots(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all snapshots ordered by date."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM payoff_snapshots
            ORDER BY snapshot_date ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_snapshot_by_month(
    month: str,
    db_path: str = DEFAULT_DB_PATH
) -> Optional[Dict]:
    """Get a snapshot for a specific month (format: YYYY-MM)."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM payoff_snapshots
            WHERE snapshot_month = ?
        """, (month,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_account_snapshots(
    snapshot_id: int,
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict]:
    """Get all account snapshots for a given snapshot."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM account_snapshots
            WHERE snapshot_id = ?
        """, (snapshot_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_latest_snapshot(db_path: str = DEFAULT_DB_PATH) -> Optional[Dict]:
    """Get the most recent snapshot."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM payoff_snapshots
            ORDER BY snapshot_date DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None


def get_snapshots_in_range(
    start_date: date,
    end_date: date,
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict]:
    """Get snapshots within a date range."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM payoff_snapshots
            WHERE snapshot_date BETWEEN ? AND ?
            ORDER BY snapshot_date ASC
        """, (start_date.isoformat(), end_date.isoformat()))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def save_payment(
    payment_date: date,
    account_name: str,
    total_payment: float,
    min_payment: float = None,
    snowball_payment: float = None,
    interest_paid: float = None,
    principal_paid: float = None,
    balance_after: float = None,
    db_path: str = DEFAULT_DB_PATH,
):
    """Save a payment record."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO payment_history (
                payment_date, account_name, total_payment, min_payment,
                snowball_payment, interest_paid, principal_paid, balance_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payment_date.isoformat(),
            account_name,
            total_payment,
            min_payment,
            snowball_payment,
            interest_paid,
            principal_paid,
            balance_after,
        ))
        conn.commit()


def get_payment_history(
    account_name: str = None,
    start_date: date = None,
    end_date: date = None,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict]:
    """Get payment history, optionally filtered."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM payment_history WHERE 1=1"
        params = []

        if account_name:
            query += " AND account_name = ?"
            params.append(account_name)
        if start_date:
            query += " AND payment_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND payment_date <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY payment_date ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def clear_all_data(db_path: str = DEFAULT_DB_PATH):
    """Clear all data from the database (for testing/reset)."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM account_snapshots")
        cursor.execute("DELETE FROM payoff_snapshots")
        cursor.execute("DELETE FROM payment_history")
        conn.commit()


def get_db_stats(db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Get statistics about stored data."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM payoff_snapshots")
        num_snapshots = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(snapshot_date), MAX(snapshot_date) FROM payoff_snapshots")
        row = cursor.fetchone()
        date_range = (row[0], row[1]) if row[0] else (None, None)

        cursor.execute("SELECT COUNT(*) FROM payment_history")
        num_payments = cursor.fetchone()[0]

        return {
            "num_snapshots": num_snapshots,
            "date_range": date_range,
            "num_payments": num_payments,
        }
