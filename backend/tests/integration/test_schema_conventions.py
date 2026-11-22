"""Conventions every table follows: uuid id, created_at, updated_at, deleted_at, metadata."""

import time

import psycopg.errors
import pytest

TABLES = [
    "accounts",
    "call_events",
    "calls",
    "usage_aggregate",
    "schema_migrations",
    "audit_log",
    "webhook_stats",
    "service_instances",
    "scheduled_jobs",
]


def test_no_table_escapes_the_conventions(conn):
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
    ).fetchall()
    assert sorted(r["tablename"] for r in rows) == sorted(TABLES)


def columns(conn, table):
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchall()
    return {r["column_name"]: r for r in rows}


@pytest.mark.parametrize("table", TABLES)
def test_table_has_the_standard_columns(conn, table):
    cols = columns(conn, table)
    assert cols["id"]["data_type"] == "uuid" and "gen_random_uuid" in cols["id"]["column_default"]
    for name in ("created_at", "updated_at"):
        assert cols[name]["data_type"] == "timestamp with time zone"
        assert cols[name]["is_nullable"] == "NO" and "now()" in cols[name]["column_default"]
    assert cols["deleted_at"]["data_type"] == "timestamp with time zone"
    assert cols["deleted_at"]["is_nullable"] == "YES"
    assert cols["metadata"]["data_type"] == "jsonb" and cols["metadata"]["is_nullable"] == "NO"


@pytest.mark.parametrize("table", TABLES)
def test_id_is_the_primary_key(conn, table):
    pk = conn.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
        "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = %s::regclass AND i.indisprimary",
        (table,),
    ).fetchall()
    assert [r["attname"] for r in pk] == ["id"]


@pytest.mark.parametrize("table", TABLES)
def test_updated_at_is_maintained_by_the_database(conn, table):
    triggers = conn.execute(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal",
        (table,),
    ).fetchall()
    assert f"{table}_touch" in {t["tgname"] for t in triggers}


def test_update_bumps_updated_at_and_never_changes_created_at(conn):
    before = conn.execute(
        "SELECT created_at, updated_at FROM accounts WHERE external_id = 'acct_001'"
    ).fetchone()
    time.sleep(0.01)
    conn.execute(
        "UPDATE accounts SET monthly_cap_minutes = 9, created_at = '2000-01-01' "
        "WHERE external_id = 'acct_001'"
    )
    after = conn.execute(
        "SELECT created_at, updated_at FROM accounts WHERE external_id = 'acct_001'"
    ).fetchone()
    assert after["created_at"] == before["created_at"]  # the attempt to rewrite history is ignored
    assert after["updated_at"] > before["updated_at"]


def test_new_rows_get_a_uuid_and_an_empty_metadata_object(conn):
    row = conn.execute(
        "INSERT INTO accounts (external_id, monthly_cap_minutes) VALUES ('acct_new', 1) "
        "RETURNING id, metadata, deleted_at"
    ).fetchone()
    assert row["id"].version == 4 and row["metadata"] == {} and row["deleted_at"] is None


@pytest.mark.parametrize("bad", ["[]", "'\"text\"'", "'1'", "'null'"])
def test_metadata_must_be_a_json_object(conn, bad):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            f"UPDATE accounts SET metadata = {bad if bad.startswith(chr(39)) else repr(bad)}::jsonb"
        )


def test_metadata_has_a_size_limit(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE accounts SET metadata = jsonb_build_object('x', repeat('a', 20000))")


def test_soft_deleted_aggregate_rows_do_not_block_a_new_live_row(conn):
    acct = conn.execute("SELECT id FROM accounts WHERE external_id = 'acct_001'").fetchone()["id"]
    insert = (
        "INSERT INTO usage_aggregate (account_id, period_type, period_start) "
        "VALUES (%s, 'day', '2026-11-10')"
    )
    conn.execute(insert, (acct,))
    with pytest.raises(psycopg.errors.UniqueViolation):  # two live rows: refused
        conn.execute(insert, (acct,))
    conn.rollback()
    conn.execute(insert, (acct,))
    conn.execute("UPDATE usage_aggregate SET deleted_at = now()")
    conn.execute(insert, (acct,))  # allowed once the old one is soft-deleted
    assert conn.execute("SELECT count(*) AS n FROM usage_aggregate").fetchone()["n"] == 2
    conn.rollback()


def test_a_voided_event_still_blocks_a_second_event_with_the_same_provider_id(conn):
    insert = (
        "INSERT INTO call_events (provider_event_id, account_external_id, provider_call_id, "
        "event_type, occurred_at, duration_seconds, cost_cents, destination_country, raw_body) "
        "VALUES ('evt', 'acct_001', 'c', 'call.ended', now(), 1, 1, 'US', '')"
    )
    conn.execute(insert)
    conn.execute("UPDATE call_events SET deleted_at = now()")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(insert)
    conn.rollback()


def test_migration_checksum_guards_against_edited_history(conn, tmp_path, monkeypatch):
    from app import migrate

    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    (tmp_path / "001_init.sql").write_text("SELECT 1;")  # not what was applied
    conn.commit()
    with pytest.raises(migrate.MigrationChecksumError):
        migrate.apply_migrations(conn)
    conn.rollback()
