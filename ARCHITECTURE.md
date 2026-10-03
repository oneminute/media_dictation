# Architecture

## Goals

Media Dictation is intentionally a small local-first application rather than a
cloud platform. The core design goals are:

1. preserve learning history for years;
2. allow a child to use the application from another PC on the home LAN;
3. keep the OpenAI key and local models on the server PC;
4. prefer local inference but fail over cleanly when configured;
5. avoid coupling historical sessions to future segmentation changes;
6. keep the stack understandable: Flask + SQLite + vanilla browser JavaScript.

## Runtime

```
Child / local browser
        |
        | HTTP :8765
        v
     Waitress
        |
      Flask
   /    |      \
  /     |       \
SQLite  |      YouTube
   |    |
   |    +------ Local media / persisted Whisper job worker
   |
   LLM router
    /      \
Ollama   OpenAI
:11434   Responses API
```

The browser never talks directly to Ollama or OpenAI.

## Source processing

For YouTube:

```
URL
 -> video ID
 -> youtube-transcript-api
 -> cue cleanup
 -> segmentation
 -> practice item list
 -> snapshot into SQLite
```

Segmentation has a version identifier. A new session stores every resulting
practice item with exact text/start/end/duration.

This is important: **resume reads the saved snapshot**, not a newly segmented
copy. Legacy sessions created before snapshots existed still use the old
best-effort re-fetch path.

## Local media transcription

Local media is stored outside SQLite. SQLite stores metadata and practice
references; the actual audio/video file stays in `MEDIA_DICTATION_MEDIA_DIR`.

```
browser upload
 -> media_service.persist_uploaded_media
 -> media_sources + transcription_jobs in SQLite
 -> job_service single-worker queue
 -> optional Ollama model unload
 -> faster-whisper progress callback + word timestamps
 -> transcript persisted with media item
 -> browser polls job status
 -> start practice
 -> practice_items snapshot
```

The same session/report/vocabulary/review pipeline is used after ingestion, so
YouTube and local-media learning data have the same semantics.

For limited VRAM systems the default strategy is to release configured Ollama
models before Whisper. Whisper then tries CUDA and automatically falls back to
CPU when `WHISPER_DEVICE=auto`. The worker count defaults to one so an 8 GB GPU
does not attempt multiple model-heavy transcriptions concurrently. If the
server restarts while a job is running, persisted queued/running jobs are
marked interrupted rather than silently remaining active forever.

## Learning data model

`learners`
  separates family members.

`practice_sessions`
  one logical practice run, including source metadata.

`practice_items`
  immutable snapshot of the exact phrase sequence used in that session.

`attempts`
  Enter/check outcomes: replace, missing, extra, correct.

`practice_events`
  learning-process telemetry: playback, reveal, translation, lookup,
  navigation, time-spent.

`sentence_reviews`
  targeted review outcomes kept separate from initial dictation attempts.

`vocabulary_entries`
  learner + normalized word + meaning. This permits multiple meanings for the
  same spelling.

`vocabulary_occurrences`
  contexts in which a vocabulary meaning was encountered.

`vocabulary_reviews`
  FSRS-6 review history. `vocabulary_entries.fsrs_card_json` stores the
  serialized py-fsrs card state, while `due_at` remains the queryable next due
  timestamp.

`media_sources`
  local audio/video metadata plus persisted Whisper transcript results.

`transcription_jobs`
  durable job status/progress/result metadata for background Whisper work.

`assessment_runs` / `assessment_responses`
  fixed-material listening screening history, isolated from normal dictation.

`audit_events`
  optional household operational/security actions without secrets or answers.

## Translation cache identity

A translation is not identified only by source text.

The current cache identity is:

```
source/context
+ provider
+ model
+ prompt_version
```

This prevents an old OpenAI result from silently masquerading as a Qwen result
after the provider is changed.

## LLM routing

Provider modes:

```
ollama
openai
auto
```

`auto` uses a failover budget:

```
short local attempt
    |
    +-- success -> return local
    |
    +-- failure -> OpenAI fallback
```

The local attempt is deliberately shorter than the local-only timeout. This
prevents local timeout + cloud timeout from exceeding the browser's total
interactive deadline.

## SQLite migration policy

Schema changes are additive and tracked in `schema_migrations`.

The application does not require users to delete an existing database.
`init_db()` creates new tables/columns and best-effort migrates legacy
vocabulary into the current learner-aware representation.

Before LAN production startup, the SQLite backup API creates a consistent copy
under `backups/`.

Portable learner export/import is versioned separately from the database
schema. Import creates a new learner and maps old session IDs to new IDs rather
than overwriting existing data. JSON export intentionally omits media binary
bytes; full backup is the restore path for local audio/video files.

## AI learning summary

The narrative 30-day report is generated on demand through the same LLM router.
Only aggregate statistics, high-frequency errors, and review metrics are sent
to the selected model. Full answer history is not included in the prompt.

The prompt explicitly prevents the model from inventing CEFR levels or facts
not present in the stored metrics.

## Assessment philosophy

The regular practice score is an internal trend indicator based on observed
behavior such as:

- first-pass accuracy;
- correction count;
- replay frequency;
- source reveals.

It is deliberately not labelled A2/B1/B2/C1.

A separate `/assessment` workflow now uses versioned fixed A2/B1/B2/C1
difficulty material and records answer accuracy plus replay behavior. Its
result is explicitly labelled a **CEFR-aligned screening estimate**, not an
official CEFR examination or certification. Ordinary YouTube/media practice
never produces a CEFR label. The current screening audio is generated by the
browser's local American-English speech synthesis, so future calibration can
replace it with identical versioned recordings without changing normal
practice analytics.

## Quality gates

The repository has two complementary test layers:

1. Python unit/API/storage/media tests plus Node syntax checks for every inline
   browser script.
2. Playwright Chromium E2E against a real local Flask process. External YouTube
   behavior is mocked, while Flask, SQLite, learner/session persistence,
   punctuation-insensitive answer checking, export/import, and page navigation
   run normally.

GitHub Actions runs the unit job first and only starts browser E2E after that
gate succeeds.

## Security boundary

The current LAN mode assumes a trusted home/private network.

- API keys remain server-side.
- Ollama should stay bound locally.
- port 8765 should not be exposed to the public Internet.
- optional household PIN protection is available through
  `MEDIA_DICTATION_PIN`;
- the PIN uses a signed Flask session cookie and is intentionally a lightweight
  household access layer, not a public-Internet account system;
- optional in-process sliding-window limits cover login and expensive
  operations; they are disabled by default on a trusted home LAN;
- persistent audit events record only action, result, client IP, learner when
  available, and a short non-sensitive description.

The rate limiter is deliberately process-local. It is appropriate for the
single-host Waitress household deployment, not a distributed public service.
