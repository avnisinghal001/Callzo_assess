"""Typed settings. Secrets have no defaults: a missing value fails at startup."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # An empty variable means "not set": compose passes optional ones through as "".
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    database_url: str
    webhook_secret: str = Field(min_length=16)
    api_key: str = Field(min_length=16)  # read-only usage API
    # Rotation: deploy the new value, keep the old one here until every client has switched.
    webhook_secret_previous: str | None = Field(default=None, min_length=16)
    api_key_previous: str | None = Field(default=None, min_length=16)
    admin_api_key_previous: str | None = Field(default=None, min_length=16)
    admin_api_key: str = Field(min_length=16)  # control plane and console; must differ
    # Opens the console without any sign-in. Only for localhost or behind an identity-aware proxy.
    console_open_access: bool = False
    # Comma-separated Host headers to accept; stops DNS-rebinding attacks on a local console.
    allowed_hosts: str = "*"
    enable_sandbox: bool = False  # lets the console inject synthetic events; keep off in production

    default_monthly_cap_minutes: int = Field(default=200, ge=0)
    log_level: str = "INFO"
    max_body_bytes: int = Field(default=64 * 1024, gt=0)
    max_attempts: int = Field(default=8, ge=1)
    claim_lease_seconds: float = Field(
        default=60.0, gt=0
    )  # a crashed worker's event is retried after this
    worker_poll_seconds: float = Field(default=0.2, gt=0)  # idle only; a busy worker never waits
    worker_heartbeat_seconds: float = Field(default=5.0, gt=0)
    worker_alive_file: str = "/tmp/worker-alive"  # touched by the loop; read by the health check
    fleet_report_seconds: float = Field(default=2.0, gt=0)
    stats_retention_days: int = Field(default=7, ge=1)
    docs_enabled: bool = True  # /docs and /openapi.json; turn off when publicly reachable

    # ---- Postgres connection pool (one pool per API process; see README "Connection budget") ----
    db_pool_min_size: int = Field(default=2, ge=1)  # kept warm
    db_pool_max_size: int = Field(default=8, ge=1)  # hard cap of connections per API process
    db_pool_timeout: float = Field(default=5.0, gt=0)  # max wait for a free connection
    # Requests allowed to wait for a connection; beyond it they fail fast (503). Starlette runs
    # sync routes in 40 threads, so max_size + max_waiting <= 40 keeps threads from starving.
    db_pool_max_waiting: int = Field(default=32, ge=1)  # NOT 0: psycopg treats 0 as unlimited
    db_pool_max_idle: float = Field(default=120.0, gt=0)  # close surplus idle connections
    db_pool_max_lifetime: float = Field(default=1800.0, gt=0)  # recycle (balances after failover)
    db_pool_reconnect_timeout: float = Field(default=60.0, gt=0)
    db_pool_num_workers: int = Field(default=3, ge=1)  # background pool maintenance threads
    db_connect_timeout: int = Field(default=5, ge=1)
    db_statement_timeout_ms: int = Field(default=30_000, ge=0)  # 0 disables
    db_idle_in_transaction_timeout_ms: int = Field(default=60_000, ge=0)  # frees leaked locks
    # Behind PgBouncer in transaction mode: no server-side prepared statements, and session
    # parameters cannot be sent at connect time (set them with ALTER ROLE instead).
    db_pgbouncer: bool = False

    @property
    def webhook_secrets(self) -> list[str]:
        return [s for s in (self.webhook_secret, self.webhook_secret_previous) if s]

    @property
    def reader_keys(self) -> list[str]:
        return [k for k in (self.api_key, self.api_key_previous) if k]

    @property
    def admin_keys(self) -> list[str]:
        return [k for k in (self.admin_api_key, self.admin_api_key_previous) if k]

    @model_validator(mode="after")
    def consistent(self) -> "Settings":
        readers = {self.api_key, self.api_key_previous} - {None}
        admins = {self.admin_api_key, self.admin_api_key_previous} - {None}
        if readers & admins:
            raise ValueError("API_KEY and ADMIN_API_KEY must be different")
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("DB_POOL_MIN_SIZE must not exceed DB_POOL_MAX_SIZE")
        return self


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
