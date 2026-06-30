import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "localslate.db"


class ActionableTask(BaseModel):
    task_desc: str
    urgency: str


class IdentifiedEntities(BaseModel):
    locations: list[str] = Field(default_factory=list)
    personnel: list[str] = Field(default_factory=list)


class IncidentReport(BaseModel):
    incident_id: str
    iso_timestamp: str
    computed_priority_level: str
    system_summary: str
    identified_entities: IdentifiedEntities
    actionable_tasks: list[ActionableTask] = Field(default_factory=list)


class DatabaseEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = DB_PATH
        self.initialize()

    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    iso_timestamp TEXT NOT NULL,
                    computed_priority_level TEXT NOT NULL,
                    system_summary TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS identified_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    location_name TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS identified_personnel (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    personnel_name TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS actionable_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    task_desc TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_priority ON incidents(computed_priority_level);
                CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(iso_timestamp);
            """)
            conn.commit()

    def insert_incident(self, json_data: dict):
        try:
            incident = IncidentReport(**json_data)
        except Exception as e:
            raise ValueError(f"Failed to validate JSON data against schema: {e}")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "INSERT INTO incidents (incident_id, iso_timestamp, computed_priority_level, system_summary) VALUES (?, ?, ?, ?)",
                (
                    incident.incident_id,
                    incident.iso_timestamp,
                    incident.computed_priority_level,
                    incident.system_summary,
                ),
            )

            for loc in incident.identified_entities.locations:
                cursor.execute(
                    "INSERT INTO identified_locations (incident_id, location_name) VALUES (?, ?)",
                    (incident.incident_id, loc),
                )

            for person in incident.identified_entities.personnel:
                cursor.execute(
                    "INSERT INTO identified_personnel (incident_id, personnel_name) VALUES (?, ?)",
                    (incident.incident_id, person),
                )

            for task in incident.actionable_tasks:
                cursor.execute(
                    "INSERT INTO actionable_tasks (incident_id, task_desc, urgency) VALUES (?, ?, ?)",
                    (incident.incident_id, task.task_desc, task.urgency),
                )

            conn.commit()


# Compatibility functions for our app shell
def init_db():
    db = DatabaseEngine()
    db.initialize()


def insert_incident(data: dict):
    db = DatabaseEngine()
    db.insert_incident(data)


def get_latest_incidents(limit=5):
    db = DatabaseEngine()
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
        SELECT incident_id, iso_timestamp, computed_priority_level, system_summary, created_at
        FROM incidents
        ORDER BY created_at DESC
        LIMIT ?;
        """,
            (limit,),
        )
        rows = cursor.fetchall()
        incidents = []
        for row in rows:
            inc_id = row[0]
            cursor.execute(
                "SELECT location_name FROM identified_locations WHERE incident_id = ?;",
                (inc_id,),
            )
            locations = [r[0] for r in cursor.fetchall()]
            cursor.execute(
                "SELECT personnel_name FROM identified_personnel WHERE incident_id = ?;",
                (inc_id,),
            )
            personnel = [r[0] for r in cursor.fetchall()]
            cursor.execute(
                "SELECT task_desc, urgency FROM actionable_tasks WHERE incident_id = ?;",
                (inc_id,),
            )
            tasks = [{"task_desc": r[0], "urgency": r[1]} for r in cursor.fetchall()]
            incidents.append(
                {
                    "incident_id": inc_id,
                    "iso_timestamp": row[1],
                    "computed_priority_level": row[2],
                    "system_summary": row[3],
                    "created_at": row[4],
                    "identified_entities": {
                        "locations": locations,
                        "personnel": personnel,
                    },
                    "actionable_tasks": tasks,
                }
            )
        return incidents
    except Exception:
        return []
    finally:
        conn.close()
