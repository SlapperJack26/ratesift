"""Verification tests for WHC Cloud VPS deployment readiness fixes (Phase 0)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs
from main import app
from services import db_service, quotelytics_db_service

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_DIR = REPO_ROOT / "deployment"


def test_database_services_honor_failsafe_and_quotelytics_db_path_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QUOTELYTICS_DB_PATH", raising=False)
    monkeypatch.delenv("FAILSAFE_DB_PATH", raising=False)

    # Ensure module defaults resolve when neither env var nor monkeypatch is active
    monkeypatch.setattr(db_service, "DB_FILE", db_service._DEFAULT_DB_FILE)
    monkeypatch.setattr(
        quotelytics_db_service, "DB_FILE", quotelytics_db_service._DEFAULT_DB_FILE
    )
    monkeypatch.setattr(jobs, "DB_PATH", jobs.DB_PATH_DEFAULT)

    assert Path(db_service.resolve_db_file()) == Path(db_service._DEFAULT_DB_FILE)
    assert Path(quotelytics_db_service.resolve_db_file()) == Path(
        quotelytics_db_service._DEFAULT_DB_FILE
    )
    assert Path(jobs.resolve_db_path(jobs.DB_PATH_DEFAULT)) == Path(jobs.DB_PATH_DEFAULT)

    # Verify FAILSAFE_DB_PATH is respected by all three data layers
    failsafe_db = str(tmp_path / "whc_failsafe.db")
    monkeypatch.setenv("FAILSAFE_DB_PATH", failsafe_db)
    assert db_service.resolve_db_file() == failsafe_db
    assert quotelytics_db_service.resolve_db_file() == failsafe_db
    assert jobs.resolve_db_path(jobs.DB_PATH_DEFAULT) == failsafe_db

    # Verify connections actually target failsafe_db cleanly
    db_service.init_db()
    quotelytics_db_service.init_quotelytics_db()
    store = jobs.RelationalJobStore()
    with db_service.db_session() as conn:
        tbls = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"users", "api_keys", "ql_rate_sheets", "failsafe_jobs"} <= tbls
    assert Path(failsafe_db).is_file()
    store.cleanup_expired()

    # Verify QUOTELYTICS_DB_PATH overrides FAILSAFE_DB_PATH
    explicit_db = str(tmp_path / "whc_quotelytics.db")
    monkeypatch.setenv("QUOTELYTICS_DB_PATH", explicit_db)
    assert db_service.resolve_db_file() == explicit_db
    assert quotelytics_db_service.resolve_db_file() == explicit_db
    assert jobs.resolve_db_path(jobs.DB_PATH_DEFAULT) == explicit_db

    # Verify existing test monkeypatches of DB_FILE still take priority
    monkeypatch_db = str(tmp_path / "monkeypatch.db")
    monkeypatch.setattr(db_service, "DB_FILE", monkeypatch_db)
    monkeypatch.setattr(quotelytics_db_service, "DB_FILE", monkeypatch_db)
    assert db_service.resolve_db_file() == monkeypatch_db
    assert quotelytics_db_service.resolve_db_file() == monkeypatch_db


def test_healthz_get_and_head_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "health_probe.db")
    monkeypatch.setattr(db_service, "DB_FILE", db_path)
    db_service.init_db()

    client = TestClient(app)
    get_res = client.get("/healthz")
    assert get_res.status_code == 200
    payload = get_res.json()
    assert payload["status"] == "healthy"
    assert payload["database"] == "connected"
    assert payload["region"] == "CA_CENTRAL_WHC"

    head_res = client.head("/healthz")
    assert head_res.status_code == 200


def test_whc_deployment_scripts_and_units_complete() -> None:
    expected_files = (
        "setup_whc_server.sh",
        "quotelytics.service",
        "quotelytics-discord-bot.service",
        "nginx_quotelytics.conf",
        "backup_db.sh",
        "verify_whc_cutover.sh",
    )
    contents = {}
    for filename in expected_files:
        path = DEPLOYMENT_DIR / filename
        assert path.is_file(), f"Missing deployment file: {filename}"
        raw = path.read_bytes()
        assert b"\r\n" not in raw, f"Deployment file {filename} must use LF line endings for Linux"
        contents[filename] = raw.decode("utf-8")

    setup_sh = contents["setup_whc_server.sh"]
    assert "SCRIPT_DIR=" in setup_sh
    assert "openssl req -x509" in setup_sh
    assert "options-ssl-nginx.conf" in setup_sh
    assert "quotelytics-discord-bot.service" in setup_sh
    assert "nginx -t" in setup_sh

    backup_sh = contents["backup_db.sh"]
    assert "FAILSAFE_DB_PATH" in backup_sh
    assert "OFFSITE_BACKUP_RSYNC_TARGET" in backup_sh
    assert "OFFSITE_BACKUP_CMD" in backup_sh
    assert "PRAGMA integrity_check;" in backup_sh

    bot_unit = contents["quotelytics-discord-bot.service"]
    assert "discord_sales_support_bot.py" in bot_unit
    assert "Restart=always" in bot_unit

    app_unit = contents["quotelytics.service"]
    assert "gunicorn main:app" in app_unit

    verifier_sh = contents["verify_whc_cutover.sh"]
    assert "systemctl is-active" in verifier_sh
    assert "X-Data-Residency: CA_CENTRAL_WHC" in verifier_sh
    assert "/healthz" in verifier_sh
