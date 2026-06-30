# ruff: noqa: E402
import sys
import time
import logging
from pathlib import Path

# Add project root to python path to avoid import errors
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Disable interactive outputs for child engines
log_dir = PROJECT_ROOT / "data"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "localslate.log", encoding="utf-8"),
    ],
)

from src.engine.db import init_db, get_latest_incidents, DatabaseEngine
from src.app.queue_manager import (
    start_queue_manager,
    stop_queue_manager,
    queue_status,
    get_queue_length,
)
from src.engine.audio_processor import WhisperProcessor
from src.engine.slm_processor import SLMProcessor

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# Retain Developer 1's class-based structure from main branch
class DashboardUI:
    def __init__(self):
        self.status = "Idle"
        self.db = DatabaseEngine()
        self.whisper = None
        self.slm = None

    def initialize_models(self):
        if self.whisper is None:
            self.status = "Loading Whisper (int8)..."
            self.whisper = WhisperProcessor()
        if self.slm is None:
            self.status = "Loading Phi-3 (4k)..."
            self.slm = SLMProcessor()
        self.status = "Idle"

    def process_file(self, file_path: Path, lock_path: Path):
        self.initialize_models()
        try:
            transcription = ""
            if file_path.suffix.lower() == ".wav":
                self.status = f"Transcribing: {file_path.name}"
                transcription = self.whisper.transcribe(file_path)
            elif file_path.suffix.lower() == ".txt":
                transcription = file_path.read_text(encoding="utf-8")

            if transcription:
                self.status = "Extracting JSON schema..."
                json_data = self.slm.extract_incident(transcription)
                self.status = "Writing to database..."
                self.db.insert_incident(json_data)
        except Exception as e:
            logging.error(f"DashboardUI process_file error: {e}")
        finally:
            if lock_path.exists():
                lock_path.unlink()
            self.status = "Idle"


# Our Interactive Console dashboard routines
def generate_mock_text_file():
    cache_dir = PROJECT_ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report_text_alpha_{int(time.time())}.txt"
    filepath = cache_dir / filename
    content = (
        "FIELD NOTES: Temperature spike in Sector 7. Main node cooling array is offline. "
        "Agent K and Operative J are investigating the primary malfunction. "
        "Need to deploy secondary cooling array immediately."
    )
    filepath.write_text(content, encoding="utf-8")
    return filename


def generate_mock_audio_file():
    import wave
    import struct

    cache_dir = PROJECT_ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report_audio_beta_{int(time.time())}.wav"
    filepath = cache_dir / filename

    with wave.open(str(filepath), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        for _ in range(16000):
            wav.writeframesraw(struct.pack("<h", 0))
    return filename


def get_keypress():
    if sys.platform == "win32":
        import msvcrt

        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                if ch in (b"\x00", b"\xe0"):
                    msvcrt.getch()
                    return None
                return ch.decode("utf-8").lower()
            except UnicodeDecodeError:
                return None
    return None


def check_ram_string():
    try:
        import psutil

        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024**3)
        total_gb = mem.total / (1024**3)
        return f"{used_gb:.2f}/{total_gb:.2f} GB ({mem.percent}%)"
    except ImportError:
        return "Unknown"


def draw_header() -> Panel:
    text = Text(
        "LocalSlate - Offline-First Intelligence Dashboard 🌌", style="bold magenta"
    )
    text.append(
        "\nCPU-Bound Inference Engine Pipeline | Offline Mode", style="cyan dim"
    )
    return Panel(text, border_style="blue")


