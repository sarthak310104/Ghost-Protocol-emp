from fastapi import FastAPI

from app.api.routes import admin, bottlenecks, deployments, incidents, ingest

app = FastAPI(
    title="Ghost Protocol",
    description=(
        "Behavioral digital twin and incident engineering platform. "
        "Ingestion-based (OTLP), self-hosted per company. Implements no "
        "reasoning itself -- see the optional reasoning-integration module "
        "for connecting an external analysis service."
    ),
    version="0.1.0",
)

app.include_router(admin.router, tags=["admin"])
app.include_router(ingest.router, tags=["ingestion"])
app.include_router(deployments.router, tags=["deployments"])
app.include_router(incidents.router, tags=["incidents"])
app.include_router(bottlenecks.router, tags=["bottlenecks"])


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
