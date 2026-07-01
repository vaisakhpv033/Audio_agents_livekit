import sqlite3
import os
from datetime import datetime, UTC

DB_PATH = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "reports.db"))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            job_id TEXT PRIMARY KEY,
            room_id TEXT,
            room TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_seconds INTEGER,
            summary TEXT,
            overall_score INTEGER,
            created_at TEXT,
            chat_history TEXT,
            status TEXT DEFAULT 'completed',
            customer_name TEXT,
            agent_type TEXT,
            sales_rep TEXT
        )
    """)
    
    # Check if chat_history, status, customer_name, agent_type, sales_rep columns exist (dynamic migration)
    cursor.execute("PRAGMA table_info(reports)")
    columns = [row[1] for row in cursor.fetchall()]
    if "chat_history" not in columns:
        cursor.execute("ALTER TABLE reports ADD COLUMN chat_history TEXT")
    if "status" not in columns:
        cursor.execute("ALTER TABLE reports ADD COLUMN status TEXT DEFAULT 'completed'")
    if "customer_name" not in columns:
        cursor.execute("ALTER TABLE reports ADD COLUMN customer_name TEXT")
    if "agent_type" not in columns:
        cursor.execute("ALTER TABLE reports ADD COLUMN agent_type TEXT")
    if "sales_rep" not in columns:
        cursor.execute("ALTER TABLE reports ADD COLUMN sales_rep TEXT")
        
    conn.commit()
    conn.close()

def save_report(
    job_id: str,
    room_id: str,
    room: str,
    started_at: str | None,
    ended_at: str,
    summary: str | None,
    overall_score: int | None,
    duration_seconds: int | None = None,
    chat_history: str | None = None,
    status: str = "ongoing",
    customer_name: str | None = None,
    agent_type: str | None = None,
    sales_rep: str | None = None
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Calculate duration if not provided
    if duration_seconds is None and started_at and ended_at:
        try:
            # strip trailing Z and parse
            start_str = started_at.rstrip('Z')
            end_str = ended_at.rstrip('Z')
            # support formats like 2026-06-25T14:41:21.123 or 2026-06-25T14:41:21
            fmt1 = "%Y-%m-%dT%H:%M:%S.%f"
            fmt2 = "%Y-%m-%dT%H:%M:%S"
            
            try:
                start_dt = datetime.strptime(start_str, fmt1)
            except ValueError:
                start_dt = datetime.strptime(start_str, fmt2)
                
            try:
                end_dt = datetime.strptime(end_str, fmt1)
            except ValueError:
                end_dt = datetime.strptime(end_str, fmt2)
                
            duration_seconds = int((end_dt - start_dt).total_seconds())
        except Exception:
            duration_seconds = 0

    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    
    cursor.execute("""
        INSERT INTO reports (
            job_id, room_id, room, started_at, ended_at, duration_seconds, summary, overall_score, created_at, chat_history, status, customer_name, agent_type, sales_rep
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            room_id=excluded.room_id,
            room=excluded.room,
            started_at=excluded.started_at,
            ended_at=excluded.ended_at,
            duration_seconds=excluded.duration_seconds,
            summary=excluded.summary,
            overall_score=excluded.overall_score,
            created_at=excluded.created_at,
            chat_history=excluded.chat_history,
            status=excluded.status,
            customer_name=excluded.customer_name,
            agent_type=excluded.agent_type,
            sales_rep=excluded.sales_rep
    """, (
        job_id,
        room_id,
        room,
        started_at,
        ended_at,
        duration_seconds,
        summary,
        overall_score,
        now_iso,
        chat_history,
        status,
        customer_name,
        agent_type,
        sales_rep
    ))
    conn.commit()
    conn.close()

def update_report_summary(
    job_id: str,
    summary: str | None,
    overall_score: int | None,
    status: str
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports
        SET summary = ?, overall_score = ?, status = ?
        WHERE job_id = ?
    """, (summary, overall_score, status, job_id))
    conn.commit()
    conn.close()

def get_all_reports():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY ended_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_report_by_job_id(job_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
