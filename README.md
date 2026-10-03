# Media Dictation

A local-first English listening and dictation trainer for YouTube and local media.

Media Dictation is designed for long-term practice on a home PC. It combines
sentence-by-sentence playback, keyboard-first dictation, learning history,
weak-sentence review, vocabulary review, local Qwen inference through Ollama,
and optional OpenAI fallback.

## Current feature set

### Dictation

- Paste a YouTube or YouTube Music URL and fetch captions automatically.
- Or upload local MP3/WAV/M4A/MP4 and other common audio/video files for optional local Whisper transcription.
- Prefer English captions when available.
- Clean non-speech cues such as `[Music]`.
- Segment captions into short listening phrases using punctuation, pauses,
  clause boundaries, and safe caption boundaries.
- Play only the current phrase and pause at its saved end timestamp.
- Hide source text by default.
- Press **Ctrl** by itself to replay the current phrase.
- Press **Enter** to correct only the first current error.
- Press **Tab / Shift+Tab** for next / previous phrase.
- Press **Ctrl+H** to show/hide the original sentence.
- Checking ignores capitalization and punctuation.
- A correct sentence remains on screen instead of auto-advancing.

### Translation and vocabulary

- Full-sentence Simplified Chinese translation.
- Click any revealed source word for its contextual Chinese meaning.
- Save a word to the vocabulary book.
- The same normalized word can have multiple contextual meanings.
- Context occurrences are retained instead of overwriting older examples.
- Translation caches are scoped by provider, model, and prompt version.

### Local and cloud LLMs

The main page also has a per-browser **LLM selector** (Auto / Local Qwen / OpenAI), so normal switching does not require editing `.env`. The environment value remains the server default.

Three provider modes are supported:

```env
LLM_PROVIDER=auto
```

- `auto`: try local Ollama first, then OpenAI fallback.
- `ollama`: local-only; OpenAI is never called.
- `openai`: cloud-only.

Recommended local model:

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TRANSLATION_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL
OLLAMA_WORD_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL
```

The Ollama request uses:

- non-thinking mode;
- temperature 0;
- `keep_alive=10m`.

In `auto` mode, local requests use shorter failover budgets so the cloud
fallback still has enough time to complete:

```env
OLLAMA_AUTO_TRANSLATION_TIMEOUT_SECONDS=12
OLLAMA_AUTO_WORD_TIMEOUT_SECONDS=7
```

Ollama does not need to be exposed to the LAN. Media Dictation calls
`127.0.0.1:11434` on the server PC.

### Local media + background Whisper

Local media is optional and does not change the normal YouTube path.

Install once:

```
setup_whisper_windows.bat
```

The main page then accepts common formats including MP3, WAV, M4A, AAC,
FLAC, OGG, OPUS, MP4, WEBM, MOV, and MKV.

Recommended settings for the current Windows workstation:

```env
WHISPER_MODEL=small.en
WHISPER_LANGUAGE=en
WHISPER_DEVICE=auto
WHISPER_RELEASE_OLLAMA=true
WHISPER_COMPUTE_TYPE_CUDA=int8_float16
WHISPER_COMPUTE_TYPE_CPU=int8

WHISPER_DOWNLOAD_ROOT=E:/AI/whisper-models
MEDIA_DICTATION_MEDIA_DIR=E:/AI/media-dictation-media
MEDIA_MAX_UPLOAD_MB=1024
```

The normal local-media flow is asynchronous:

```
local media upload
 -> persisted transcription job
 -> browser polls progress
 -> optional Qwen VRAM release
 -> faster-whisper
 -> word timestamps
 -> transcript stored with the media item
 -> start practice
 -> exact practice-item snapshot
 -> HTML5 audio/video playback
