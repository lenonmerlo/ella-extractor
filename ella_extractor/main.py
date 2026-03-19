from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from ella_extractor.routers.banco_do_brasil import router as banco_do_brasil_router
from ella_extractor.routers.banco_do_brasil_bank_statement import router as banco_do_brasil_bank_statement_router
from ella_extractor.routers.bradesco_bank_statement import router as bradesco_router
from ella_extractor.routers.bradesco_fatura_mensal_v1 import router as bradesco_fatura_mensal_v1_router
from ella_extractor.routers.c6_bank_statement import router as c6_router
from ella_extractor.routers.c6_invoice import router as c6_invoice_router
from ella_extractor.routers.itau_bank_statement import router as itau_bank_statement_router
from ella_extractor.routers.itau_latam_pass import router as itau_latam_pass_router
from ella_extractor.routers.itau_personnalite import router as itau_personnalite_router
from ella_extractor.routers.nubank_bank_statement import router as nubank_router
from ella_extractor.routers.santander import router as santander_router
from ella_extractor.routers.sicredi import router as sicredi_router


logger = logging.getLogger("ella-extractor")


def create_app() -> FastAPI:
    app = FastAPI(title="ELLA PDF Extractor (Local Test Service)")

    @app.on_event("startup")
    async def log_docs_urls() -> None:
        base_url = os.getenv("EXTRACTOR_BASE_URL", "http://localhost:8000").rstrip("/")
        startup_logger = logging.getLogger("uvicorn.error")
        bb_routes = sorted(
            route.path
            for route in app.routes
            if hasattr(route, "path") and "banco-do-brasil" in route.path
        )
        if app.docs_url:
            docs_msg = f"Swagger UI: {base_url}{app.docs_url}"
            logger.info(docs_msg)
            startup_logger.info(docs_msg)
        if app.openapi_url:
            openapi_msg = f"OpenAPI JSON: {base_url}{app.openapi_url}"
            logger.info(openapi_msg)
            startup_logger.info(openapi_msg)
        if bb_routes:
            startup_logger.info("Banco do Brasil routes loaded: %s", ", ".join(bb_routes))

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
    app.include_router(itau_latam_pass_router)
    app.include_router(bradesco_fatura_mensal_v1_router)
    app.include_router(itau_bank_statement_router)
    app.include_router(banco_do_brasil_router)
    app.include_router(banco_do_brasil_bank_statement_router)
    app.include_router(sicredi_router)
    app.include_router(santander_router)
    app.include_router(c6_invoice_router)
    app.include_router(c6_router)
    app.include_router(nubank_router)
    app.include_router(bradesco_router)

    return app


app = create_app()
