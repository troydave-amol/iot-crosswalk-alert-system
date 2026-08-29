"""
db.py — Database connection manager and backward-compatible API.

This module retains the public interface that the rest of the codebase
imports (``from db import init_db, insert_event, fetch_events, ...``).
The actual logic now lives in ``repositories/`` — this file delegates
to singleton instances for backward compatibility.

Public API (unchanged):
    get_connection()
    init_db()
    authenticate_user(username, password)
    get_user_by_username(username)
    update_user_password(username, new_password)
    insert_event(payload)
    fetch_events(...)
    stream_events(...)
    fetch_analytics_aggregates(time_range)
    RAW_EXPORT_FIELDS
"""

import os
import pymysql
import pymysql.cursors
from datetime import datetime, timezone
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Import repository singletons and constants
from repositories import user_repo, event_repo
from repositories.event_repository import RAW_EXPORT_FIELDS  # noqa: F401 — re-exported

load_dotenv()


# ────────────────────────────────────────────────────────────────────────────
# Connection Helpers
# ────────────────────────────────────────────────────────────────────────────

def get_connection():
    """
    Creates a new database connection.
    Intentionally determines database presence to allow creation if missing.
    """
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


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


# ────────────────────────────────────────────────────────────────────────────
# Schema Initialization & Seed Data
# ────────────────────────────────────────────────────────────────────────────

def init_db():
    """
    Initializes the database and table.
    Safe to run multiple times.
    """
    conn = None
    try:
        # 1. Connect without selecting a database to create it if needed
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        target_db = os.getenv("DB_NAME", "crosswalk_db")

        with conn.cursor() as cursor:
            # Create Database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {target_db}")
            cursor.execute(f"USE {target_db}")

            # Create events table
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp_iso DATETIME NOT NULL,
                source VARCHAR(16) NOT NULL,
                child_in_roi TINYINT(1) NOT NULL,
                roi_status VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                latency_ms INT NOT NULL,
                warning_logic_on TINYINT(1) NOT NULL,
                switch_enabled TINYINT(1) NOT NULL,
                warning_device_on TINYINT(1) NOT NULL,
                battery_percent FLOAT NOT NULL,
                solar_status VARCHAR(16) NOT NULL,
                scenario VARCHAR(32) NULL,
                camera_status VARCHAR(16) NULL,
                edge_status VARCHAR(16) NULL,
                led_driver_status VARCHAR(16) NULL,
                INDEX idx_timestamp (timestamp_iso),
                INDEX idx_warning (warning_device_on),
                INDEX idx_child (child_in_roi)
            )
            """
            cursor.execute(create_table_sql)

            # Attempt to add indexes individually if table already existed without them
            # This handles the migration case where the table exists but new indexes don't
            try:
                cursor.execute("CREATE INDEX idx_warning ON events (warning_device_on)")
            except Exception:
                pass  # Index likely exists or other non-critical error

            try:
                cursor.execute("CREATE INDEX idx_child ON events (child_in_roi)")
            except Exception:
                pass

            # Migration: add child_count column if it doesn't exist (safe for existing tables)
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN child_count INT NOT NULL DEFAULT 0")
                print(f"  → Added 'child_count' column to events table.")
            except Exception:
                pass  # Column already exists

            print(f"Database '{target_db}' and table 'events' checked/initialized successfully.")

            # ── RBAC: Create users table ──────────────────────────────
            create_users_sql = """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role ENUM('tmc_officer', 'it_specialist') NOT NULL DEFAULT 'tmc_officer',
                full_name VARCHAR(128) NOT NULL,
                created_at DATETIME NOT NULL,
                last_login DATETIME NULL,
                INDEX idx_username (username),
                INDEX idx_role (role)
            )
            """
            cursor.execute(create_users_sql)
            print(f"  → Table 'users' checked/initialized successfully.")

            # Seed default accounts if the users table is empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM users")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # TMC Officer seed
                tmc_user = os.getenv("TMC_USERNAME", "tmc_officer")
                tmc_pass = os.getenv("TMC_PASSWORD", "SmartCrosswalk2026")
                tmc_hash = generate_password_hash(tmc_pass)

                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (tmc_user, tmc_hash, "tmc_officer", "TMC Officer", now_iso)
                )

                # IT Specialist seed
                it_user = os.getenv("IT_SPECIALIST_USERNAME", "it_specialist")
                it_pass = os.getenv("IT_SPECIALIST_PASSWORD", "uswagmalaybalay")
                it_hash = generate_password_hash(it_pass)

                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (it_user, it_hash, "it_specialist", "IT Systems Specialist", now_iso)
                )

                print(f"  → Seeded default users: '{tmc_user}' (tmc_officer), '{it_user}' (it_specialist)")
            else:
                print(f"  → Users table already populated ({row['cnt']} users). Skipping seed.")

    except Exception as e:
        print(f"DB INIT INVALID: {e}")
        # We do not raise, so the app can continue running even if DB fails
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────────────────────────
# Backward-Compatible Function Aliases
# ────────────────────────────────────────────────────────────────────────────
# These delegate to repository singletons so existing callers (app.py,
# LiveSession, VideoTestSession) don't need any import changes.

def authenticate_user(username, password):
    return user_repo.authenticate(username, password)

def get_user_by_username(username):
    return user_repo.get_by_username(username)

def update_user_password(username, new_password):
    return user_repo.update_password(username, new_password)

def insert_event(payload):
    return event_repo.insert(payload)

def fetch_events(**kwargs):
    return event_repo.fetch(**kwargs)

def stream_events(**kwargs):
    return event_repo.stream(**kwargs)

def fetch_analytics_aggregates(time_range="all"):
    return event_repo.fetch_analytics(time_range)
