# audio — vendor-agnostic канон скилла распознавания аудио

Канонический слой для скилла `/audio` — распознавания русского аудио через [GigaAM](https://github.com/salute-developers/GigaAM) (open-source ASR от Сбера, PyPI `gigaam==0.1.0`) с VAD от [silero-vad](https://github.com/snakers4/silero-vad) (MIT).

Тонкие обёртки для AI-агентов (размещаются рядом — в корне того же дерева, где лежит `.agents/`):
- Claude Code: `.claude/skills/audio/SKILL.md`
- Codex CLI: `.codex/skills/audio/SKILL.md`

Обе обёртки вызывают `scripts/transcribe.sh` с теми же флагами. Путь к скрипту определяется автоматически от расположения `transcribe.sh` (через `dirname "$0"`).

## Что делает

Принимает аудиофайл → возвращает `.md`-транскрипцию на русском.

**Модели GigaAM v2:**
- `v2_rnnt` — дефолт, качество приоритетно. RTF ~0.2-0.3 на CPU.
- `v2_ctc` — через флаг `--fast`. Быстрее в 3-4 раза, WER чуть хуже (~2-3% vs 1.5-2%).

**VAD (для аудио ≥25 сек):** [silero-vad](https://github.com/snakers4/silero-vad) находит речевые сегменты и режет их на куски ≤24 сек (лимит `GigaAM.transcribe()` — ≤25 сек). Без HF_TOKEN, без gated-условий — полностью out-of-the-box.

## Поддерживаемые форматы

**Аудио:** m4a, mp3, wav, ogg, flac (всё, что читает системный `ffmpeg`).

**Видео-контейнеры:** mp4, webm, mkv, mov, m4v, avi — `ffmpeg` автоматически извлекает аудиодорожку, видеотрек игнорируется. Скилл работает только с аудио — отдельные файлы аудио не создаются, результат всегда `.md` с транскрипцией.

## CLI-контракт

```
transcribe.sh <audio-path> [--out <md-path>] [--fast]
transcribe.sh --check
```

Флаги (разбирает Python argparse, порядок не важен):
- `audio-path` — позиционный, обязательный (кроме `--check`).
- `--out PATH` — путь к выходному `.md`. По умолчанию `<audio-basename>.md` рядом с исходником.
- `--fast` — переключает на `v2_ctc` (быстрее, чуть хуже качество).
- `--check` — диагностика установки без аудио (синтезирует 1-сек WAV, прогоняет через `v2_ctc` + загружает silero-vad).

## Выход (формат .md)

```markdown
# Транскрипция: <filename>

- Модель: gigaam-v2-rnnt
- VAD: silero-vad (open-source)
- Длительность: HH:MM:SS
- Дата: YYYY-MM-DD HH:MM
- Аудио: `/абсолютный/путь`

## Сегменты

**[00:00:00]** текст сегмента 1

**[00:00:42]** текст сегмента 2
...

## Полный текст

<склеенный текст всех сегментов>
```

## Exit codes

| Код | Причина                                                |
|-----|--------------------------------------------------------|
| 0   | OK                                                     |
| 1   | аудиофайл не найден                                    |
| 2   | ffmpeg не установлен (проверяется в bash-обёртке)      |
| 4   | ошибка GigaAM (загрузка модели или инференс)           |
| 5   | директория выхода read-only и fallback недоступен      |

## Требования окружения

### 1. Python 3.10+
```
python3 --version
```

### 2. ffmpeg
```
brew install ffmpeg
```

### 3. Warm-up (первый запуск)

Скрипт создаёт изолированный `.venv/` в директории скилла (`.agents/skills/audio/.venv/`) и ставит зависимости из `requirements.txt`:
- `gigaam==0.1.0`
- `silero-vad>=5.1`
- `soundfile>=0.12` — audio backend для torchaudio (macOS не имеет sox_io)
- `torch>=2.5,<2.9`, `torchaudio>=2.5,<2.9` — пины обязательны (GigaAM 0.1.0 совместим только с `<2.9`).

Первый запуск скачивает:
- `torch` / `torchaudio` (~500MB)
- Веса GigaAM `v2_ctc`/`v2_rnnt` при первом `load_model()` (~240MB)
- `silero-vad` модель (~10MB) при первом VAD-вызове

Итого 2-5 минут, последующие запуски — только инференс.

**HF_TOKEN и прочие токены — НЕ нужны.**

### 4. macOS / Apple Silicon

Upstream GigaAM тестируется только на Linux/Ubuntu. На macOS:
- CPU-режим работает (smoke-тест v1 прошёл)
- `torchcodec` может не иметь нативных wheels — `torchaudio.info()` падает на m4a/mp4
- **Fallback в `transcribe.py`**: для короткого файла (<25с) при падении `torchaudio.info()` делаем predecode через ffmpeg → 16kHz mono WAV. Для длинного файла (≥25с) predecode делается всегда (silero-vad требует 16kHz mono tensor).
- Проверка: `transcribe.sh --check` — если не валится, CPU-инференс + silero-vad работают.

## VAD-пайплайн для длинных аудио (≥25с)

1. `ffmpeg` → 16kHz mono WAV во временный файл
2. `silero_vad.load_silero_vad()` — загрузка VAD-модели (кешируется)
3. `silero_vad.read_audio(wav_path, sampling_rate=16000)` → 1D tensor
4. `silero_vad.get_speech_timestamps(wav, vad, speech_pad_ms=250, min_speech_duration_ms=250, max_speech_duration_s=24.0, return_seconds=True)` → список `[{start, end}, ...]`
5. Для каждого сегмента:
   - `chunk = wav[start*16000 : end*16000]` (1D)
   - `torchaudio.save(tmp_wav, chunk.unsqueeze(0), 16000)` (2D — channel dim)
   - `text = model.transcribe(tmp_wav)` → сохраняем в сегмент
   - Удаляем tmp_wav
6. Склеиваем сегменты в `.md`

`max_speech_duration_s=24.0` заставляет silero резать длинные речевые блоки по тишине нативно — overlap вручную не нужен. `speech_pad_ms=250` добавляет padding на краях, чтобы не обрезать слова.

## Output-fallback

Если директория исходного аудио read-only (Google Drive клиента), Python автоматически пишет в `~/Downloads/audio-transcripts/<basename>.md`. Если и там нельзя — exit 5.

## Точки расширения (не в v1)

- Диаризация спикеров → `--diarize` (требует pyannote speaker-diarization-3.1, возвращает HF_TOKEN-зависимость).
- Экспорт SRT/VTT → `--format srt`.
- Эмоции через `gigaam-emo` → `--emotions`.
- Batch-режим для нескольких файлов одним вызовом.

## Файловая структура

```
<root>/
├── .agents/skills/audio/
│   ├── REFERENCE.md          # этот файл (канон, vendor-agnostic)
│   ├── scripts/
│   │   ├── transcribe.sh     # bash-обёртка (ffmpeg check + venv bootstrap + exec python)
│   │   └── transcribe.py     # весь CLI + логика (argparse, silero-vad, GigaAM)
│   ├── requirements.txt      # gigaam + silero-vad + torch/torchaudio пины
│   ├── .venv/                # изолированный Python-venv (в .gitignore)
│   └── .gitignore
├── .claude/skills/audio/
│   └── SKILL.md              # тонкая обёртка для Claude Code
└── .codex/skills/audio/
    └── SKILL.md              # тонкая обёртка для Codex CLI
```
