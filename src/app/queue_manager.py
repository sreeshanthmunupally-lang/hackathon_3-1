import shutil
import uuid
import time
import logging
import threading
import hashlib
from pathlib import Path
from src.engine.audio_processor import transcribe_audio
from src.engine.slm_processor import IncidentReport, structure_text
from src.engine.db import insert_incident
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
QUEUE_DIR = PROJECT_ROOT / "data" / "queue"
FAILED_DIR = PROJECT_ROOT / "data" / "failed_audio"

# Ensure directories exist
for d in [CACHE_DIR, QUEUE_DIR, FAILED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Global status tracking for the dashboard
queue_status = {
    "is_running": False,
    "current_file": None,
    "current_status": "Idle",
    "queue_count": 0,
    "processed_count": 0,
    "failed_count": 0,
}


def get_queue_length():
    try:
        files = [
            f
            for f in QUEUE_DIR.iterdir()
            if f.is_file() and not f.name.endswith(".lock")
        ]
        return len(files)
    except Exception:
        return 0


def run_with_timeout(func, args, timeout):
    res = [None]
    err = [None]

    def target():
        try:
            res[0] = func(*args)
        except Exception as e:
            err[0] = e

    t = threading.Thread(target=target)
    t.daemon = True
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, TimeoutError(f"Task exceeded timeout of {timeout} seconds")
    if err[0] is not None:
        return None, err[0]
    return res[0], None


def process_file(file_path: Path):
    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        file_hash = hasher.hexdigest()
    except Exception:
        file_hash = str(uuid.uuid4())

    lock_path = QUEUE_DIR / f"{file_hash}.lock"
    lock_path.touch()

    suffix = file_path.suffix.lower()
    dest_path = QUEUE_DIR / f"{file_hash}{suffix}"

    try:
        shutil.move(str(file_path), str(dest_path))
    except Exception as e:
        logging.error(f"Failed to move file to queue: {e}")
        if lock_path.exists():
            lock_path.unlink()
        return

    queue_status["current_file"] = dest_path.name

    try:
        if suffix == ".wav":
            queue_status["current_status"] = "Transcribing..."
            logging.info(f"Processing audio incident {file_hash}...")

            transcript, err = run_with_timeout(transcribe_audio, (dest_path,), 120.0)
            if err:
                logging.error(f"Audio processing error/timeout: {err}")
                raise err

            queue_status["current_status"] = "Structuring..."
            report = structure_text(transcript)
            report["incident_id"] = file_hash

            queue_status["current_status"] = "Saving to Database..."
            insert_incident(report)
            queue_status["processed_count"] += 1

        elif suffix == ".txt":
            queue_status["current_status"] = "Reading Text..."
            logging.info(f"Processing text incident {file_hash}...")

            with open(dest_path, "r", encoding="utf-8") as f:
                text = f.read(4010)

            if len(text) > 4000:
                logging.warning("Text file exceeds 4000 char limit. Truncating.")
                text = text[:4000]

            queue_status["current_status"] = "Structuring..."
            report = structure_text(text)
            report["incident_id"] = file_hash

            queue_status["current_status"] = "Saving to Database..."
            insert_incident(report)

            dest_path.unlink()
            queue_status["processed_count"] += 1

        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    except Exception as e:
        logging.error(f"Failed to process incident {file_hash}: {e}")
        queue_status["failed_count"] += 1

        if dest_path.exists():
            failed_dest = FAILED_DIR / dest_path.name
            try:
                shutil.move(str(dest_path), str(failed_dest))
            except Exception as move_err:
                logging.error(
                    f"Could not move failed file to failed folder: {move_err}"
                )

        try:
            fallback_report = IncidentReport(
                incident_id=file_hash,
                iso_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                computed_priority_level="HIGH",
                system_summary=f"FAILED PROCESSING: {str(e)[:200]}",
                identified_entities={"locations": [], "personnel": []},
                actionable_tasks=[],
            ).model_dump()
            insert_incident(fallback_report)
        except Exception as db_err:
            logging.error(f"Failed to write failed record to database: {db_err}")

    finally:
        if lock_path.exists():
            lock_path.unlink()
        queue_status["current_file"] = None
        queue_status["current_status"] = "Idle"


class AudioFileHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if file_path.suffix.lower() in [".wav", ".txt"]:
            time.sleep(1.0)
            if file_path.exists():
                self.callback(file_path)


class QueueManager:
    def __init__(self, process_callback):
        self.process_callback = process_callback
        self.observer = Observer()

    def start(self):
        handler = AudioFileHandler(self.process_callback)
        self.observer.schedule(handler, str(CACHE_DIR), recursive=False)
        self.observer.start()
        queue_status["is_running"] = True
        logging.info("Queue Manager Observer started.")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        queue_status["is_running"] = False
        logging.info("Queue Manager Observer stopped.")


# Compatibility global functions for our app shell
global_queue_manager = None


def start_queue_manager():
    global global_queue_manager
    if global_queue_manager is None:
        global_queue_manager = QueueManager(process_file)
        global_queue_manager.start()


def stop_queue_manager():
    global global_queue_manager
    if global_queue_manager is not None:
        global_queue_manager.stop()
        global_queue_manager = None
