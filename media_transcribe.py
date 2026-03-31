#!/usr/bin/env python3
"""Download media, extract audio, and transcribe it with Whisper."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from loguru import logger

AudioFormat = Literal["opus", "mp3", "wav", "m4a"]
OutputFormat = Literal["txt", "srt", "vtt", "json", "tsv", "all"]
WhisperDevice = Literal["auto", "cpu", "cuda"]


def console_friendly_name(value: str) -> str:
    """Convert a title-like string into a shell-friendly filename stem."""
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"[^\w.\-]+", "-", value, flags=re.ASCII)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-. _")
    return value or "media"


def detect_whisper_device() -> WhisperDevice:
    """Return the preferred Whisper device based on local PyTorch CUDA support."""
    try:
        import torch
    except ImportError:
        logger.debug("PyTorch is not importable; defaulting Whisper device to cpu")
        return "cpu"

    cuda_available = torch.cuda.is_available()
    logger.debug("PyTorch CUDA available: {}", cuda_available)
    return "cuda" if cuda_available else "cpu"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the media transcription workflow."""
    parser = argparse.ArgumentParser(
        description="Wrap yt-dlp, ffmpeg, and whisper into one transcription workflow."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="Media file path or URL to download and transcribe. Omit to record from a local audio source.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for downloaded media, extracted audio, and transcript files. Defaults to a temp directory.",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model to use. Default: base",
    )
    parser.add_argument(
        "--language",
        help="Optional language code or name to pass to Whisper.",
    )
    parser.add_argument(
        "--audio-format",
        default="opus",
        choices=("opus", "mp3", "wav", "m4a"),
        help="Audio format to write with ffmpeg. Default: opus",
    )
    parser.add_argument(
        "--output-format",
        default="txt",
        choices=("txt", "srt", "vtt", "json", "tsv", "all"),
        help="Whisper output format. Default: txt",
    )
    parser.add_argument(
        "--keep-video",
        action="store_true",
        help="Keep the original downloaded video or source file untouched.",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the extracted audio file after transcription.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip transcript cleanup for txt output.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="Whisper inference device. Default: auto",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Record local audio interactively and stop with Ctrl+C.",
    )
    parser.add_argument(
        "--capture-source",
        default="@DEFAULT_MONITOR@",
        help="PulseAudio/PipeWire source name to record from. Default: @DEFAULT_MONITOR@",
    )
    parser.add_argument(
        "--create-virtual-sink",
        action="store_true",
        help="Create a temporary virtual output sink and record from its monitor source.",
    )
    parser.add_argument(
        "--virtual-sink-name",
        default="media-transcribe",
        help="Name for the temporary virtual sink. Default: media-transcribe",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=4,
        help="Chunk size in seconds for live transcription. Default: 4",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        choices=("auto", "float16", "float32", "int8"),
        help="faster-whisper compute type for live capture. Default: auto",
    )
    return parser


def is_url(value: str) -> bool:
    """Return True when the input looks like an HTTP(S) URL."""
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def ensure_command(name: str) -> None:
    """Exit with an error if the named external command is unavailable."""
    if shutil.which(name):
        logger.debug("Found required command on PATH: {}", name)
        return
    raise SystemExit(f"Required command not found on PATH: {name}")


def run_command(args: list[str], capture_stdout: bool = False) -> str | None:
    """Run a subprocess command with logging and optional stdout capture."""
    kwargs = {
        "check": True,
        "text": True,
    }
    if capture_stdout:
        kwargs["stdout"] = subprocess.PIPE
    logger.debug("Running command: {}", " ".join(args))
    result = subprocess.run(args, **kwargs)
    if capture_stdout:
        logger.debug("Command completed with captured output")
        return result.stdout.strip()
    logger.debug("Command completed")
    return None


