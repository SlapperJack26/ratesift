"""
Verification suite for GTM Plan Group 3 (Server Hardening & Production Operations):
1. /healthz operational probe endpoint (database check, CA_CENTRAL_WHC).
2. Production debug route gating (/showcase, /flowchart, /failsafe/demo).
3. Documented .env.example configuration template exists.
4. Render legacy files removed from workspace root.
"""
import os
import pytest
from fastapi.testclient import TestClient

from main import app
from services.db_service import init_db, get_connection
from services.auth_service import register_and_create_session


def test_01_healthz_endpoint_healthy():
    init_db()
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["region"] == "CA_CENTRAL_WHC"
    assert "Quotelytics" in data["app"]


def test_02_production_debug_routes_gating(monkeypatch):
    init_db()
    client = TestClient(app)

    # In default test/dev mode, routes render 200
    assert client.get("/showcase").status_code == 200
    assert client.get("/flowchart").status_code == 200
    assert client.get("/failsafe/demo").status_code == 200

    # In production mode without admin credentials, routes return 404
    monkeypatch.setenv("APP_ENV", "production")
    anon_client = TestClient(app)
    assert anon_client.get("/showcase").status_code == 404
    assert anon_client.get("/flowchart").status_code == 404
    assert anon_client.get("/failsafe/demo").status_code == 404

    # Regular user in production mode still gets 404
    reg_u, reg_tok = register_and_create_session(
        name="Prod Regular",
        email="prod.regular@maple.ca",
        company="Maple Co",
        origin_zip="M5V 2T6",
        password="ProdRegularPassword2026!"
    )
    user_client = TestClient(app, cookies={"quotelytics_session": reg_tok})
    assert user_client.get("/showcase").status_code == 404

    # Admin user in production mode can access debug routes
    admin_u, admin_tok = register_and_create_session(
        name="Prod Admin",
        email="prod.admin@maple.ca",
        company="Maple Admin",
        origin_zip="M5V 2T6",
        password="ProdAdminPassword2026!"
    )
    conn = get_connection()
    conn.execute("UPDATE users SET role = 'ADMIN' WHERE id = ?", (admin_u["id"],))
    conn.commit()
    conn.close()

    admin_client = TestClient(app, cookies={"quotelytics_session": admin_tok})
    assert admin_client.get("/showcase").status_code == 200
    assert admin_client.get("/flowchart").status_code == 200
    assert admin_client.get("/failsafe/demo").status_code == 200


def test_03_env_example_template_documented():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_example_path = os.path.join(repo_root, ".env.example")
    assert os.path.exists(env_example_path)

    with open(env_example_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "APP_ENV=production" in content
    assert "QUOTELYTICS_ADMIN_EMAIL" in content
    assert "QUOTELYTICS_ADMIN_PASSWORD" in content
    assert "SMTP_HOST" in content
    assert "COOKIE_SECURE" in content
    assert "STRIPE_SECRET_KEY" in content


def test_04_render_legacy_files_not_in_root():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for legacy_name in ["render.yaml", "Procfile", "tunnel_runner.py", "tunnel_url.txt"]:
        fpath = os.path.join(repo_root, legacy_name)
        assert not os.path.exists(fpath), f"Legacy file {legacy_name} still found in root"
