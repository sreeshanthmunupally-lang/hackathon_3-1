import pytest
import sqlite3
from pathlib import Path

from src.engine.db import DatabaseEngine
from src.engine.audio_processor import validate_audio_file
from src.engine.slm_processor import mock_extraction, IncidentReport


def test_db_initialization(tmp_path):
    # Test DB path
    test_db_path = tmp_path / "test_localslate.db"

    db_engine = DatabaseEngine()
    db_engine.db_path = test_db_path
    db_engine.initialize()

    assert test_db_path.exists()

    conn = sqlite3.connect(str(test_db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall()]
    conn.close()

    assert "incidents" in tables
    assert "identified_locations" in tables
    assert "identified_personnel" in tables
    assert "actionable_tasks" in tables


def test_pydantic_schema_validation():
    text = "Report from Sector 7 by Agent K. Cooling array offline."
    data = mock_extraction(text)

    report = IncidentReport(**data)

    assert report.computed_priority_level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert "Sector 7" in report.identified_entities.locations
    assert "Agent K" in report.identified_entities.personnel
    assert len(report.actionable_tasks) > 0


def test_audio_processor_file_not_found():
    non_existent = Path("data/non_existent_file.wav")
    with pytest.raises(FileNotFoundError):
        validate_audio_file(non_existent)


def test_audio_processor_size_limit(tmp_path):
    large_file = tmp_path / "large.wav"
    # Write 26MB of dummy bytes to exceed the 25MB limit
    with open(large_file, "wb") as f:
        f.write(b"\0" * (26 * 1024 * 1024))

    with pytest.raises(ValueError, match="exceeds the 25MB limit"):
        validate_audio_file(large_file)
