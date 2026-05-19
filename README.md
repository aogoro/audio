# audio

Russian speech-to-text transcription using [GigaAM v3](https://github.com/salute-developers/GigaAM) + [silero-vad](https://github.com/snakers4/silero-vad). Fully local, no API keys required. Works on CPU (macOS Apple Silicon, Linux).

---

Транскрипция русского аудио через GigaAM v3 (open-source ASR от Сбера) + silero-vad для сегментации длинных записей. Полностью локально, без API-ключей.

## Возможности

- Распознавание русской речи через GigaAM v3 (end-to-end с пунктуацией и нормализацией текста)
- Пунктуация, заглавные буквы, нормализация — из коробки (e2e модели)
- Длинные аудио: silero-vad автоматически находит речевые сегменты
- Аудио: m4a, mp3, wav, ogg, flac
- Видео: mp4, webm, mkv, mov, m4v, avi (ffmpeg извлекает аудиодорожку)
- Выход: Markdown с таймстемпами по сегментам + полный текст
- Работает на CPU (macOS Apple Silicon, Linux)
- Не требует HF_TOKEN или других токенов

## Требования

- Python 3.10+
- ffmpeg (`brew install ffmpeg` / `apt install ffmpeg`)

Всё остальное (venv, зависимости, веса моделей) подтягивается автоматически при первом запуске.

## Установка

```bash
git clone https://github.com/aogoro/audio.git
```

### Куда положить

Репо содержит три папки: `.agents/`, `.claude/`, `.codex/`. Их можно разместить двумя способами:

**В рабочую папку проекта** — скилл виден только в этом проекте:
```bash
cd ~/my-project
git clone https://github.com/aogoro/audio.git /tmp/audio-skill
cp -r /tmp/audio-skill/.agents .agents
cp -r /tmp/audio-skill/.claude .claude
cp -r /tmp/audio-skill/.codex .codex
```

**В домашнюю директорию (`~/`)** — скилл глобальный, виден из любого проекта в Claude Code CLI, Cursor, VS Code, desktop-app:
```bash
cd ~
git clone https://github.com/aogoro/audio.git /tmp/audio-skill
cp -r /tmp/audio-skill/.agents .agents
cp -r /tmp/audio-skill/.claude .claude
cp -r /tmp/audio-skill/.codex .codex
```

> Если у вас уже есть `.agents/`, `.claude/`, `.codex/` с другими скиллами — копируйте только `skills/audio/` в соответствующие папки.

### Первый запуск

При первом вызове скрипт автоматически:
1. Создаёт изолированный `.venv/` в директории скилла
2. Устанавливает зависимости (`gigaam`, `silero-vad`, `soundfile`, `torch`, `torchaudio`)
3. Скачивает веса моделей GigaAM (~240MB) и silero-vad (~10MB)

Суммарно ~750MB, 2-5 минут. Последующие запуски — только инференс.

## Использование

### CLI

```bash
# Транскрибировать аудиофайл
bash .agents/skills/audio/scripts/transcribe.sh recording.m4a

# Быстрый режим (v3_e2e_ctc, в 3-4 раза быстрее)
bash .agents/skills/audio/scripts/transcribe.sh meeting.mp4 --fast

# Указать выходной файл
bash .agents/skills/audio/scripts/transcribe.sh lecture.wav --out ~/Documents/lecture.md

# Проверить установку (без аудио)
bash .agents/skills/audio/scripts/transcribe.sh --check
```

### Флаги

| Флаг | Описание |
|------|----------|
| `--fast` | Модель v3_e2e_ctc (быстрее в 3-4 раза, чуть ниже качество) |
| `--out PATH` | Путь к выходному .md |
| `--check` | Диагностика установки без аудио |

### AI-скилл

После установки Claude Code и Codex автоматически подхватывают скилл. Триггеры:

- «транскрибируй запись»
- «расшифруй аудио»
- «расшифруй видео»
- `/audio path/to/file.m4a`

### Формат выхода

```markdown
# Транскрипция: recording.m4a

- Модель: gigaam-v3-e2e-rnnt
- VAD: silero-vad (open-source)
- Длительность: 00:45:12
- Дата: 2026-05-19 14:30
- Аудио: `/path/to/recording.m4a`

## Сегменты

**[00:00:00]** Текст первого сегмента с пунктуацией.

**[00:00:42]** Текст второго сегмента с заглавными буквами.

## Полный текст

<склеенный текст всех сегментов>
```

## Модели

| Модель | Флаг | Особенности | Когда использовать |
|--------|------|-------------|-------------------|
| v3_e2e_rnnt | (по умолчанию) | Пунктуация, нормализация, лучшее качество | Качество важно |
| v3_e2e_ctc | `--fast` | Пунктуация, нормализация, быстрее в 3-4 раза | Быстрый черновик |

## Vendor-agnostic архитектура

Скилл построен по 3-tier vendor-agnostic архитектуре. Логика отделена от конкретного AI-рантайма:

```
.agents/skills/audio/          ← Tier 1: канон (vendor-neutral)
  REFERENCE.md                   source of truth — алгоритм, параметры, контракт
  scripts/transcribe.{sh,py}     вся логика

.claude/skills/audio/          ← Tier 2: тонкая обёртка Claude Code
  SKILL.md                       ~70 строк: парсинг аргументов + Claude I/O

.codex/skills/audio/           ← Tier 3: тонкая обёртка Codex CLI
  SKILL.md                       ~60 строк: парсинг аргументов + Codex I/O
```

**Канон** (`.agents/`) содержит всю бизнес-логику: какие модели использовать, как резать длинное аудио, формат выхода, exit codes. Он vendor-neutral — не упоминает конкретные tools.

**Обёртки** (`.claude/`, `.codex/`) — тонкие адаптеры по 50-80 строк. Они маппят vendor-neutral операции на инструменты конкретного хоста (Read/Write/Bash для Claude, apply_patch/read_file для Codex). Обёртки ссылаются на канон, но никогда не дублируют алгоритм.

Зачем:
- **Переиспользуемость** — один алгоритм работает в Claude Code, Codex, Cursor, VS Code, desktop-app
- **Поддержка** — изменения логики в одном месте (канон), обёртки не трогаем
- **Ясность** — каждый файл делает одно: логику ИЛИ I/O-маппинг

## Лицензия

MIT. Зависимости: [GigaAM](https://github.com/salute-developers/GigaAM) (MIT), [silero-vad](https://github.com/snakers4/silero-vad) (MIT).