def record_audio(source_name: str, output_path: Path) -> Path:
    """Record audio from a PulseAudio/PipeWire source into a WAV file until interrupted."""
    ensure_command("parec")
    logger.info("Recording from {}. Press Ctrl+C to stop.", source_name)
    cmd = [
        "parec",
        "--device",
        source_name,
        "--file-format=wav",
        str(output_path),
    ]
    process = subprocess.Popen(cmd)
    try:
        process.wait()
    except KeyboardInterrupt:
        logger.info("Stopping recording")
        process.terminate()
        process.wait(timeout=5)
        print("", file=sys.stderr)

    if process.returncode not in {0, -15}:
        raise subprocess.CalledProcessError(process.returncode or 1, cmd)

    if not output_path.exists():
        raise SystemExit(f"Recording did not create an output file: {output_path}")
    logger.info("Recorded audio to {}", output_path)
    return output_path


def live_transcribe_audio(
    source_name: str,
    transcript_path: Path,
    model_name: str,
    device: WhisperDevice,
    language: str | None,
    chunk_seconds: int = 4,
    sample_rate: int = 16_000,
    channels: int = 1,
    compute_type: str = "auto",
) -> Path:
    """Record PCM audio from a local source and transcribe rolling chunks with faster-whisper."""
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError as exc:
        raise SystemExit(
            "The Python faster-whisper and numpy packages are not installed in the active environment. Run `uv sync`."
        ) from exc

    try:
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from textual.reactive import reactive
        from textual.widgets import Footer, Header, Static
    except ImportError as exc:
        raise SystemExit("The Python textual package is not installed in the active environment. Run `uv sync`.") from exc

    ensure_command("parec")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("")

    resolved_compute_type = compute_type if compute_type != "auto" else ("float16" if device == "cuda" else "int8")
    model = WhisperModel(
        model_name,
        device="cuda" if device == "cuda" else "cpu",
        compute_type=resolved_compute_type,
    )
    bytes_per_second = sample_rate * channels * 2
    chunk_size = bytes_per_second * chunk_seconds
    pending = bytearray()
    chunk_index = 0
    stop_requested = threading.Event()

    cmd = [
        "parec",
        "--device",
        source_name,
        "--raw",
        f"--rate={sample_rate}",
        "--format=s16le",
        f"--channels={channels}",
    ]
    logger.info("Streaming local audio from {}. Press Ctrl+C to stop.", source_name)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started_at = time.monotonic()
    total_bytes_recorded = 0
    transcript_line_count = 0
    status_message = "Recording live audio. Press Ctrl+C to stop."
    transcript_lines: list[str] = []

    class CaptureApp(App[None]):
        """Simple Textual app to display live capture status and transcript output."""

        BINDINGS = [("ctrl+q", "quit_capture", "Quit")]

        CSS = """
        Screen {
            layout: vertical;
        }

        #status {
            height: 10;
            padding: 0 1;
            border: round $accent;
        }

        #transcript {
            height: 1fr;
            padding: 0 1;
            border: round $success;
        }
        """

        status_text = reactive("")
        transcript_text = reactive("")

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Vertical():
                yield Static(id="status")
                yield Static(id="transcript")
            yield Footer()

        def on_mount(self) -> None:
            self.update_status()
            self.update_transcript()

        def update_status(self) -> None:
            elapsed = int(time.monotonic() - started_at)
            minutes, seconds = divmod(elapsed, 60)
            recorded_seconds = total_bytes_recorded / bytes_per_second if bytes_per_second else 0
            self.status_text = "\n".join(
                [
                    f"Source: {source_name}",
                    f"Model: {model_name}",
                    f"Device: {device}",
                    f"Compute type: {resolved_compute_type}",
                    f"Transcript: {transcript_path}",
                    f"Elapsed: {minutes:02d}:{seconds:02d}",
                    f"Chunks processed: {chunk_index}",
                    f"Transcript lines: {transcript_line_count}",
                    f"Buffered audio: {len(pending) / bytes_per_second:.1f}s",
                    f"Recorded audio: {recorded_seconds:.1f}s",
                    f"Status: {status_message}",
                ]
            )
            self.query_one("#status", Static).update(self.status_text)

        def update_transcript(self) -> None:
            transcript = "\n".join(transcript_lines[-30:]).strip()
            self.transcript_text = transcript
            self.query_one("#transcript", Static).update(self.transcript_text or "Waiting for transcription...")

        def action_quit_capture(self) -> None:
            nonlocal status_message
            status_message = "Stopping live transcription"
            stop_requested.set()
            if process.poll() is None:
                process.terminate()
            self.update_status()
            self.exit()

    app = CaptureApp()

    def safe_ui_update(callback: Callable[[], None]) -> None:
        """Attempt a thread-safe UI update, ignoring late calls after app shutdown."""
        try:
            app.call_from_thread(callback)
        except RuntimeError:
            pass

    def transcribe_chunk(pcm_data: bytes) -> None:
        nonlocal chunk_index, transcript_line_count, status_message
        if not pcm_data.strip(b"\x00"):
            return

        chunk_index += 1
        status_message = f"Transcribing chunk {chunk_index}"
        safe_ui_update(app.update_status)
        audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio,
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        lines = [segment.text.strip() for segment in segments if segment.text.strip()]
        if not lines:
            status_message = f"Chunk {chunk_index} produced no transcript"
            safe_ui_update(app.update_status)
            return

        with transcript_path.open("a") as transcript_file:
            if transcript_file.tell() > 0:
                transcript_file.write("\n")
            transcript_file.write("\n".join(lines))
            transcript_file.write("\n")
        transcript_lines.extend(lines)
        transcript_line_count += len(lines)
        status_message = f"Chunk {chunk_index} appended to {transcript_path.name}"
        safe_ui_update(app.update_status)
        safe_ui_update(app.update_transcript)

    def worker() -> None:
        nonlocal total_bytes_recorded, status_message
        try:
            assert process.stdout is not None
            while True:
                if stop_requested.is_set():
                    break
                data = process.stdout.read(4096)
                if not data:
                    break
                total_bytes_recorded += len(data)
                pending.extend(data)
                safe_ui_update(app.update_status)
                while len(pending) >= chunk_size:
                    chunk = bytes(pending[:chunk_size])
                    del pending[:chunk_size]
                    transcribe_chunk(chunk)
        finally:
            if pending and not stop_requested.is_set():
                transcribe_chunk(bytes(pending))
            status_message = "Stopping capture"
            safe_ui_update(app.update_status)
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            safe_ui_update(app.exit)

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    try:
        app.run()
    except KeyboardInterrupt:
        status_message = "Stopping live transcription"
        process.terminate()
        print("", file=sys.stderr)
    worker_thread.join()

    logger.info("Transcript written to {}", transcript_path)
    return transcript_path


