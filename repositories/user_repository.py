"""
user_repository.py — RBAC user authentication and password management.

Provides stateless, connection-per-call database operations for the ``users``
table.  Each method opens its own connection, performs the query, and closes
the connection — no shared state or long-lived connections.
"""

import os
from datetime import datetime, timezone

import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()


def _get_db_connection():
    """Return a connection to the target database (not root-level)."""
    target_db = os.getenv("DB_NAME", "crosswalk_db")
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=target_db,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


class UserRepository:
    """Data-access object for the ``users`` table."""

    def authenticate(self, username: str, password: str) -> dict | None:
        """
        Authenticate a user against the users table.
        Returns the user row dict on success, None on failure.
        """
        conn = None
        try:
            conn = _get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if user and check_password_hash(user["password_hash"], password):
                    # Update last_login timestamp
                    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "UPDATE users SET last_login = %s WHERE id = %s",
                        (now_iso, user["id"])
                    )
                    return user
                return None
        except Exception as e:
            print(f"[AUTH] authenticate_user error: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_by_username(self, username: str) -> dict | None:
        """Fetch a single user row by username. Returns None if not found."""
        conn = None
        try:
            conn = _get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                return cursor.fetchone()
        except Exception as e:
            print(f"[AUTH] get_user_by_username error: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_password(self, username: str, new_password: str) -> bool:
        """
        Update a user's password hash in the database.
        Returns True on success, False on failure.
        """
        conn = None
        try:
            conn = _get_db_connection()
            new_hash = generate_password_hash(new_password)
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE username = %s",
                    (new_hash, username)
                )
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[AUTH] update_user_password error: {e}")
            return False
        finally:
            if conn:
                conn.close()
