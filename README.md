# Media Dictation

A local web app for sentence-by-sentence YouTube dictation practice.

## Features

- Paste a YouTube URL and automatically fetch timestamped captions.
- Prefer English captions when available.
- Merge short YouTube caption fragments into sentence-like practice units.
- Play only the current sentence and pause automatically at its end.
- Keep the source sentence hidden while you type.
- Keyboard-first dictation workflow.

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

## Notes

This project uses `youtube-transcript-api`, which accesses YouTube caption data. Some videos have no accessible captions, and YouTube can occasionally block or change transcript access.

Manually created captions usually produce better sentence boundaries than auto-generated captions.
