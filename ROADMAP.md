# Roadmap

## Completed foundation

- [x] Exact session snapshots for stable resume
- [x] Schema migration tracking
- [x] Multi-learner profiles
- [x] Video title metadata
- [x] Playback/reveal/translation/lookup/time telemetry
- [x] Today / 7-day / 30-day / all-time analytics
- [x] Internal performance trend indicator
- [x] Local Ollama / OpenAI / auto routing
- [x] Failover timeout budget
- [x] Provider/model/prompt-version cache identity
- [x] Multiple vocabulary meanings and contexts
- [x] Lightweight spaced vocabulary review
- [x] Weak-sentence targeted review
- [x] Separate review-result statistics
- [x] Portable learner JSON export
- [x] Consistent SQLite backup script
- [x] Stable production launcher
- [x] Automated unit tests and GitHub Actions CI
- [x] Transcript and LLM service extraction

## Next high-value work

### Local media and Whisper

- [x] MP3/WAV/M4A/MP4 and common local media upload
- [x] optional faster-whisper installation
- [x] word timestamps
- [x] automatic GPU -> CPU fallback
- [x] Qwen VRAM release before transcription
- [x] E-drive configurable Whisper/model/media paths
- [x] exact snapshots and resume for local media
- [x] local-media weak-sentence review
- [ ] background transcription jobs with progress for very long media
- [ ] media library management / deletion UI

### Standardized listening assessment

Build a separate assessment mode with calibrated fixed material. Only this mode
should estimate CEFR bands.

Do not infer CEFR directly from arbitrary YouTube or podcast dictation.

### Vocabulary scheduler

Replace the current lightweight stage scheduler with a proper FSRS
implementation once enough review-history data exists.

### LAN access hardening

Optional simple PIN/session authentication for household use, without turning
the project into a cloud account system.

### Browser E2E tests

Add Playwright-based smoke tests for:

- creating/selecting a learner;
- loading mocked transcript data;
- punctuation-insensitive checking;
- saving vocabulary;
- resuming snapshots;
- report rendering.

### Restore/import

Learner JSON export exists. Add a validated import/restore path with versioned
schema validation after the export format has stabilized.

## Deliberately deferred

- React/Vue migration
- microservices
- external database server
- complex agent frameworks

The current Flask + SQLite + vanilla JavaScript architecture is sufficient for
the intended household/local-first workload.
