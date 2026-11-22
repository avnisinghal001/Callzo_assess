from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.console import ConsoleFiles
from app.core.config import Settings, load_settings
from app.core.db import make_pool
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.metrics import Metrics
from app.core.middleware import RequestContext
from app.modules.accounts.router import router as accounts_router
from app.modules.audit.router import router as audit_router
from app.modules.fleet.reporter import FleetReporter
from app.modules.health.router import router as health_router
from app.modules.inbox.router import router as events_router
from app.modules.ops.router import router as ops_router
from app.modules.reconcile.router import router as reconcile_router
from app.modules.usage.router import router as usage_router
from app.modules.webhooks.router import router as webhooks_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = make_pool(settings)
        app.state.pool = pool
        reporter = FleetReporter(
            pool, lambda: app.state.metrics.pool_stats.stats(), settings.fleet_report_seconds
        )
        app.state.metrics = Metrics(pool, reporter.count)
        app.state.reporter = reporter
        reporter.start()
        yield
        reporter.stop()
        pool.close()

    app = FastAPI(
        title="Callzo usage metering",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.add_middleware(RequestContext)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[h.strip() for h in settings.allowed_hosts.split(",")],
        www_redirect=False,
    )
    install_error_handlers(app)
    app.include_router(webhooks_router)
    app.include_router(usage_router)
    app.include_router(accounts_router)
    app.include_router(events_router)
    app.include_router(reconcile_router)
    app.include_router(ops_router)
    app.include_router(audit_router)
    app.include_router(health_router)
    app.mount("/console", ConsoleFiles(), name="console")

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/console/")

    return app


def app_from_env() -> FastAPI:
    return create_app()
