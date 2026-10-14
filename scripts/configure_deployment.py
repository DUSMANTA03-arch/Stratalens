"""Run locally in an interactive terminal; token input is hidden and never logged."""

import getpass
import os
import re
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
choice = parser.add_mutually_exclusive_group()
choice.add_argument("--vercel", action="store_true", help="Configure only Vercel deployment access")
choice.add_argument("--github", action="store_true", help="Configure only private repository publication access")
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / ".env"
text = path.read_text() if path.exists() else ""
print(
    "Paste each deployment token privately. Input is hidden. Enter leaves an existing value unchanged."
)
keys = ["VERCEL_TOKEN"] if args.vercel else ["GITHUB_TOKEN"] if args.github else ["GITHUB_TOKEN", "RENDER_API_KEY", "SUPABASE_ACCESS_TOKEN"]
for key in keys:
    value = getpass.getpass(key + ": ").strip()
    if not value:
        continue
    if any(c in value for c in "\n\r\"'"):
        raise SystemExit("Unexpected token characters; no changes saved.")
    line = key + "=" + value
    pattern = r"^" + key + r"=.*$"
    if re.search(pattern, text, re.M):
        text = re.sub(pattern, lambda m: line, text, flags=re.M)
    else:
        text = text.rstrip() + "\n" + line + "\n"
with os.fdopen(
    os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
) as stream:
    stream.write(text)
os.chmod(path, 0o600)
print(
    "Saved locally to .env. Do not commit this file or copy deployment tokens to application environment settings."
)
