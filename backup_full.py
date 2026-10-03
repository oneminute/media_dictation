from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from media_service import media_dir
from storage import database_path


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path("backups") / f"full_{stamp}"
    root.mkdir(parents=True, exist_ok=False)

    db_src = database_path()
    db_dst = root / "media_dictation.db"

    source = sqlite3.connect(db_src)
    destination = sqlite3.connect(db_dst)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    media_src = media_dir()
    media_dst = root / "media"
    if media_src.exists():
        shutil.copytree(media_src, media_dst)

    print(f"Full backup created: {root.resolve()}")


if __name__ == "__main__":
    main()
