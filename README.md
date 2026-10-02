# Media Dictation

A local web app for sentence-by-sentence YouTube dictation practice.

## Features

- Paste a YouTube URL and automatically fetch timestamped captions.
- Prefer English captions when available.
- Merge short YouTube caption fragments into sentence-like practice units.
- Play only the current sentence and pause automatically at its end.
- Keep the source sentence hidden while you type.
- Keyboard-first dictation workflow.
- Press Enter to correct only the first current error; other typed text stays in place.
- Detect substitutions, missing words, and extra words using sequence alignment.
- A fully correct sentence stays on the current sentence instead of auto-advancing.
- Optional on-demand Simplified Chinese translation through the OpenAI Responses API.
- Click any word in the revealed source sentence to get a context-aware Chinese meaning.
- Save looked-up words into a persistent SQLite vocabulary book with their source sentence.
- Lightweight local SQLite history for sessions, dictation attempts, errors, progress, translations, word lookups, and vocabulary.
- Learning Center at `/learning` with daily summary, overall report, frequent errors, performance estimate, practice history, and resume links.
- Resume unfinished practice from the earliest sentence that has not yet been completed correctly.
- Optional proxy support for cloud environments such as GitHub Codespaces.

### Keyboard shortcuts

- **Ctrl (press and release by itself):** replay the current sentence.
- **Enter:** check the current answer.
  - If there is a wrong word, only that word is replaced with the correct word.
  - If a word is missing, only the missing word is inserted.
  - If an extra word is present, only that extra word is removed.
  - Press Enter again to correct the next error.
  - If the whole sentence is correct, the app stays on the current sentence.
- **Ctrl+H:** show/hide the original sentence.
- **Tab / Shift+Tab:** next / previous sentence.

Answer checking ignores capitalization and all punctuation, including commas, periods, quotation marks, apostrophes, and hyphens. Only letters and numbers participate in comparison.

## Windows

1. Install Python 3.
2. Clone this repository.
3. Double-click `start_windows.bat`.
4. The browser should open `http://127.0.0.1:8765`.
5. Paste a YouTube URL and click **获取字幕并开始**.

Local execution normally needs no proxy because requests leave through your own Internet connection.

## Linux / macOS

```bash
chmod +x start_linux_mac.sh
./start_linux_mac.sh
```

Then open `http://127.0.0.1:8765`.

## Manual start

```bash
python -m pip install -r requirements.txt
python app.py
```

## Learning Center and resume

Open:

```
http://127.0.0.1:8765/learning
```

The main dictation page also has a **学习中心** button.

The Learning Center shows:

- today's completed sentences, correction count, and first-pass accuracy;
- cumulative completed sentences;
- an internal listening-dictation performance score and label;
- today's and cumulative frequent error words;
- a vocabulary book containing saved words, contextual Chinese meanings, and source sentences;
- recent practice sessions with progress and error counts;
- a **继续练习** button for every unfinished session.

Resume is based on the earliest sentence in that saved session that has not yet received a fully-correct Enter check. The SQLite file persists across days, so an unfinished practice can be continued later as long as `data/media_dictation.db` is kept.

The performance estimate is intentionally **not labeled as CEFR**. The source material is not standardized for difficulty, so claiming A2/B1/B2 from ordinary podcast dictation data would be misleading. The current estimate uses first-pass accuracy, correction frequency, and sample size. A standardized placement test can be added later if CEFR estimation is desired.

## Clickable words and vocabulary book

After you reveal the source sentence, every word is clickable.

Clicking a word:

1. sends the word together with the current sentence to the local Flask backend;
2. asks the configured low-cost OpenAI model for the word's concise Chinese meaning **in that sentence**;
3. caches the result in SQLite so the same word in the same sentence does not call the API again;
4. shows an **加入生词本** button.

Saved words appear in the **生词本** section of:

```
http://127.0.0.1:8765/learning
```

The vocabulary entry stores the word, contextual Chinese meaning, source sentence, and source video information.

## Local SQLite data

The app automatically creates:

```
data/media_dictation.db
```

No separate database installation is required; Python's built-in `sqlite3` module is used.

The database intentionally stores only a small set of learning data:

