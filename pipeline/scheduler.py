"""APScheduler orchestrator — registers all fetcher cron jobs and runs a health endpoint.

Usage:
    python -m pipeline.scheduler
"""

import asyncio
import json
import logging
import signal
import time
from datetime import datetime, timezone

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline.config import PipelineConfig
from pipeline.db import close_pool, create_pool, execute_schema, log_pipeline_run

logger = logging.getLogger("pipeline.scheduler")

# ---------------------------------------------------------------------------
# Schedule registry — each entry maps a logical fetcher name to its cron
# expression and the import path for the fetcher class.
#
# Fetchers from #85 and #86 are registered here but imported lazily so the
# scheduler can start even before those modules are implemented.
# ---------------------------------------------------------------------------

SCHEDULE_REGISTRY: list[dict] = [
    # Taiwan market fetchers (#85)
    {"name": "twse_mi_index",       "cron": "*/30 9-14 * * 1-5", "module": "pipeline.fetchers.twse",    "class": "TwseMiIndexFetcher"},
    {"name": "twse_stock_day_all",  "cron": "0 16 * * 1-5",      "module": "pipeline.fetchers.twse",    "class": "TwseStockDayAllFetcher"},
    {"name": "twse_t187ap03",       "cron": "0 1 * * 1",         "module": "pipeline.fetchers.twse",    "class": "TwseCompanyInfoFetcher"},
    {"name": "finmind_stock_info",  "cron": "0 2 * * 1",         "module": "pipeline.fetchers.finmind", "class": "FinMindStockInfoFetcher"},
    {"name": "sitca_holdings",      "cron": "0 9 20 * *",        "module": "pipeline.fetchers.sitca",   "class": "SitcaFetcher"},
    # International fetchers (#86)
    {"name": "finnhub_fund_holdings", "cron": "0 6 * * 6",       "module": "pipeline.fetchers.finnhub_", "class": "FinnhubFundFetcher"},
    {"name": "yfinance_us_stocks",    "cron": "0 6 * * 1-5",     "module": "pipeline.fetchers.yfinance_", "class": "YfinanceFetcher"},
    {"name": "fx_rates",              "cron": "0 9 * * 1-5",     "module": "pipeline.fetchers.fx",      "class": "FxRateFetcher"},
    # Transformers
    {"name": "weight_calculator",     "cron": "0 17 * * 1-5",    "module": "pipeline.transformers.weight_calculator", "class": "WeightCalculator"},
]

MISFIRE_GRACE_TIME = 600  # 10 minutes — allow jobs that missed their window


def _parse_cron(expr: str) -> dict:
    """Parse a 5-field cron expression into CronTrigger kwargs."""
    parts = expr.split()
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _try_import_fetcher(module_path: str, class_name: str):
    """Lazily import a fetcher class.  Returns None if the module doesn't exist yet."""
    try:
        mod = __import__(module_path, fromlist=[class_name])
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Fetcher %s.%s not available: %s", module_path, class_name, exc)
        return None


class PipelineScheduler:
    """Orchestrates all pipeline fetchers via APScheduler."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.scheduler = AsyncIOScheduler(timezone=self.config.scheduler_timezone)
        self.pool = None
        self._start_time = time.monotonic()
        self._registered_fetchers: list[str] = []
        self._last_run_time: str | None = None
        self._health_app: web.Application | None = None
        self._health_runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Initialize pool, run migration, register jobs, start scheduler + health."""
        # 1. DB pool + schema
        self.pool = await create_pool(self.config.postgres_url)
        await execute_schema(self.pool)
        logger.info("Schema migration complete")

        # 2. Register fetcher jobs
        for entry in SCHEDULE_REGISTRY:
            fetcher_cls = _try_import_fetcher(entry["module"], entry["class"])
            if fetcher_cls is None:
                continue

            fetcher = fetcher_cls()
            cron_kwargs = _parse_cron(entry["cron"])
            trigger = CronTrigger(timezone=self.config.scheduler_timezone, **cron_kwargs)

            self.scheduler.add_job(
                self._run_fetcher,
                trigger=trigger,
                args=[fetcher, entry["name"]],
                id=entry["name"],
                name=entry["name"],
                misfire_grace_time=MISFIRE_GRACE_TIME,
                replace_existing=True,
            )
            self._registered_fetchers.append(entry["name"])
            logger.info("Registered: %s (%s)", entry["name"], entry["cron"])

        # 3. Start scheduler
        self.scheduler.start()
        logger.info(
            "Scheduler started — %d fetchers registered", len(self._registered_fetchers)
        )

        # 4. Start health endpoint
        await self._start_health_server()

    async def stop(self) -> None:
        """Graceful shutdown — stop scheduler, close pool, stop health server."""
        logger.info("Shutting down...")
        self.scheduler.shutdown(wait=False)

        if self._health_runner:
            await self._health_runner.cleanup()

        if self.pool:
            await close_pool(self.pool)
            logger.info("Connection pool closed")

    async def _run_fetcher(self, fetcher, name: str) -> None:
        """Execute a single fetcher with error isolation."""
        logger.info("Running: %s", name)
        try:
            count = await fetcher.run(self.pool)
            self._last_run_time = datetime.now(timezone.utc).isoformat()
            logger.info("Completed: %s — %d rows", name, count)
        except Exception:
            self._last_run_time = datetime.now(timezone.utc).isoformat()
            logger.exception("Failed: %s", name)
            # Error is already logged to pipeline_run by BaseFetcher.run()
            # Scheduler continues — other fetchers are unaffected.

    # -- Health endpoint --------------------------------------------------

    async def _start_health_server(self, port: int = 8080) -> None:
        """Start a lightweight HTTP health check on the given port."""
        self._health_app = web.Application()
        self._health_app.router.add_get("/health", self._health_handler)

        self._health_runner = web.AppRunner(self._health_app)
        await self._health_runner.setup()
        site = web.TCPSite(self._health_runner, "0.0.0.0", port)
        await site.start()
        logger.info("Health endpoint listening on :%d/health", port)

    async def _health_handler(self, request: web.Request) -> web.Response:
        uptime_secs = int(time.monotonic() - self._start_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)

        body = {
            "status": "ok",
            "fetchers": len(self._registered_fetchers),
            "registered": self._registered_fetchers,
            "last_run": self._last_run_time,
            "uptime": f"{hours}h{minutes}m{seconds}s",
        }
        return web.json_response(body)


async def main() -> None:
    """Entry point — start scheduler and wait for shutdown signal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = PipelineConfig.from_env()
    sched = PipelineScheduler(config)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await sched.start()
    logger.info("Pipeline scheduler running — press Ctrl+C to stop")
    await stop_event.wait()
    await sched.stop()


if __name__ == "__main__":
    asyncio.run(main())
