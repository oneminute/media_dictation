from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


FILES = [
    Path("static/index.html"),
    Path("static/learning.html"),
    Path("static/review.html"),
]


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required for inline JavaScript syntax checks")

    failures = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        blocks = list(
            re.finditer(
                r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        inline_number = 0
        for match in blocks:
            attrs = match.group("attrs") or ""
            if re.search(r"\bsrc\s*=", attrs, flags=re.IGNORECASE):
                continue
            body = match.group("body")
            if not body.strip():
                continue
            inline_number += 1
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".js",
                encoding="utf-8",
                delete=False,
            ) as temp:
                temp.write(body)
                temp_path = temp.name
            try:
                proc = subprocess.run(
                    [node, "--check", temp_path],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if proc.returncode != 0:
                    failures.append(
                        f"{path} inline script {inline_number}:\n"
                        f"{proc.stdout}{proc.stderr}"
                    )
            finally:
                Path(temp_path).unlink(missing_ok=True)

    if failures:
        raise SystemExit("\n\n".join(failures))

    print("Inline JavaScript syntax checks passed.")


if __name__ == "__main__":
    main()
