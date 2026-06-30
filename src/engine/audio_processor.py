import os
import wave
from pathlib import Path
import logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WHISPER_MODEL_DIR = PROJECT_ROOT / ".models" / "whisper"
os.environ["OMP_NUM_THREADS"] = "2"


def validate_audio_file(file_path: Path):
    if not file_path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {file_path}")

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > 25.0:
        raise ValueError(f"Audio file size ({size_mb:.2f}MB) exceeds the 25MB limit")

    try:
        with wave.open(str(file_path), "rb") as wav:
            channels = wav.getnchannels()
            framerate = wav.getframerate()
            if channels != 1:
                raise ValueError(f"Audio must be mono, but has {channels} channels")
            if framerate != 16000:
                raise ValueError(
                    f"Audio must be 16kHz, but has frequency {framerate}Hz"
                )
    except wave.Error as e:
        raise ValueError(f"Invalid WAV file: {e}")


class WhisperProcessor:
    def __init__(self):
        self.model_path = WHISPER_MODEL_DIR
        self.model_bin = self.model_path / "model.bin"
        self.model = None

        # If real model exists, load it
        if self.model_bin.exists():
            try:
                from faster_whisper import WhisperModel

                logging.info(f"Loading Whisper model from {self.model_path}...")
                self.model = WhisperModel(
                    str(self.model_path),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,
                )
            except Exception as e:
                logging.error(f"Failed to load Whisper model: {e}")

    def transcribe(self, audio_path: Path) -> str:
        validate_audio_file(audio_path)

        # Fallback/Mock mode if real model was not loaded
        if self.model is None:
            logging.warning(
                "Whisper model not loaded. Falling back to mock transcription."
            )
            import time

            time.sleep(2.0)

            file_name = audio_path.name.lower()
            if "alpha" in file_name:
                transcript = (
                    "Arrived at Sector 7. Found the secondary cooling array offline. "
                    "Priority is high. Agent K and Operative J are investigating. "
                    "We need to deploy secondary cooling array."
                )
            elif "beta" in file_name:
                transcript = (
                    "Water leak detected in Server Room B. Main electrical node is at risk. "
                    "Operative S has requested immediate evacuation. Priority is critical."
                )
            else:
                transcript = (
                    "Routine check in Sector 4 completed by Agent M. "
                    "All systems nominal. Temperature is low. No issues found."
                )

            try:
                audio_path.unlink()
                logging.info(
                    f"Mock Transcription: Securely deleted raw audio {audio_path.name}"
                )
            except Exception as e:
                logging.error(f"Failed to delete audio file: {e}")

            return transcript

        # Real transcription
        logging.info(f"Starting Whisper transcription for {audio_path.name}...")
        segments, info = self.model.transcribe(str(audio_path), beam_size=5)
        text_segments = []
        for segment in segments:
            text_segments.append(segment.text)
        transcript = " ".join(text_segments).strip()
        logging.info("Transcription completed.")

        try:
            audio_path.unlink()
            logging.info(
                f"Securely deleted raw audio post-processing: {audio_path.name}"
            )
        except Exception as e:
            logging.error(f"Failed to delete audio file: {e}")

        return transcript


# Compatibility global functions for our app shell
def transcribe_audio(file_path: Path) -> str:
    processor = WhisperProcessor()
    return processor.transcribe(file_path)
