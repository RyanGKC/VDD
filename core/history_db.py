import sqlite3
from datetime import datetime

class HistoryDB:
    def __init__(self, db_path="history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    job_id TEXT PRIMARY KEY,
                    company_name TEXT,
                    timestamp DATETIME,
                    overall_risk TEXT,
                    report_json TEXT,
                    UNIQUE(company_name, date(timestamp))
                )
            ''')
            conn.commit()

    def save_report(self, job_id: str, company_name: str, overall_risk: str, report_json: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO reports (job_id, company_name, timestamp, overall_risk, report_json) VALUES (?, ?, ?, ?, ?)",
                (job_id, company_name, datetime.now().isoformat(), overall_risk, report_json)
            )
            conn.commit()

    def get_all_reports_metadata(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT job_id, company_name, timestamp, overall_risk FROM reports ORDER BY timestamp DESC"
            )
            rows = cursor.fetchall()
            return [
                {
                    "job_id": row[0],
                    "company_name": row[1],
                    "timestamp": row[2],
                    "overall_risk": row[3]
                }
                for row in rows
            ]

    def get_report_by_job_id(self, job_id: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT report_json FROM reports WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
        return None

    def delete_reports(self, job_ids: list[str]):
        if not job_ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(job_ids))
            cursor.execute(f"DELETE FROM reports WHERE job_id IN ({placeholders})", job_ids)
            conn.commit()
