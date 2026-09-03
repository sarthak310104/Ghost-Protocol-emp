from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, bottlenecks, cohorts, deployments, incidents, ingest
from app.core.config import get_settings

settings = get_settings()

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

# Deliberately an explicit origin allowlist, never "*" -- credentialed
# (cookie-bearing) CORS requests can't legally use a wildcard origin per
# the CORS spec anyway, but being explicit here also means a
# misconfigured deployment fails closed (rejects unknown origins)
# instead of failing open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if settings.cookies_secure:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


app.include_router(admin.router, tags=["admin"])
app.include_router(auth.router, tags=["auth"])
app.include_router(ingest.router, tags=["ingestion"])
app.include_router(deployments.router, tags=["deployments"])
app.include_router(incidents.router, tags=["incidents"])
app.include_router(bottlenecks.router, tags=["bottlenecks"])
app.include_router(cohorts.router, tags=["cohorts"])


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}