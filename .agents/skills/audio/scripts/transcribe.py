#!/usr/bin/env python3
"""Распознавание аудио через GigaAM v2.

CLI:
  transcribe.py <audio> [--out PATH] [--fast]
  transcribe.py --check     # диагностика установки без аудио

Exit codes:
  0  OK
  1  audio file not found
  2  ffmpeg not found (обрабатывается в bash-обёртке)
  4  GigaAM inference error
  5  output directory read-only

Для аудио >=25с использует silero-vad (MIT, open-source) чтобы найти речевые
сегменты и прогнать их через model.transcribe() по одному. HF_TOKEN НЕ требуется.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Распознавание аудио через GigaAM v2 (russian ASR).",
    )
    ap.add_argument(
        "audio", nargs="?", type=Path, help="Путь к аудио-файлу. Не нужен с --check."
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Путь к .md (по умолчанию — рядом с аудио).",
    )
    ap.add_argument(
        "--fast", action="store_true", help="Быстрая модель v2_ctc вместо v2_rnnt."
    )
    ap.add_argument(
        "--check", action="store_true", help="Диагностика установки без аудио."
    )
    args = ap.parse_args()

    if args.check:
        _run_check()
        return

    if not args.audio or not args.audio.exists():
        sys.stderr.write("ERROR: audio file required and must exist\n")
        sys.exit(1)

    t0 = time.monotonic()
    duration = _get_duration(args.audio)

    model_name = "v2_ctc" if args.fast else "v2_rnnt"
    print(
        f"[info] модель: {model_name}, длительность: {_fmt_time(duration)}",
        file=sys.stderr,
        flush=True,
    )

    import gigaam  # type: ignore

    try:
        model = gigaam.load_model(model_name)
    except Exception as e:
        sys.stderr.write(f"GigaAM load_model failed: {e}\n")
        sys.exit(4)

    if duration < 25:
        # Короткое аудио: прямой transcribe, без VAD
        audio_for_transcribe = _ensure_readable_short(args.audio)
        try:
            text = model.transcribe(str(audio_for_transcribe))
        except Exception as e:
            sys.stderr.write(f"GigaAM transcribe failed: {e}\n")
            sys.exit(4)
        segments = [{"start": 0.0, "end": duration, "text": (text or "").strip()}]
    else:
        # Длинное аудио: predecode в 16kHz mono WAV + silero-vad
        wav_path = _ensure_wav_16k_mono(args.audio)
        try:
            segments = _transcribe_longform(model, wav_path)
        except Exception as e:
            sys.stderr.write(f"GigaAM longform (silero-vad) failed: {e}\n")
            sys.exit(4)

    default_out = args.audio.with_suffix(".md")
    out_path = _resolve_writable(args.out or default_out, args.audio)
    if out_path is None:
        sys.stderr.write("ERROR: cannot find writable output directory\n")
        sys.exit(5)

    _write_md(out_path, args.audio, model_name, duration, segments)
    elapsed = time.monotonic() - t0
    print(
        f"OK {out_path}  [{elapsed:.1f}s, модель={model_name}, сегментов={len(segments)}]"
    )


def _ensure_readable_short(audio: Path) -> Path:
    """Для коротких файлов: проверяем что torchaudio может их прочитать.
    Если нет — predecode через ffmpeg в WAV (fallback для macOS без torchcodec)."""
    try:
        import torchaudio  # type: ignore

        torchaudio.info(str(audio))
        return audio
    except Exception as e:
        print(
            f"[warn] torchaudio не смог прочитать {audio.name}: {e}",
            file=sys.stderr,
        )
        return _ensure_wav_16k_mono(audio)


def _ensure_wav_16k_mono(audio: Path) -> Path:
    """Декод в 16kHz mono WAV через ffmpeg во временный файл.

    Нужно всегда для longform-пути: silero-vad принимает только 16kHz mono tensor.
    Для коротких файлов вызывается только при падении torchaudio.info().
    """
    safe_name = audio.stem.replace(" ", "_")
    tmp = Path(tempfile.gettempdir()) / (safe_name + ".wav16k.wav")
    print(
        f"[info] predecode через ffmpeg → 16kHz mono WAV ({tmp.name})...",
        file=sys.stderr,
        flush=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            str(tmp),
        ],
        check=True,
    )
    return tmp


def _get_duration(audio: Path) -> float:
    """Длительность через torchaudio.info с ffmpeg-fallback."""
    try:
        import torchaudio  # type: ignore

        info = torchaudio.info(str(audio))
        return float(info.num_frames) / float(info.sample_rate)
    except Exception:
        # Fallback: ffprobe-style через ffmpeg
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())


def _transcribe_longform(model, wav_path: Path) -> list[dict]:
    """VAD-chunking через silero-vad + цикл model.transcribe().

    max_speech_duration_s=24 — silero сам режет длинные речевые блоки
    по тишине (умнее чем ручной split + overlap). Все сегменты <=24s,
    что укладывается в лимит GigaAM.transcribe() (<=25s).
    """
    import torchaudio  # type: ignore
    from silero_vad import (  # type: ignore
        load_silero_vad,
        get_speech_timestamps,
        read_audio,
    )

    print(
        "[info] запускаю silero-vad для поиска речевых сегментов...",
        file=sys.stderr,
        flush=True,
    )
    vad = load_silero_vad()
    wav = read_audio(str(wav_path), sampling_rate=16000)  # 1D tensor[N]

    raw_segments = get_speech_timestamps(
        wav,
        vad,
        sampling_rate=16000,
        speech_pad_ms=250,
        min_speech_duration_ms=250,
        max_speech_duration_s=24.0,
        return_seconds=True,
    )

    n = len(raw_segments)
    print(
        f"[info] найдено {n} сегмент(ов), транскрибирую...", file=sys.stderr, flush=True
    )

    segments = []
    for i, seg in enumerate(raw_segments, 1):
        s = float(seg["start"])
        e = float(seg["end"])
        start_idx = int(s * 16000)
        end_idx = int(e * 16000)
        chunk = wav[start_idx:end_idx]  # 1D tensor

        # torchaudio.save требует 2D → добавляем channel dim для mono
        tmp_wav = Path(tempfile.gettempdir()) / f"audio-chunk-{i:04d}.wav"
        torchaudio.save(str(tmp_wav), chunk.unsqueeze(0), 16000)

        try:
            text = model.transcribe(str(tmp_wav))
        finally:
            tmp_wav.unlink(missing_ok=True)

        text = (text or "").strip()
        segments.append({"start": s, "end": e, "text": text})

        if i % 5 == 0 or i == n:
            print(
                f"[info]   сегмент {i}/{n} [{_fmt_time(s)} - {_fmt_time(e)}]",
                file=sys.stderr,
                flush=True,
            )

    return segments


def _resolve_writable(out: Path, source: Path):
    """Возвращает writable Path или None если ни source-dir, ни ~/Downloads/audio-transcripts/ не writable."""
    out_parent = out.parent
    if out_parent.exists() and os.access(out_parent, os.W_OK):
        return out
    try:
        out_parent.mkdir(parents=True, exist_ok=True)
        if os.access(out_parent, os.W_OK):
            return out
    except OSError:
        pass

    fallback_dir = Path.home() / "Downloads" / "audio-transcripts"
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if not os.access(fallback_dir, os.W_OK):
        return None
    return fallback_dir / (source.stem + ".md")


def _fmt_time(sec: float) -> str:
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _write_md(
    path: Path, audio: Path, model_name: str, duration: float, segments
) -> None:
    lines = [
        f"# Транскрипция: {audio.name}",
        "",
        f"- Модель: gigaam-{model_name.replace('_', '-')}",
        "- VAD: silero-vad (open-source)",
        f"- Длительность: {_fmt_time(duration)}",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Аудио: `{audio}`",
        "",
        "## Сегменты",
        "",
    ]
    for seg in segments:
        text = seg["text"]
        if not text:
            continue
        lines.append(f"**[{_fmt_time(seg['start'])}]** {text}")
        lines.append("")

    lines.append("## Полный текст")
    lines.append("")
    full = " ".join(seg["text"] for seg in segments if seg["text"]).strip()
    lines.append(full)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _run_check() -> None:
    """Синтез 1-сек тишины + прогон через v2_ctc. Проверяет venv + ffmpeg + gigaam."""
    print("[check] создаю тестовый WAV (1 сек тишины, 16kHz mono)...", flush=True)
    tmp = Path(tempfile.gettempdir()) / "audio-skill-check.wav"
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<" + "h" * 16000, *([0] * 16000)))

    print("[check] загружаю gigaam v2_ctc...", flush=True)
    import gigaam  # type: ignore

    m = gigaam.load_model("v2_ctc")

    print("[check] прогоняю transcribe()...", flush=True)
    m.transcribe(str(tmp))

    print("[check] загружаю silero-vad...", flush=True)
    from silero_vad import load_silero_vad  # type: ignore

    load_silero_vad()

    print("OK: venv + ffmpeg + gigaam v2_ctc + silero-vad работают")


if __name__ == "__main__":
    main()