def get_default_sink() -> str:
    """Return the current default PulseAudio/PipeWire sink name."""
    ensure_command("pactl")
    default_sink = run_command(["pactl", "get-default-sink"], capture_stdout=True)
    if not default_sink:
        raise SystemExit("Failed to determine the default sink with pactl.")
    return default_sink


def create_virtual_sink(sink_name: str) -> tuple[list[str], str, str]:
    """Create a temporary null sink, mirror it to the current default sink, and return module ids."""
    ensure_command("pactl")
    sink_name = console_friendly_name(sink_name).lower()
    mirrored_sink = get_default_sink()
    module_ids: list[str] = []
    sink_module_id = run_command(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description={sink_name}",
        ],
        capture_stdout=True,
    )
    if not sink_module_id:
        raise SystemExit("Failed to create virtual sink with pactl.")
    module_ids.append(sink_module_id)
    monitor_source = f"{sink_name}.monitor"
    loopback_module_id = run_command(
        [
            "pactl",
            "load-module",
            "module-loopback",
            f"source={monitor_source}",
            f"sink={mirrored_sink}",
            "latency_msec=50",
        ],
        capture_stdout=True,
    )
    if loopback_module_id:
        module_ids.append(loopback_module_id)
    logger.info("Created virtual sink {} with monitor {}", sink_name, monitor_source)
    logger.info("Mirroring virtual sink {} to {}", sink_name, mirrored_sink)
    return module_ids, monitor_source, mirrored_sink


