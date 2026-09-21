"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import SylvaSenseError, internal
from app.providers.registry import provider_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sylvasense")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    status = provider_status()
    log.info("SylvaSense %s starting", settings.version)
    log.info("Data mode: %s (%s)", status["mode"], status["indicator"])
    if status["simulated"]:
        log.warning(
            "No Earth Engine credential — results are SIMULATED and labelled as "
            "such. %s",
            status["earth_engine"]["next_step"],
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="SylvaSense API",
        version=settings.version,
        description=(
            "Forest carbon intelligence from Earth observation. Every result "
            "carries the sensor, model and date it came from."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    # --- Error contract -------------------------------------------------
    # A user must never see a bare 500. Everything that escapes a route is
    # converted into the same shape the UI knows how to render.

    @app.exception_handler(SylvaSenseError)
    async def _handled(_: Request, exc: SylvaSenseError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', [])[1:])}: {err.get('msg')}"
            for err in exc.errors()
        )
        error = SylvaSenseError(
            code="INVALID_REQUEST",
            title="THE REQUEST COULD NOT BE READ",
            detail="SylvaSense could not interpret the request the page sent.",
            causes=["a malformed area of interest", "an out-of-range year"],
            next_step="Redraw the area or reload the page, then try again.",
            status_code=422,
            technical=problems,
        )
        return JSONResponse(status_code=422, content=error.to_payload())

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")
        error = internal(f"{type(exc).__name__}: {exc}")
        return JSONResponse(status_code=500, content=error.to_payload())

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, object]:
        status = provider_status()
        return {
            "status": "ok",
            "version": settings.version,
            "data_mode": status["mode"],
            "simulated": status["simulated"],
        }

    return app


app = create_app()
