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
- Lightweight local SQLite history for sessions, dictation attempts, errors, progress, and translation cache.
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

Answer checking ignores capitalization and punctuation. Apostrophes inside words are preserved.

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
- recent practice sessions with progress and error counts;
- a **继续练习** button for every unfinished session.

Resume is based on the earliest sentence in that saved session that has not yet received a fully-correct Enter check. The SQLite file persists across days, so an unfinished practice can be continued later as long as `data/media_dictation.db` is kept.

The performance estimate is intentionally **not labeled as CEFR**. The source material is not standardized for difficulty, so claiming A2/B1/B2 from ordinary podcast dictation data would be misleading. The current estimate uses first-pass accuracy, correction frequency, and sample size. A standardized placement test can be added later if CEFR estimation is desired.

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
OPENAI_TRANSLATION_MODEL=gpt-4o-mini
```

3. Restart the app.

The default translation model is `gpt-4o-mini`, which is inexpensive and sufficient for short English-to-Chinese sentence translation. You can change `OPENAI_TRANSLATION_MODEL` without changing code.

The app uses the OpenAI **Responses API**. A Codex model can technically be selected by changing the model environment variable if your API project has access, but Codex is optimized for coding and is not recommended for routine sentence translation.

You can verify whether translation is configured:

```bash
curl http://127.0.0.1:8765/api/health
```

Look for:

```json
{
  "translation_enabled": true,
  "translation_model": "gpt-4o-mini"
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