def unload_virtual_sink(module_ids: list[str]) -> None:
    """Unload previously created PulseAudio/PipeWire modules."""
    ensure_command("pactl")
    for module_id in reversed(module_ids):
        run_command(["pactl", "unload-module", module_id])
        logger.info("Removed virtual sink module {}", module_id)


def download_source(source: str, output_dir: Path) -> Path:
    """Download a URL with yt-dlp and return the normalized local file path."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise SystemExit(
            "The Python yt-dlp package is not installed in the active environment. Run `uv sync`."
        ) from exc

    logger.info("Downloading source with yt-dlp")
    template = str(output_dir / "%(title)s [%(id)s].%(ext)s")
    options = {
        "outtmpl": template,
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
    }
    logger.debug("yt-dlp output template: {}", template)
    before_files = {path.resolve() for path in output_dir.iterdir() if path.is_file()}
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=True)
        requested_downloads = info.get("requested_downloads") or []
        actual_path = None
        for item in requested_downloads:
            filepath = item.get("filepath")
            if filepath:
                actual_path = filepath
                break

        if actual_path is None:
            actual_path = info.get("_filename")

        if actual_path is None:
            actual_path = ydl.prepare_filename(info)

        output_path = Path(actual_path).resolve()
    after_files = [path.resolve() for path in output_dir.iterdir() if path.is_file()]
    if not output_path.exists():
        logger.debug("yt-dlp reported missing path {}; scanning output directory", output_path)
        sidecar_suffixes = {
            ".description",
            ".info.json",
            ".jpg",
            ".json",
            ".part",
            ".png",
            ".webp",
            ".ytdl",
        }
        new_files = [
            path
            for path in after_files
            if path not in before_files and not any(str(path).endswith(suffix) for suffix in sidecar_suffixes)
        ]
        if not new_files:
            raise SystemExit(f"yt-dlp reported an output path that does not exist: {output_path}")
        output_path = max(new_files, key=lambda path: path.stat().st_mtime)
    friendly_path = output_path.with_name(
        f"{console_friendly_name(output_path.stem)}{output_path.suffix.lower()}"
    )
    if friendly_path != output_path:
        friendly_path.unlink(missing_ok=True)
        output_path.rename(friendly_path)
        output_path = friendly_path
    logger.info("Downloaded media to {}", output_path)
    return output_path


def audio_codec_args(audio_format: AudioFormat) -> str:
    """Map a requested output format to the corresponding PyAV codec name."""
    codec_names = {
        "opus": "libopus",
        "mp3": "libmp3lame",
        "wav": "pcm_s16le",
        "m4a": "aac",
    }
    try:
        return codec_names[audio_format]
    except KeyError as exc:
        raise ValueError(f"Unsupported audio format: {audio_format}") from exc


def output_container_name(audio_format: AudioFormat) -> str | None:
    """Return an explicit output container name when the file extension needs one."""
    if audio_format == "m4a":
        return "ipod"
    return None


def extract_audio(media_path: Path, output_dir: Path, audio_format: AudioFormat) -> Path:
    """Decode the first audio stream with PyAV and write it to a standalone file."""
    try:
        import av
    except ImportError as exc:
        raise SystemExit("The Python av package is not installed in the active environment. Run `uv sync`.") from exc

    audio_path = output_dir / f"{console_friendly_name(media_path.stem)}.{audio_format}"
    logger.info("Extracting audio to {}", audio_path)
    codec_name = audio_codec_args(audio_format)

    with av.open(str(media_path)) as input_container:
        input_stream = next((stream for stream in input_container.streams if stream.type == "audio"), None)
        if input_stream is None:
            raise SystemExit(f"No audio stream found in source file: {media_path}")

        output_kwargs: dict[str, str] = {}
        container_name = output_container_name(audio_format)
        if container_name:
            output_kwargs["format"] = container_name

        with av.open(str(audio_path), mode="w", **output_kwargs) as output_container:
            output_stream = output_container.add_stream(codec_name, rate=48_000)
            output_stream.bit_rate = 128_000 if audio_format == "opus" else 192_000
            output_stream.layout = "stereo"

            for frame in input_container.decode(input_stream):
                if frame.pts is None:
                    frame.pts = None
                frame.sample_rate = 48_000
                for packet in output_stream.encode(frame):
                    output_container.mux(packet)

            for packet in output_stream.encode(None):
                output_container.mux(packet)

    logger.info("Audio extraction complete")
    return audio_path


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    model: str,
    language: str | None,
    output_format: OutputFormat,
    device: WhisperDevice,
) -> Path:
    """Transcribe an audio file with the Whisper Python API and write the chosen output format."""
    try:
        import whisper
        from whisper.utils import get_writer
    except ImportError as exc:
        raise SystemExit(
            "The Python whisper package is not installed in the active environment. Run `uv sync`."
        ) from exc

    logger.info("Starting Whisper transcription with model {} on {}", model, device)
    logger.debug("Loading Whisper model {}", model)
    model_instance = whisper.load_model(model, device=device)
    transcribe_kwargs: dict[str, Any] = {
        "fp16": device == "cuda",
    }
    if language:
        transcribe_kwargs["language"] = language
    result = model_instance.transcribe(str(audio_path), **transcribe_kwargs)

    transcript_path = output_dir / f"{console_friendly_name(audio_path.stem)}.txt"
    if output_format == "all":
        writer = get_writer("all", str(output_dir))
        writer(result, audio_path.name)
        transcript_path.write_text(render_segment_transcript(result))
    elif output_format == "txt":
        transcript_path.write_text(render_segment_transcript(result))
    else:
        writer = get_writer(output_format, str(output_dir))
        writer(result, audio_path.name)
        transcript_path = output_dir / f"{console_friendly_name(audio_path.stem)}.{output_format}"
    logger.info("Transcription complete: {}", transcript_path)
    return transcript_path


def render_segment_transcript(result: dict[str, Any]) -> str:
    """Render Whisper segments as readable plain text with line and stanza breaks."""
    segments = result.get("segments") or []
    if not segments:
        text = str(result.get("text", "")).strip()
        return f"{text}\n" if text else ""

    lines: list[str] = []
    previous_end: float | None = None

    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)

        if previous_end is not None and start - previous_end >= 1.5 and lines and lines[-1] != "":
            lines.append("")

        lines.append(text)
        previous_end = end

    return "\n".join(lines).strip() + "\n"


def maybe_clean_transcript(transcript_path: Path) -> None:
    """Retained for compatibility; segment-based txt output no longer needs a cleanup pass."""
    logger.debug("Skipping transcript cleanup for {}", transcript_path)


def write_exception_log(output_dir: Path, exc: BaseException) -> Path:
    """Persist an exception traceback to a timestamped log file and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = output_dir / f"media-transcribe-error-{timestamp}.log"
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_path.write_text(details)
    return log_path