- `practice_sessions`: video ID, source URL, language, subtitle type, number of practice segments, current progress, and timestamps.
- `attempts`: each Enter check, sentence index/text, the answer before correction, event type (`replace`, `missing`, `extra`, or `correct`), and the wrong/correct word when applicable.
- `translations`: English source sentence, Chinese translation, model, and timestamps.
- `word_translations`: cached context-aware word lookups, keyed by normalized word plus source sentence.
- `vocabulary`: saved vocabulary words with Chinese meaning, source sentence, source video, and timestamps.

Saved translations are reused across app restarts, so clicking **中文翻译** for a sentence that is already in SQLite does not call the OpenAI API again.

The database is local and ignored by Git. To use a different location, set:

```env
MEDIA_DICTATION_DB=D:/somewhere/media_dictation.db
```

A small summary endpoint is available at:

```
http://127.0.0.1:8765/api/stats
```

It reports total sessions, completed sentences, recorded errors, and cached translations.

## Optional OpenAI Chinese translation

Translation is **on demand**. The app calls the OpenAI API only when you click **中文翻译** for the current sentence.

The API key stays in the Flask backend and is never sent to browser JavaScript.

1. Copy `.env.example` to `.env`.
2. Put your API key in `.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here

# Full-sentence translation: cheaper Flex processing
OPENAI_TRANSLATION_MODEL=gpt-5.6-luna
OPENAI_TRANSLATION_SERVICE_TIER=flex
OPENAI_TRANSLATION_TIMEOUT_SECONDS=45

# Clickable word lookup: normal real-time/default processing
OPENAI_WORD_MODEL=gpt-5.6-luna
OPENAI_WORD_SERVICE_TIER=default
OPENAI_WORD_TIMEOUT_SECONDS=15
```

3. Restart the app.

By default, full-sentence translation uses `gpt-5.6-luna` with `service_tier=flex` and reasoning disabled (`effort=none`) to reduce cost. Clickable word lookup also uses `gpt-5.6-luna`, but stays on the normal `default` service tier for faster interaction.

The app uses the OpenAI **Responses API**. Full-sentence Flex translation has a 45-second backend timeout and a 55-second browser timeout. Word lookup keeps a shorter 15-second backend timeout and 20-second browser timeout. If translation appears stuck, update dependencies with `python -m pip install -U -r requirements.txt` and check the visible error message. A Codex model can technically be selected by changing the model environment variable if your API project has access, but Codex is optimized for coding and is not recommended for routine sentence translation.

You can verify whether translation is configured:

```bash
curl http://127.0.0.1:8765/api/health
```

Look for:

```json
{
  "translation_enabled": true,
  "translation_model": "gpt-5.6-luna",
  "translation_service_tier": "flex",
  "translation_timeout_seconds": 45,
  "word_model": "gpt-5.6-luna",
  "word_service_tier": "default",
  "word_timeout_seconds": 15
}
```

## GitHub Codespaces and YouTube IP blocking

YouTube frequently blocks IP ranges owned by cloud providers. GitHub Codespaces runs in a cloud environment, so a video can have perfectly valid captions and still fail with an IP-blocking error. The same video may work locally because your local copy uses your residential/office IP.

This is a network-origin problem, not a missing-caption problem.

### Option A: Webshare rotating residential proxy

The app automatically enables Webshare when these environment variables are present:

- `YT_WEBSHARE_PROXY_USERNAME`
- `YT_WEBSHARE_PROXY_PASSWORD`
- `YT_WEBSHARE_PROXY_LOCATIONS` — optional, defaults to `us`; comma-separated values such as `us,ca`

For Codespaces, store the username and password as **Codespaces repository secrets**, not in source code.

After the variables are available, restart the app. Check the active mode with:

```bash
curl http://127.0.0.1:8765/api/health
```

Expected result:

```json
{"ok":true,"proxy_mode":"webshare"}
```

### Option B: Any HTTP/HTTPS proxy

Set one or both:

- `YT_HTTP_PROXY`
- `YT_HTTPS_PROXY`

Example format:

```
http://username:password@proxy.example.com:8080
```

Then `/api/health` should report:

```json
{"ok":true,"proxy_mode":"generic"}
```

With no proxy variables it reports `direct`.

## Notes

This project uses `youtube-transcript-api`, which accesses YouTube caption data through an undocumented YouTube endpoint. Cloud-provider IP blocking is a known limitation. The upstream project recommends rotating residential proxies for cloud deployments.

Do not commit proxy credentials, YouTube cookies, OpenAI API keys, or other account credentials into this repository. The local `.env` file is ignored by Git.
