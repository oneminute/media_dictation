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
   |    +------ Local media / Whisper
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
 -> optional Ollama model unload
 -> faster-whisper word timestamps
 -> transcript_service.merge_caption_fragments
 -> practice_items snapshot
```

The same session/report/vocabulary/review pipeline is used after ingestion, so
YouTube and local-media learning data have the same semantics.

For limited VRAM systems the default strategy is to release configured Ollama
models before Whisper. Whisper then tries CUDA and automatically falls back to
CPU when `WHISPER_DEVICE=auto`.

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

It is deliberately not labelled A2/B1/B2/C1. CEFR requires calibrated
assessment material and a separate validated workflow.

## Security boundary

The current LAN mode assumes a trusted home/private network.

- API keys remain server-side.
- Ollama should stay bound locally.
- port 8765 should not be exposed to the public Internet.
- optional household PIN protection is available through
  `MEDIA_DICTATION_PIN`;
- the PIN uses a signed Flask session cookie and is intentionally a lightweight
  household access layer, not a public-Internet account system.
