from pathlib import Path
import runpy


def test_installed_package_uses_runtime_working_directory(monkeypatch, tmp_path):
    source = Path(__file__).parents[1] / "mandate/config.py"
    installed = tmp_path / "lib/python/site-packages/mandate/config.py"
    installed.parent.mkdir(parents=True)
    installed.write_text(source.read_text(), encoding="utf-8")
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / ".env").write_text("PUBLIC_BASE_URL=http://localhost:8000\n", encoding="utf-8")
    monkeypatch.chdir(app_root)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("WEB_DIST", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    settings = runpy.run_path(str(installed))
    assert settings["WEB_DIST"] == app_root / "apps/web/dist"
    assert settings["PUBLIC_BASE_URL"] == "http://localhost:8000"


def test_readiness_refuses_missing_production_bundle(client, monkeypatch, tmp_path):
    from mandate import config
    monkeypatch.setattr(config, "PRODUCTION", True)
    monkeypatch.setattr(config, "WEB_DIST", tmp_path)
    assert client.get("/api/ready").status_code == 503


def test_readiness_refuses_failed_worker(client, monkeypatch):
    from mandate.main import app
    class FailedWorker:
        def done(self):
            return True
    monkeypatch.setattr(app.state, "payment_worker", FailedWorker())
    assert client.get("/api/ready").status_code == 503