```

The default background worker count is one, which avoids trying to run multiple
Whisper jobs at once on an 8 GB GPU. The media library at `/library` shows
queued/running/completed/failed jobs, progress, saved media, practice history,
rename/retry/start/delete actions. A server restart marks an in-process job as
interrupted so it can be retried cleanly.

With `WHISPER_DEVICE=auto`, the service tries CUDA first and falls back to CPU
int8 if CUDA initialization or transcription fails. On an 8 GB GPU,
`WHISPER_RELEASE_OLLAMA=true` is recommended because the loaded Qwen model can
otherwise occupy most VRAM.

Whisper model downloads can be kept off the system drive with
`WHISPER_DOWNLOAD_ROOT`.

## Persistent learning data

SQLite is created automatically at:

```
data/media_dictation.db
```

The current schema includes:

- learner profiles;
- practice sessions;
- immutable practice-item snapshots;
- answer/correction attempts;
- playback/reveal/translation/lookup/time-spent events;
- targeted sentence review results;
- provider/model/version-scoped translation caches;
- multi-meaning vocabulary entries;
- vocabulary context occurrences;
- spaced-review scheduling;
- schema migration metadata.

Existing databases are upgraded automatically. Old sessions remain readable.
New sessions store the exact generated sentence list and timestamps, so future
segmentation changes do not alter old practice sessions.

### Learners and reports

Multiple learners can use the same server. The selected learner is remembered
in browser local storage.

The Learning Center shows:

- today;
- last 7 days;
- last 30 days;
- all-time summary;
- completed phrases;
- first-pass accuracy;
- correction count;
- replay frequency;
- source-reveal count;
- translation count;
- word-lookup count;
- estimated practice time;
- frequent errors;
- internal listening-dictation performance indicator;
- on-demand 30-day AI learning summary with a concrete 7-day practice plan.

The performance indicator is **not CEFR**. It is intended for tracking a
learner against their own history.

### Targeted review

`/review` presents historically difficult sentences, prioritized by error
count. Review answers are stored separately from original attempts so they do
not distort first-pass dictation statistics.

### Vocabulary review

Vocabulary entries can be rated:

- Again
- Hard
- Good
- Easy

The review scheduler uses **FSRS-6** through `py-fsrs`. Each vocabulary entry
stores its serialized FSRS card state and review log. The desired retention is
configurable with:

```env
FSRS_DESIRED_RETENTION=0.90
```

Legacy vocabulary automatically begins FSRS scheduling on its next review.

### CEFR-aligned listening screening

`/assessment` provides a separate 12-item fixed-material listening/dictation
screen across A2, B1, B2, and C1 difficulty bands.

It records transcription accuracy and replay count and stores assessment
history separately from ordinary YouTube/media practice. The result is labelled
a **CEFR-aligned screening estimate**. It is not an official CEFR examination or
certification.

The current version uses the browser's local American-English speech synthesis.
That keeps the assessment local, but voice quality may differ between PCs.
Human-recorded/versioned audio is a future calibration improvement.

### Data export and backup

The Learning Center has **导出数据** and **导入数据**. Export downloads a
portable JSON package for the selected learner containing:

- learner metadata;
- reports;
- sessions;
- exact practice-item snapshots;
- attempts;
- interaction telemetry;
- sentence reviews;
- vocabulary and contexts.

Import validates `export_version=1` and restores the package into a **new
learner profile**, preserving the original learner rather than overwriting it.
JSON restore does not contain local media binaries; use the full backup for
those files.

A fast database-only backup script is provided:

```
backup_data_windows.bat
```

Production startup runs this SQLite backup automatically.

When local media is used, run a complete backup periodically:

```
backup_full_windows.bat
```

That creates a timestamped copy containing both SQLite and locally uploaded
media. The portable JSON learner export contains media metadata but not the
binary audio/video files.

## Windows setup

After cloning or after a substantial update, run once:

```
setup_windows.bat
```

It:

1. installs/updates Python dependencies;
2. runs the full unit-test suite;
3. stops if tests fail.

Normal local start:

```
start_windows.bat
```

LAN production start:

```
start_production_windows.bat
```

The production launcher:

- checks dependencies without changing installed versions;
- backs up SQLite;
- checks whether local Ollama is reachable;
- starts Waitress on `0.0.0.0:8765`;
- prints LAN addresses.

The child PC only needs a browser and opens the printed URL, for example:

```
http://192.168.1.25:8765
```

Both PCs must be on the same trusted private network.

Do not forward port 8765 through the router.

Optional household PIN protection is available:

```env
MEDIA_DICTATION_PIN=2468
```

When set, browsers must log in once before accessing pages, APIs, or local
media. Leave it blank to keep the previous no-login behavior. You may also set
`MEDIA_DICTATION_SECRET_KEY` if you want login sessions to survive server
restarts.

Optional LAN hardening is available without adding Redis or another service:

```env
MEDIA_RATE_LIMIT_ENABLED=false
MEDIA_LOGIN_RATE_LIMIT_PER_MINUTE=10
MEDIA_EXPENSIVE_RATE_LIMIT_PER_MINUTE=30
MEDIA_AUDIT_ENABLED=true
```

Rate limiting is disabled by default for a trusted household LAN. When enabled,
it limits login attempts and expensive endpoints such as transcription,
translation, import, and AI summaries. Audit logging is enabled by default and
stores only action/IP/result/non-sensitive summaries; it never records PINs,
API keys, or complete dictation answers. Recent entries are available through
`/api/audit` to an authenticated household browser when PIN protection is
enabled.

## Configuration

Copy:

```
.env.example
```

to:

```
.env
```

A typical local-first configuration is:

```env
LLM_PROVIDER=auto

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TRANSLATION_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL
OLLAMA_TRANSLATION_TIMEOUT_SECONDS=60
OLLAMA_AUTO_TRANSLATION_TIMEOUT_SECONDS=12
OLLAMA_WORD_MODEL=hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL
OLLAMA_WORD_TIMEOUT_SECONDS=45
OLLAMA_AUTO_WORD_TIMEOUT_SECONDS=7

