"""Move the backend to port 5001 and make all tooling agree.

Root cause of the blank pages: macOS **AirPlay Receiver** binds port 5000 and
answers with `403 Forbidden` / `Server: AirTunes`. Any request to
http://127.0.0.1:5000 therefore never reaches Flask, so every page looked empty
while the backend was in fact not running at all.

5001 avoids that reserved port permanently, so this script updates the single
source of truth (wsgi.py default), the Vite dev proxy, the health checks in
start-all.sh, and the README examples.
"""

import pathlib
import re

ROOT = pathlib.Path("/Users/aryanchaubey/Desktop/KnowGraph-AI")


def patch(path: pathlib.Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"PATTERN NOT FOUND in {path.name}:\n{old[:160]}")
    path.write_text(text.replace(old, new, count))
    print(f"  patched {path.name}")


# 1. Backend default port -----------------------------------------------------
patch(
    ROOT / "backend" / "wsgi.py",
    'host = os.getenv("HOST", "127.0.0.1")\n    port = int(os.getenv("PORT", "5000"))',
    '# Default 5001, not 5000: macOS AirPlay Receiver owns 5000 and answers with\n'
    '# 403/`Server: AirTunes`, which silently shadows the API. Override with PORT.\n'
    '    host = os.getenv("HOST", "127.0.0.1")\n'
    '    port = int(os.getenv("PORT", "5001"))',
)

# 2. Vite proxy target --------------------------------------------------------
patch(
    ROOT / "frontend" / "vite.config.js",
    "target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5000',",
    "// Port 5001 by default — 5000 is reserved by macOS AirPlay Receiver.\n"
    "        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5001',",
)

# 3. start-all.sh — header, checks and summary -------------------------------
start_all = ROOT / "start-all.sh"
text = start_all.read_text()
text = text.replace("Backend        (Flask on :5000)", "Backend        (Flask on :5001)")
text = text.replace("http://127.0.0.1:5000", "http://127.0.0.1:5001")
text = text.replace('ok "backend is already running on :5000"', 'ok "backend is already running on :5001"')
start_all.write_text(text)
print("  patched start-all.sh")

# 4. README examples ---------------------------------------------------------
readme = ROOT / "README.md"
rtext = readme.read_text()
rtext = rtext.replace("http://127.0.0.1:5000", "http://127.0.0.1:5001")
rtext = rtext.replace("-b 127.0.0.1:5000", "-b 127.0.0.1:5001")
rtext = rtext.replace(
    "| Port 5000 already in use (macOS AirPlay) | Start with `PORT=5001` and set `VITE_API_TARGET=http://127.0.0.1:5001`. |",
    "| Pages look empty / all API calls return 403 | macOS AirPlay Receiver owns port 5000. The backend defaults to **5001** for this reason — check `curl http://127.0.0.1:5001/api/health`. |",
)
readme.write_text(rtext)
print("  patched README.md")

# 5. .env.example note -------------------------------------------------------
env = ROOT / "backend" / ".env.example"
etext = env.read_text()
if "PORT=" not in etext:
    etext = etext.replace(
        "APP_ENV=development",
        "# Backend port. 5000 is reserved by macOS AirPlay Receiver, so the default is 5001.\nPORT=5001\n\nAPP_ENV=development",
    )
    env.write_text(etext)
    print("  patched .env.example")

print("port migration applied")
