"""
Toutes les méthodes liées à FastAPI pour les requetes API.

- /api/health
- /api/status
- /api/council/query
- /api/council/query/stream
- /api/council/sessions
- /api/council/sessions/{id}
- /api/config/nodes
"""
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from .config import get_config
from .council import get_orchestrator
from .llm_service import get_llm_service, shutdown_llm_service
from .models import (
    CouncilSession,
    CouncilStatusResponse,
    HealthCheckResponse,
    LLMNodeInfo,
    LLMStatus,
    QueryRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Booting LLM Council API...")

    cfg = get_config()
    logger.info(f"Council members: {len(cfg.council_members)}")
    logger.info(f"Chairman: {cfg.chairman.name} ({cfg.chairman.model})")

    # Startup probe
    svc = get_llm_service()
    nodes = await svc.check_all_nodes_health()
    online = sum(1 for n in nodes if n.status == LLMStatus.ONLINE)
    logger.info(f"Nodes online: {online}/{len(nodes)}")
    yield
    logger.info("Shutting down LLM Council API...")
    await shutdown_llm_service()


app = FastAPI(
    title="LLM Council",
    description="Local multi-LLM council with peer review + chairman synthesis",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Check de verification
@app.get("/api/health", response_model=HealthCheckResponse)
async def health_check():
    svc = get_llm_service()
    nodes = await svc.check_all_nodes_health()
    all_ok = all(n.status == LLMStatus.ONLINE for n in nodes)

    return HealthCheckResponse(status="healthy" if all_ok else "degraded", nodes=nodes)


@app.get("/api/status", response_model=CouncilStatusResponse)
async def status():
    cfg = get_config()
    orch = get_orchestrator()
    svc = get_llm_service()

    nodes = await svc.check_all_nodes_health()
    council_nodes = [n for n in nodes if not n.is_chairman]
    chairman_node = next((n for n in nodes if n.is_chairman), None)

    if chairman_node is None:
        chairman_node = LLMNodeInfo(
            name=cfg.chairman.name,
            host=cfg.chairman.host,
            port=cfg.chairman.port,
            model=cfg.chairman.model,
            is_chairman=True,
            status=LLMStatus.OFFLINE,
        )

    all_ok = all(n.status == LLMStatus.ONLINE for n in nodes)
    return CouncilStatusResponse(
        active_sessions=orch.active_sessions,
        total_sessions=orch.total_sessions,
        council_members=council_nodes,
        chairman=chairman_node,
        system_status="operational" if all_ok else "degraded",
    )


# Requête post et get pour le conseil
@app.post("/api/council/query", response_model=CouncilSession)
async def council_query(req: QueryRequest):
    orch = get_orchestrator()
    try:
        return await orch.run_full_council(req.query)
    except Exception as e:
        logger.error(f"/api/council/query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/council/query/stream")
async def council_query_stream(req: QueryRequest):
    orch = get_orchestrator()

    async def stream():
        try:
            async for session in orch.run_council_streaming(req.query):
                payload = session.model_dump(mode="json")
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/council/sessions", response_model=List[CouncilSession])
async def sessions():
    return get_orchestrator().get_all_sessions()


@app.get("/api/council/sessions/{session_id}", response_model=CouncilSession)
async def session_by_id(session_id: str):
    session = get_orchestrator().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# Verif de la configuration
@app.get("/api/config/nodes")
async def config_nodes():
    cfg = get_config()

    council = [
        {
            "name": n.name,
            "host": n.host,
            "port": n.port,
            "model": n.model,
            "is_chairman": n.is_chairman,
            "api_url": n.api_url,
        }
        for n in cfg.council_members
    ]

    chair = {
        "name": cfg.chairman.name,
        "host": cfg.chairman.host,
        "port": cfg.chairman.port,
        "model": cfg.chairman.model,
        "is_chairman": True,
        "api_url": cfg.chairman.api_url,
    }

    return {"nodes": council + [chair]}


FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def root():
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    cfg = get_config()
    uvicorn.run("backend.main:app", host=cfg.api_host, port=cfg.api_port, reload=cfg.debug)