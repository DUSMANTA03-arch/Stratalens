"""Read-only backup before migration. Secrets and record contents never print."""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv


async def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    url = os.environ["SUPABASE_URL"].rstrip("/")
    headers = {
        "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }
    saved = {}
    async with httpx.AsyncClient(timeout=60) as client:
        for table in [
            "workspace_owners",
            "workspace_records",
            "document_pages",
            "workspace_jobs",
            "workspace_usage",
        ]:
            rows = []
            while True:
                order = {
                    "workspace_owners": "user_id",
                    "workspace_records": "id",
                    "document_pages": "document_id,page",
                    "workspace_jobs": "id",
                    "workspace_usage": "owner_id,day",
                }[table]
                r = await client.get(
                    url + "/rest/v1/" + table,
                    headers=headers,
                    params={"limit": 500, "offset": len(rows), "order": order},
                )
                if r.status_code != 200:
                    raise RuntimeError(
                        table
                        + ": backup request failed with HTTP "
                        + str(r.status_code)
                    )
                batch = r.json()
                rows += batch
                if len(batch) < 500:
                    break
            saved[table] = rows
            print(table + ": " + str(len(rows)) + " records")
    # Do not migrate while a job is active; this also avoids an inconsistent snapshot.
    if any(
        j.get("status") == "running"
        and (j.get("lease_until") or "") > datetime.now(timezone.utc).isoformat()
        for j in saved["workspace_jobs"]
    ):
        raise RuntimeError("Pause active jobs and repeat the backup before migration.")
    folder = root / "tmp/deployment"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / (
        "workspace-backup-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(saved, stream)
    print("Backup saved privately under tmp/deployment. No live data was changed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            "Preflight failed: "
            + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        )
        sys.exit(1)
