# Media Dictation

A local web app for sentence-by-sentence YouTube dictation practice.

## Features

- Paste a YouTube URL and automatically fetch timestamped captions.
- Prefer English captions when available.
- Merge short YouTube caption fragments into sentence-like practice units.
- Play only the current sentence and pause automatically at its end.
- Keep the source sentence hidden while you type.
- Keyboard-first dictation workflow.
- Optional proxy support for cloud environments such as GitHub Codespaces.

### Keyboard shortcuts

- **Ctrl (press and release by itself):** replay the current sentence.
- **Enter:** check the current answer.
  - If there is an error, the caret/selection jumps to the first mismatching word.
  - If the answer is fully correct, the app automatically advances to and plays the next sentence.
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

Do not commit proxy credentials, YouTube cookies, or account credentials into this repository.
