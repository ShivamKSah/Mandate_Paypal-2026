from __future__ import annotations

import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet


def _load_predeploy_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "predeploy_check.py"
    spec = importlib.util.spec_from_file_location("predeploy_check", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_prod_env() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "PUBLIC_DEMO": "true",
        "COOKIE_SECURE": "true",
        "PUBLIC_BASE_URL": "https://mandate-demo.onrender.com",
        "ALLOWED_HOSTS": "mandate-demo.onrender.com,localhost",
        "PAYPAL_ENV": "sandbox",
        "PAYPAL_BASE_URL": "https://api-m.sandbox.paypal.com",
        "PAYPAL_CLIENT_ID": "test-client-id-secret-token",
        "PAYPAL_CLIENT_SECRET": "test-client-secret-token",
        "PAYPAL_MERCHANT_ID": "TESTMERCHANT999",
        "PAYPAL_WEBHOOK_ID": "TESTWEBHOOK999",
        "VAULT_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "GROQ_API_KEY": "gsk_fake_test_token_value",
        "DATABASE_URL": "postgres://user:supersecretpass@dpg-host/mandate",
    }


def test_predeploy_check_passes_with_valid_production_env(tmp_path: Path, capsys, monkeypatch):
    mod = _load_predeploy_module()
    env = _valid_prod_env()
    env_file = tmp_path / ".env.prod"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
    for key in env:
        monkeypatch.delenv(key, raising=False)

    code = mod.main(["--env-file", str(env_file)])
    out = capsys.readouterr().out

    assert code == 0
    assert "FAIL " not in out
    for secret in env.values():
        if len(secret) >= 8 and secret != "production":
            assert secret not in out


def test_predeploy_check_flags_missing_and_invalid_production_values(tmp_path: Path, capsys, monkeypatch):
    mod = _load_predeploy_module()
    env = _valid_prod_env()
    env["PUBLIC_BASE_URL"] = "http://mandate-demo.onrender.com"
    env["ALLOWED_HOSTS"] = "other-host.example.com"
    env["VAULT_ENCRYPTION_KEY"] = "not-a-fernet-key"
    env["COOKIE_SECURE"] = "false"
    env["PUBLIC_DEMO"] = "false"
    env["APP_ACCESS_KEY"] = "too-short"
    env["PAYPAL_WEBHOOK_ID"] = ""
    env_file = tmp_path / ".env.bad"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
    for key in list(env) + ["APP_ACCESS_KEY"]:
        monkeypatch.delenv(key, raising=False)

    code = mod.main(["--env-file", str(env_file)])
    out = capsys.readouterr().out

    assert code == 1
    assert "FAIL PUBLIC_BASE_URL:" in out
    assert "FAIL ALLOWED_HOSTS:" in out
    assert "FAIL VAULT_ENCRYPTION_KEY:" in out
    assert "FAIL COOKIE_SECURE:" in out
    assert "FAIL APP_ACCESS_KEY:" in out
    assert "FAIL PAYPAL_WEBHOOK_ID:" in out
    assert "too-short" not in out
    assert "not-a-fernet-key" not in out
    assert "supersecretpass" not in out
