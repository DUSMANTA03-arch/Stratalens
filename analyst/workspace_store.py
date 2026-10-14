"""Small Supabase REST adapter. Service credentials never leave the server."""

import os
import asyncio
import hashlib
import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException


def configured():
    return all(
        os.getenv(k)
        for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    )


class Store:
    def __init__(self, owner):
        self.owner = owner
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=45)
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()
        self.client = None

    async def request(self, method, path, **kwargs):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        headers.update(kwargs.pop("headers", {}))
        try:
            if self.client is not None:
                response = await self.client.request(method, self.url + path, headers=headers, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=45) as client:
                    response = await client.request(method, self.url + path, headers=headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 404
                and any(
                    name in path
                    for name in (
                        "review_workspace_observation",
                        "patch_workspace_record",
                        "workspace_reliability_ready",
                    )
                )
            ):
                raise HTTPException(
                    503,
                    "The reliability database upgrade is not installed. Back up your workspace and apply migrations/002_reliability.sql in Supabase before using reviews, notes or period assignment.",
                ) from exc
            raise HTTPException(
                503,
                "Workspace storage is unavailable. Check configuration or resume a paused Supabase project.",
            ) from exc
        return (
            response.json()
            if response.content and "json" in response.headers.get("content-type", "")
            else response.content
        )

    async def rpc(self, name, **values):
        return await self.request(
            "POST",
            "/rest/v1/rpc/" + name,
            json={"p_owner": self.owner, **{"p_" + k: v for k, v in values.items()}},
        )

    async def records(self, kind, **filters):
        result = []
        while True:
            rows = await self.request(
                "GET",
                "/rest/v1/workspace_records",
                params={
                    "owner_id": "eq." + self.owner,
                    "kind": "eq." + kind,
                    "order": "created_at.desc,id.asc",
                    "limit": "500",
                    "offset": len(result),
                    **filters,
                },
            )
            result.extend(rows)
            if len(rows) < 500:
                return result

    async def record(self, kind, record_id):
        rows = await self.records(kind, id="eq." + str(record_id))
        if not rows:
            raise HTTPException(404, "Record not found.")
        return rows[0]

    async def put(self, kind, data, record_id=None):
        row = {
            "id": record_id or str(uuid4()),
            "owner_id": self.owner,
            "kind": kind,
            "data": data,
        }
        rows = await self.request(
            "POST",
            "/rest/v1/workspace_records",
            json=row,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            params={"on_conflict": "id"},
        )
        return rows[0]

    async def new_job(self, kind, state, job_id=None):
        job = {
            "id": job_id or str(uuid4()),
            "owner_id": self.owner,
            "kind": kind,
            "state": state,
            "status": "queued",
        }
        rows = await self.request(
            "POST",
            "/rest/v1/workspace_jobs",
            json=job,
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
            params={"on_conflict": "id"},
        )
        return rows[0] if rows else (await self.jobs(job["id"]))[0]

    async def jobs(self, job_id=None):
        params = {
            "owner_id": "eq." + self.owner,
            "order": "created_at.desc",
            "limit": "100",
        }
        if job_id:
            params["id"] = "eq." + str(job_id)
        return await self.request("GET", "/rest/v1/workspace_jobs", params=params)

    async def pages(self, document_id, start=1, end=600):
        return await self.request(
            "GET",
            "/rest/v1/document_pages",
            params={
                "owner_id": "eq." + self.owner,
                "document_id": "eq." + str(document_id),
                "and": f"(page.gte.{start},page.lte.{end})",
                "order": "page.asc",
            },
        )

    async def signed_upload(self, path):
        data = await self.request(
            "POST",
            "/storage/v1/object/upload/sign/reports/" + quote(path, safe="/"),
            json={},
        )
        return (
            self.url + "/storage/v1" + data["url"]
            if data["url"].startswith("/")
            else data["url"]
        )

    async def selected_pages(self, document_id, numbers):
        if not numbers:
            return []
        return await self.request("GET", "/rest/v1/document_pages", params={
            "owner_id": "eq." + self.owner, "document_id": "eq." + str(document_id),
            "page": "in.(" + ",".join(str(int(n)) for n in numbers) + ")", "order": "page.asc",
        })

    async def signed_url(self, path):
        data = await self.request(
            "POST",
            "/storage/v1/object/sign/reports/" + quote(path, safe="/"),
            json={"expiresIn": 300},
        )
        return self.url + "/storage/v1" + data["signedURL"]

    async def blob(self, path):
        return await self.request(
            "GET", "/storage/v1/object/reports/" + quote(path, safe="/")
        )

    async def pdf_blob(self, path):
        cache = Path(tempfile.gettempdir()) / "stratalens-pdfs"
        target = cache / hashlib.sha256((self.url + "/" + path).encode()).hexdigest()
        if target.exists():
            try:
                return await asyncio.to_thread(target.read_bytes)
            except OSError:
                pass
        data = await self.blob(path)
        await self.cache_pdf(path, data)
        return data

    async def cache_pdf(self, path, data):
        # Disposable cache only; Supabase is the source of truth after restarts.
        def write():
            cache = Path(tempfile.gettempdir()) / "stratalens-pdfs"
            cache.mkdir(mode=0o700, exist_ok=True)
            target = (
                cache / hashlib.sha256((self.url + "/" + path).encode()).hexdigest()
            )
            files = sorted(
                (f for f in cache.iterdir() if f.is_file()),
                key=lambda f: f.stat().st_mtime,
            )
            size = sum(f.stat().st_size for f in files)
            for old in files:
                if size + len(data) <= 80_000_000:
                    break
                size -= old.stat().st_size
                old.unlink(missing_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)

        try:
            await asyncio.to_thread(write)
        except OSError:
            pass

    async def upload(self, path, content, mime="application/pdf"):
        await self.request(
            "POST",
            "/storage/v1/object/reports/" + quote(path, safe="/"),
            content=content,
            headers={"Content-Type": mime, "x-upsert": "true"},
        )

    async def remove_blob(self, path):
        await self.request(
            "DELETE", "/storage/v1/object/reports", json={"prefixes": [path]}
        )
        target = (
            Path(tempfile.gettempdir())
            / "stratalens-pdfs"
            / hashlib.sha256((self.url + "/" + path).encode()).hexdigest()
        )
        target.unlink(missing_ok=True)

    async def usage(self):
        return await self.request(
            "GET",
            "/rest/v1/workspace_usage",
            params={"owner_id": "eq." + self.owner, "order": "day.desc", "limit": "31"},
        )