def draw_status() -> Panel:
    status_text = Text()
    status_text.append("SYSTEM STATUS\n", style="bold yellow")

    manager_state = "RUNNING" if queue_status["is_running"] else "STOPPED"
    manager_color = "green" if queue_status["is_running"] else "red"
    status_text.append("• Ingestion Service: ", style="bold")
    status_text.append(f"{manager_state}\n", style=manager_color)

    status_text.append("• Active File: ", style="bold")
    curr_file = queue_status["current_file"]
    status_text.append(f"{curr_file or 'None'}\n", style="cyan")

    status_text.append("• Pipeline Step: ", style="bold")
    status_text.append(
        f"{queue_status['current_status']}\n",
        style="bold green" if queue_status["current_status"] != "Idle" else "white",
    )

    status_text.append("• Local Ingest Queue: ", style="bold")
    status_text.append(f"{get_queue_length()} pending\n", style="yellow")

    status_text.append("• RAM Allocation: ", style="bold")
    status_text.append(f"{check_ram_string()}\n", style="white")

    status_text.append("• CPU Threads: ", style="bold")
    status_text.append("4 Max (2 Whisper, 2 SLM)\n\n", style="white")

    status_text.append("METRICS\n", style="bold yellow")
    status_text.append(
        f"✓ Processed: {queue_status['processed_count']}\n", style="bold green"
    )
    status_text.append(
        f"✗ Failed/Pending: {queue_status['failed_count']}\n", style="bold red"
    )

    return Panel(status_text, border_style="yellow")


def draw_incidents() -> Panel:
    table = Table(expand=True)
    table.add_column("Incident ID", style="dim", width=12)
    table.add_column("Timestamp", width=15)
    table.add_column("Priority", width=10)
    table.add_column("Locations", width=15)
    table.add_column("Personnel", width=15)
    table.add_column("Summary", style="white")

    incidents = get_latest_incidents(5)
    for inc in incidents:
        priority = inc["computed_priority_level"]
        color = "white"
        if priority == "CRITICAL":
            color = "bold red"
        elif priority == "HIGH":
            color = "bold orange3"
        elif priority == "MEDIUM":
            color = "yellow"
        elif priority == "LOW":
            color = "green"
        elif priority == "PENDING_REVIEW":
            color = "bold red blinking"

        locations = ", ".join(inc["identified_entities"]["locations"])
        personnel = ", ".join(inc["identified_entities"]["personnel"])

        table.add_row(
            inc["incident_id"][:8] + "...",
            inc["iso_timestamp"][:19].replace("T", " "),
            Text(priority, style=color),
            locations if locations else "N/A",
            personnel if personnel else "N/A",
            inc["system_summary"],
        )
    return Panel(table, border_style="green", title="Latest SQLite Database Records")


def draw_footer() -> Panel:
    text = Text()
    text.append("[Q]", style="bold red")
    text.append(" Quit  |  ", style="white")
    text.append("[T]", style="bold green")
    text.append(" Drop Mock Text File  |  ", style="white")
    text.append("[A]", style="bold blue")
    text.append(" Drop Mock WAV Audio File", style="white")
    return Panel(text, border_style="cyan")


def main():
    if not HAS_RICH:
        print("Error: The 'rich' library is required to run the LocalSlate Dashboard.")
        print("Please install dependencies: pip install rich psutil pydantic")
        sys.exit(1)

    init_db()
    start_queue_manager()

    console = Console()
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="status", ratio=1), Layout(name="incidents", ratio=3)
    )

    console.print("[green]Launching LocalSlate CLI Dashboard...[/green]")

    message = ""
    message_time = 0

    try:
        with Live(layout, screen=True, refresh_per_second=4):
            while True:
                layout["header"].update(draw_header())
                layout["status"].update(draw_status())
                layout["incidents"].update(draw_incidents())

                footer_panel = draw_footer()
                if time.time() - message_time < 3.0:
                    footer_panel.subtitle = message
                layout["footer"].update(footer_panel)

                kp = get_keypress()
                if kp == "q":
                    break
                elif kp == "t":
                    fname = generate_mock_text_file()
                    message = f"Success: Ingested {fname} into cache."
                    message_time = time.time()
                elif kp == "a":
                    fname = generate_mock_audio_file()
                    message = f"Success: Ingested WAV {fname} into cache."
                    message_time = time.time()

                time.sleep(0.1)
    finally:
        stop_queue_manager()
        console.clear()
        print("LocalSlate ingestion background pipeline stopped. Goodbye.")


if __name__ == "__main__":
    main()