def main() -> int:
    """Run the end-to-end download, extraction, transcription, and cleanup flow."""
    parser = build_parser()
    args = parser.parse_args()

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.debug else "INFO",
        format="<level>{level: <8}</level> {message}",
    )

    explicit_output_dir = args.output_dir is not None
    if args.output_dir is None:
        working_dir = Path(tempfile.mkdtemp(prefix="media-transcribe-"))
        transcript_dir = Path.cwd()
    else:
        working_dir = args.output_dir.expanduser().resolve()
        transcript_dir = working_dir

    working_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Using working directory {}", working_dir.resolve())
    logger.debug("Using transcript directory {}", transcript_dir.resolve())
    whisper_device = detect_whisper_device() if args.device == "auto" else args.device
    logger.info("Selected Whisper device: {}", whisper_device)

    if args.source is None and not args.capture:
        raise SystemExit("Provide a source path/URL or use --capture for local audio capture.")

    virtual_sink_module_ids: list[str] | None = None
    try:
        if args.capture:
            capture_source = args.capture_source
            mirrored_sink: str | None = None
            if args.create_virtual_sink:
                virtual_sink_module_ids, capture_source, mirrored_sink = create_virtual_sink(args.virtual_sink_name)
                logger.info(
                    "Route application audio to output sink '{}' while recording from '{}'",
                    console_friendly_name(args.virtual_sink_name).lower(),
                    capture_source,
                )
                if mirrored_sink is not None:
                    logger.info("Virtual sink audio is also mirrored to '{}'", mirrored_sink)
            transcript_path = transcript_dir / f"{console_friendly_name(args.virtual_sink_name)}.txt"
            live_transcribe_audio(
                capture_source,
                transcript_path,
                args.model,
                whisper_device,
                args.language,
                chunk_seconds=args.chunk_seconds,
                compute_type=args.compute_type,
            )
            return 0
        else:
            assert args.source is not None
            source_path = (
                download_source(args.source, working_dir)
                if is_url(args.source)
                else Path(args.source).expanduser().resolve()
            )
        if not source_path.exists():
            raise SystemExit(f"Source file does not exist: {source_path}")
        logger.info("Using source {}", source_path)

        audio_path = extract_audio(source_path, working_dir, args.audio_format)
        transcript_path = transcribe_audio(
            audio_path=audio_path,
            output_dir=transcript_dir,
            model=args.model,
            language=args.language,
            output_format=args.output_format,
            device=whisper_device,
        )

        if args.output_format == "txt" and not args.no_clean:
            maybe_clean_transcript(transcript_path)

        if args.source is not None and is_url(args.source) and not args.keep_video:
            logger.debug("Removing downloaded source file {}", source_path)
            source_path.unlink(missing_ok=True)

        if not args.keep_audio:
            logger.debug("Removing extracted audio file {}", audio_path)
            audio_path.unlink(missing_ok=True)

        logger.info("Transcript written to {}", transcript_path)
        return 0
    finally:
        if virtual_sink_module_ids is not None:
            try:
                unload_virtual_sink(virtual_sink_module_ids)
            except Exception:
                logger.exception("Failed to unload virtual sink modules {}", virtual_sink_module_ids)


def cli() -> int:
    """Wrap main() with terminal-facing exception handling and error log persistence."""
    try:
        return main()
    except KeyboardInterrupt:
        raise
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code == 0:
            return 0

        fallback_output_dir = Path.cwd()
        if len(sys.argv) > 1:
            try:
                args, _ = build_parser().parse_known_args()
                if args.output_dir is not None:
                    fallback_output_dir = args.output_dir
            except Exception:
                pass

        error_log = write_exception_log(fallback_output_dir, exc)
        print(str(exc), file=sys.stderr)
        print(f"Exception log written to: {error_log}", file=sys.stderr)
        return code
    except Exception as exc:
        fallback_output_dir = Path.cwd()
        if len(sys.argv) > 1:
            try:
                args, _ = build_parser().parse_known_args()
                if args.output_dir is not None:
                    fallback_output_dir = args.output_dir
            except Exception:
                pass
        error_log = write_exception_log(fallback_output_dir, exc)
        logger.exception("Unhandled exception")
        print(f"Exception log written to: {error_log}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
