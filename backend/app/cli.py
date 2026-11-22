"""Operator commands.

python -m app.cli reconcile [--account ID] [--dry-run]   exit 1 if drift was found in a dry run
python -m app.cli retry-dead                              put dead events back in the queue
"""

import argparse
import sys

import structlog

from app.core.config import load_settings
from app.core.db import connect
from app.core.logging import configure_logging
from app.modules.accounts import repository as accounts
from app.modules.inbox import repository as inbox
from app.modules.reconcile.service import reconcile_account

log = structlog.get_logger()


def list_account_ids(conn) -> list[str]:
    ids, after = [], ""
    while page := accounts.list_page(conn, after=after, limit=500, deleted=False):
        ids += [a.external_id for a in page]
        after = page[-1].external_id
    conn.commit()
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("reconcile", help="recompute usage from raw events")
    rec.add_argument("--account", help="one account id (default: all)")
    rec.add_argument("--dry-run", action="store_true", help="report drift, change nothing")
    commands.add_parser("retry-dead", help="requeue events that exhausted their retries")
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level)
    with connect(settings) as conn:
        if args.command == "retry-dead":
            with conn.transaction():
                count = inbox.requeue_dead(conn)
            log.info("dead_events_requeued", count=count)
            return 0

        account_ids = [args.account] if args.account else list_account_ids(conn)
        drifted = 0
        for account_id in account_ids:
            report = reconcile_account(conn, account_id, dry_run=args.dry_run)
            drifted += len(report.drift)
        return 1 if (args.dry_run and drifted) else 0


if __name__ == "__main__":
    sys.exit(main())
