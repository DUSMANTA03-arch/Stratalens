import asyncio
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from analyst.models import ResearchRequest
from analyst.charts import prepare_chart
from analyst.providers import ProviderError, Providers
from analyst.sample import SAMPLE_QUESTION, SampleProviders
from analyst.workflow import build_workflow, public_result
from analyst.auth import require_owner, router as auth_router
from analyst.workspace_api import router as workspace_router
from analyst.workspace_store import configured
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
RUN_TIMEOUT = 240
load_dotenv(ROOT / ".env")
app = FastAPI(title="StrataLens", version="0.3.0", docs_url=None, redoc_url=None)
app.include_router(auth_router)
app.include_router(workspace_router)
logger = logging.getLogger("analyst")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > 4_000_000:
                    raise HTTPException(413, "Request too large. Attach up to three smaller chart images.")
            return message

        await self.app(scope, limited_receive if scope["type"] == "http" else receive, send)


app.add_middleware(BodyLimitMiddleware)


@app.middleware("http")
async def security_headers(request, call_next):
    from fastapi.responses import JSONResponse
    if request.method in {'POST','PATCH','DELETE','PUT'}:
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail':'Cross-origin request rejected.'},status_code=403)
    size = request.headers.get("content-length", "0")
    if request.method == "POST" and size.isdigit() and int(size) > 4_000_000:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Request too large. Attach up to three smaller chart images."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    supabase_origin = os.getenv('SUPABASE_URL','').rstrip('/')
    response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: {supabase_origin}; connect-src 'self' {supabase_origin}; frame-src 'self' blob: {supabase_origin}; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control']='no-store'
    return response


@app.get("/")
async def index():
    return FileResponse(ROOT / "assets" / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "workspace_ready": configured(), "sample_available": True}


@app.get('/api/sample')
async def sample():
    provider=SampleProviders()
    state=await build_workflow(provider).ainvoke({'question':SAMPLE_QUESTION,'mode':'sample'})
    return public_result(state,provider,0)


@app.get('/api/sample/export.pdf')
async def sample_pdf():
    from analyst.exports import brief_pdf
    from fastapi.responses import Response
    content=await asyncio.to_thread(brief_pdf,await sample())
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="stratalens-SYNTHETIC.pdf"'})


@app.post("/api/research")
async def research(body: ResearchRequest, _legacy_access_code: str = "", owner=Depends(require_owner)):
    if not body.question.strip() or len(body.question.strip()) < 10:
        raise HTTPException(422, "Enter a research question of at least 10 non-padding characters.")
    if body.mode == 'live':
        raise HTTPException(410, 'Live research now uses /api/v2/research and durable jobs. Use the workspace UI.')
    if body.mode == "live" and not all(os.getenv(k) for k in ("GEMINI_API_KEY", "TAVILY_API_KEY")):
        raise HTTPException(503, "Live research is not configured. Add the provider keys to deployment secrets.")
    try:
        charts = [await asyncio.to_thread(prepare_chart, chart) for chart in body.charts] if body.mode == "live" else []
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    providers = SampleProviders() if body.mode == "sample" else Providers()

    async def stream():
        started = time.monotonic()
        state = {"question": SAMPLE_QUESTION if body.mode == "sample" else body.question.strip(), "mode": body.mode, "charts": charts}
        queue = asyncio.Queue()

        async def produce():
            partial = False
            try:
                async with asyncio.timeout(RUN_TIMEOUT):
                    graph = build_workflow(providers, started)
                    async for update in graph.astream(state, stream_mode="updates"):
                        for stage, values in update.items():
                            state.update(values)
                            handoff = {
                                "planner": f"Passing {len(state.get('plan', {}).get('queries', []))} search queries to retrieval",
                                "researcher": f"Passing {len(state.get('sources', []))} readable sources to chart reading and evidence extraction",
                                "chart_reader": f"Passing {len(state.get('claims', []))} chart/source observations to evidence extraction",
                                "analyst": f"Passing {len(state.get('claims', []))} quoted claims to validation",
                                "validator": f"Passing {len(state.get('assessments', []))} assessments and {len(state.get('calculations', []))} calculations to writing",
                                "writer": f"Assembled report from {len(state.get('claims', []))} claims and {len(state.get('sources', []))} sources",
                            }.get(stage, "Updating the next agent")
                            await queue.put({"type": "stage", "stage": stage, "round": state.get("rounds", 0),
                                "plan": state.get("plan"), "sources": len(state.get("sources", [])),
                                "claims": len(state.get("claims", [])), "warnings": state.get("warnings", []),
                                "handoff": handoff})
                    partial = bool(state.get("partial")) or not bool(state.get("report", {}).get("sections"))
            except asyncio.CancelledError:
                raise
            except (TimeoutError, ProviderError) as exc:
                partial = True
                message = "Time limit reached. Available evidence is shown below." if isinstance(exc, TimeoutError) else str(exc)
                state["warnings"] = state.get("warnings", []) + [message]
            except Exception as exc:
                partial = True
                # Log only the exception class, never prompts, credentials or provider payloads.
                logger.error("Research failed: %s", type(exc).__name__)
                state["warnings"] = state.get("warnings", []) + ["Research stopped unexpectedly. Available evidence has been retained."]
            await queue.put({"type": "result", "data": public_result(state, providers, time.monotonic() - started, partial)})
            await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            yield json.dumps({"type": "start", "mode": body.mode}) + "\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except TimeoutError:
                    event = {"type": "heartbeat", "elapsed": round(time.monotonic() - started)}
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await providers.close()

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
