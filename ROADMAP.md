# Roadmap

## V1 household learning platform — completed

### Stable learning foundation

- [x] Exact session snapshots for stable resume
- [x] Additive SQLite schema migration tracking
- [x] Multi-learner profiles and isolated reports
- [x] Video titles and source metadata
- [x] Playback / reveal / translation / lookup / time telemetry
- [x] Today / 7-day / 30-day / all-time analytics
- [x] Internal dictation trend indicator
- [x] Weak-sentence targeted review with separate review statistics
- [x] Provider/model/prompt-version translation cache identity
- [x] Portable learner JSON export
- [x] Validated learner JSON import into a new profile
- [x] Consistent SQLite backup
- [x] Full SQLite + local-media backup

### LLMs

- [x] Local Ollama / OpenAI / auto routing
- [x] Short local failover budget in auto mode
- [x] Per-browser Auto / Local Qwen / OpenAI selector
- [x] Context-aware sentence and word translation
- [x] On-demand AI 30-day learning summary

### Vocabulary

- [x] Multiple meanings for one spelling
- [x] Multiple source-context occurrences
- [x] Again / Hard / Good / Easy review UI
- [x] FSRS-6 scheduling via py-fsrs
- [x] Persistent FSRS card state and review history

### Local media and Whisper

- [x] MP3/WAV/M4A/MP4 and common media upload
- [x] Optional faster-whisper installation
- [x] Word timestamps
- [x] CUDA -> CPU fallback
- [x] Qwen VRAM release before transcription
- [x] E-drive configurable model/media paths
- [x] Background persisted transcription jobs
- [x] Live transcription progress
- [x] Single-worker default for limited VRAM
- [x] Media library
- [x] Rename, retry, start-practice and deletion controls
- [x] Exact snapshots/resume for local media
- [x] Local-media weak-sentence review

### Listening assessment

- [x] Separate fixed-material assessment mode
- [x] A2 / B1 / B2 / C1 screening bands
- [x] Punctuation-insensitive transcription scoring
- [x] Replay-aware scoring
- [x] Per-level results and assessment history
- [x] Explicit distinction between screening estimate and official CEFR testing

### Household deployment and security

- [x] Waitress LAN production launcher
- [x] Optional household PIN/session authentication
- [x] Optional high-cost/login rate limiting
- [x] Persistent non-sensitive audit log
- [x] API keys stay server-side
- [x] Ollama can remain loopback-only

### Quality gates

- [x] Python unit/API/storage/media tests
- [x] Browser inline JavaScript syntax checks
- [x] Playwright browser E2E workflow
- [x] GitHub Actions CI
- [x] Transcript / LLM / media / background-job service extraction

## Future enhancements — not V1 blockers

These are useful improvements, but the current household system does not depend
on them for reliable long-term use.

- Replace browser speech synthesis in the CEFR-aligned screening with a
  versioned set of human-recorded or centrally generated American-English
  audio clips. This would make assessment audio identical across computers.
- Validate the screening thresholds against external calibrated material before
  treating them as more than a household estimate.
- Optimize FSRS parameters from a sufficiently large personal review history;
  until then the standard FSRS-6 scheduler and configured desired retention are
  used.
- Add cancel/pause/resume semantics inside a running Whisper job. Current jobs
  are persisted, but an application restart marks an in-process job interrupted
  and lets the user retry it.
- Add media tags, search and playlists if the local library becomes large.
- Add optional PWA/offline browser shell if tablet/mobile use becomes important.
- Add audit-log UI filtering/export if household administration needs grow.

## Deliberately deferred

- React/Vue migration
- microservices
- Redis/Celery
- external database server
- complex agent frameworks

Flask + SQLite + vanilla JavaScript + a small local worker pool remains the
intended architecture for the home/LAN workload.
