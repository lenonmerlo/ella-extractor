from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from ella_extractor.routers.c6_bank_statement import router as c6_router
from ella_extractor.routers.itau_personnalite import router as itau_personnalite_router
from ella_extractor.routers.sicredi import router as sicredi_router


logger = logging.getLogger("ella-extractor")


def create_app() -> FastAPI:
    app = FastAPI(title="ELLA PDF Extractor (Local Test Service)")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "name": "ella-extractor",
            "version": os.getenv("VERSION", "dev"),
            "gitSha": os.getenv("GIT_SHA", "unknown"),
            "buildTime": os.getenv("BUILD_TIME", "unknown"),
        }

    app.include_router(itau_personnalite_router)
    app.include_router(sicredi_router)
    app.include_router(c6_router)

    return app


app = create_app()
