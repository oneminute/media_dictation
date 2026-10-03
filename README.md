# Media Dictation

A local-first English listening and dictation trainer for YouTube content.

Media Dictation is designed for long-term practice on a home PC. It combines
sentence-by-sentence playback, keyboard-first dictation, learning history,
weak-sentence review, vocabulary review, local Qwen inference through Ollama,
and optional OpenAI fallback.

## Current feature set

### Dictation

- Paste a YouTube or YouTube Music URL and fetch captions automatically.
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

### Persistent learning data

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
- internal listening-dictation performance indicator.

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

The application schedules a future due time based on the rating. This is a
lightweight spaced-review system; it is not yet a full FSRS implementation.

### Data export and backup

The Learning Center has **导出数据**. It downloads a portable JSON export for
the selected learner containing:

- learner metadata;
- reports;
- sessions;
- exact practice-item snapshots;
- attempts;
- interaction telemetry;
- sentence reviews;
- vocabulary and contexts.

A database backup script is also provided:

```
backup_data_windows.bat
```

Production startup makes a SQLite backup before starting the server.

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

Do not forward port 8765 through the router. The LAN UI currently has no login
authentication.

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
- OpenAI model and service-tier settings.

## Testing

Run:

```
run_tests_windows.bat
```

or:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the same unit-test suite on every push and pull request.

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
- spaced-review updates;
- targeted sentence review;
- learner export API.

## Project structure

```
app.py                  Flask routes
transcript_service.py   YouTube + caption cleanup + segmentation
llm_service.py          Ollama/OpenAI providers + routing
storage.py              SQLite schema, migrations, repositories, analytics

static/
  index.html             main dictation UI
  learning.html          reports, history, vocabulary, SRS
  review.html            targeted weak-sentence review

tests/
  test_segmentation.py
  test_storage_v2.py
  test_api_v2.py
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