OPENAI_API_KEY=your_openai_api_key_here
OPENAI_TRANSLATION_MODEL=gpt-5.6-luna
OPENAI_TRANSLATION_SERVICE_TIER=flex
OPENAI_TRANSLATION_TIMEOUT_SECONDS=45
OPENAI_WORD_MODEL=gpt-5.6-luna
OPENAI_WORD_SERVICE_TIER=default
OPENAI_WORD_TIMEOUT_SECONDS=15

FSRS_DESIRED_RETENTION=0.90
MEDIA_TRANSCRIPTION_WORKERS=1

MEDIA_RATE_LIMIT_ENABLED=false
MEDIA_LOGIN_RATE_LIMIT_PER_MINUTE=10
MEDIA_EXPENSIVE_RATE_LIMIT_PER_MINUTE=30
MEDIA_AUDIT_ENABLED=true
```

For completely local operation:

```env
LLM_PROVIDER=ollama
```

The OpenAI API key stays in the server-side environment and is never sent to
browser JavaScript.

## Health and diagnostics

Open:

```
http://127.0.0.1:8765/api/health
```

It reports, without exposing secrets:

- database schema version;
- segmentation version;
- configured LLM provider;
- Ollama availability and model names;
- local timeout budgets;
- whether OpenAI is configured;
- OpenAI model and service-tier settings;
- whether faster-whisper is installed;
- Whisper model/device configuration;
- media upload limit;
- rate-limit/audit settings.

## Testing

Run:

```
run_tests_windows.bat
```

or:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the Python/unit/API suite, inline JavaScript syntax checks,
and a Playwright Chromium E2E suite on every push and pull request.

Coverage currently includes:

- YouTube URL parsing;
- caption cleanup and segmentation;
- schema creation/migration;
- session snapshots and resume;
- learner isolation;
- learning-event metrics;
- provider/model-scoped caching;
- local-first LLM routing;
- multi-meaning vocabulary;
- FSRS-6 vocabulary scheduling and review state;
- targeted sentence review;
- learner export API;
- local-media ingestion metadata and Whisper timestamp conversion;
- optional household PIN protection;
- per-request LLM provider override;
- AI learning summary endpoint;
- persisted media transcription jobs and transcript metadata;
- learner export/import round trips;
- CEFR-aligned assessment scoring/history.

Playwright additionally checks the real browser flow with mocked external
YouTube dependencies: learner creation, transcript loading, punctuation-
insensitive checking, session/history rendering, export/import, and the
library/assessment/review pages.

CI also runs Node syntax checks against the inline JavaScript in all browser
pages.

## Project structure

```
app.py                  Flask routes
transcript_service.py   YouTube + caption cleanup + segmentation
llm_service.py          Ollama/OpenAI providers, routing, AI summaries
media_service.py        local media persistence + optional faster-whisper
job_service.py          persisted background Whisper worker
assessment_service.py   fixed-material CEFR-aligned screening logic
storage.py              SQLite schema, migrations, repositories, analytics

static/
  index.html             main dictation UI
  learning.html          reports, history, vocabulary, SRS
  review.html            targeted weak-sentence review
  library.html           local media library and job progress
  assessment.html        fixed-material listening screening

tests/
  test_segmentation.py
  test_storage_v2.py
  test_api_v2.py
  test_media_service.py
  test_remaining_features.py
  e2e/core.spec.js
```

See `ARCHITECTURE.md` for design details and `ROADMAP.md` for remaining work.

## Keyboard shortcuts

- **Ctrl**: replay current phrase.
- **Enter**: check current answer.
- **Ctrl+H**: show/hide source.
- **Tab**: next phrase.
- **Shift+Tab**: previous phrase.

## YouTube / Codespaces note

`youtube-transcript-api` uses an undocumented YouTube endpoint. Cloud-provider
IPs are frequently blocked by YouTube. Local execution normally works through
your residential/home connection.

Proxy environment variables are still supported:

- `YT_WEBSHARE_PROXY_USERNAME`
- `YT_WEBSHARE_PROXY_PASSWORD`
- `YT_WEBSHARE_PROXY_LOCATIONS`
- `YT_HTTP_PROXY`
- `YT_HTTPS_PROXY`

Do not commit API keys, proxy credentials, cookies, local databases, or backups.
