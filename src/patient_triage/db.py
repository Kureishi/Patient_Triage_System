import sqlite3
import time
from . import config


def init_db(path: str = None):
    path = path or config.DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            source_file TEXT,
            case_id TEXT,
            event TEXT,
            detail TEXT,
            ts REAL
        )
    """)
    conn.commit()
    return conn


def log_event(conn, patient_id, source_file, case_id, event, detail=""):
    conn.execute(
        "INSERT INTO case_events (patient_id, source_file, case_id, event, detail, ts) VALUES (?,?,?,?,?,?)",
        (patient_id, source_file, case_id, event, detail, time.time()),
    )
    conn.commit()
