from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


def _load_discover_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "discover_merchant.py"
    spec = importlib.util.spec_from_file_location("discover_merchant", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mock_paypal_http(payee: dict[str, str], *, order_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://api-m.sandbox.paypal.com/")
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-secret-never-print", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            import json
            body = json.loads(request.content.decode())
            assert "payee" not in body["purchase_units"][0]
            assert body["intent"] == "CAPTURE"
            assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "1.00"}
            return httpx.Response(201, json={"id": "DISCOVERORD123456", "status": "CREATED"})
        if request.method == "GET" and request.url.path == "/v2/checkout/orders/DISCOVERORD123456":
            if order_status != 200:
                return httpx.Response(order_status, json={"name": "NOT_AUTHORIZED", "debug_id": "DBG-DISC-403", "details": [{"issue": "PERMISSION_DENIED"}]})
            return httpx.Response(200, json={
                "id": "DISCOVERORD123456",
                "status": "CREATED",
                "purchase_units": [{"payee": payee}],
            })
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_discover_merchant_match_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] Matching PayPal merchant_id prints MATCH and leaves .env untouched."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    original = "PAYPAL_CLIENT_ID=cid\nPAYPAL_CLIENT_SECRET=csec-secret\nPAYPAL_MERCHANT_ID=Q6KWTQLUQGFCY\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "csec-secret")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "Q6KWTQLUQGFCY")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")

    with _mock_paypal_http({"merchant_id": "Q6KWTQLUQGFCY", "email_address": "sb-biz@business.example.com"}) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=True, http_client=http, load_env=False)

    out = capsys.readouterr().out
    assert code == 0
    assert info["status"] == "MATCH"
    assert info["wrote_env"] is False
    assert "Comparison: MATCH" in out
    assert "Q6KWTQLUQGFCY" in out
    assert "tok-secret-never-print" not in out
    assert "csec-secret" not in out
    assert env_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".env.bak").exists()


def test_discover_merchant_mismatch_without_flag_changes_nothing_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] MISMATCH without --write-env reports MISMATCH and makes no file edits."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    original = "PAYPAL_MERCHANT_ID=ZJM1234567XZC\nOTHER=keep\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "csec")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "ZJM1234567XZC")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")

    with _mock_paypal_http({"merchant_id": "Q6KWTQLUQGFCY", "email_address": "sb-biz@business.example.com"}) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=False, http_client=http, load_env=False)

    out = capsys.readouterr().out
    assert code == 0
    assert info["status"] == "MISMATCH"
    assert info["wrote_env"] is False
    assert "Comparison: MISMATCH" in out
    assert env_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".env.bak").exists()


def test_discover_merchant_mismatch_write_env_updates_only_merchant_line_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] --write-env backs up .env to .env.bak and replaces only the PAYPAL_MERCHANT_ID line."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    original = (
        "# Header comment\n"
        "PAYPAL_CLIENT_ID=cid-keep\n"
        'PAYPAL_CLIENT_SECRET="secret-keep"\n'
        'PAYPAL_MERCHANT_ID="ZJM1234567XZC"\n'
        "GROQ_API_KEY=gsk_keep\n"
    )
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid-keep")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret-keep")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "ZJM1234567XZC")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")

    with _mock_paypal_http({"merchant_id": "Q6KWTQLUQGFCY", "email_address": "sb-biz@business.example.com"}) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=True, http_client=http, load_env=False)

    out = capsys.readouterr().out
    assert code == 0
    assert info["wrote_env"] is True
    assert (tmp_path / ".env.bak").read_text(encoding="utf-8") == original
    assert env_file.read_text(encoding="utf-8") == (
        "# Header comment\n"
        "PAYPAL_CLIENT_ID=cid-keep\n"
        'PAYPAL_CLIENT_SECRET="secret-keep"\n'
        "PAYPAL_MERCHANT_ID=Q6KWTQLUQGFCY\n"
        "GROQ_API_KEY=gsk_keep\n"
    )
    assert "new PAYPAL_MERCHANT_ID: Q6K...FCY" in out
    assert "secret-keep" not in out


def test_discover_merchant_email_only_reports_missing_merchant_id_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] If PayPal returns email_address without merchant_id, report clearly and do not overwrite .env."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    original = "PAYPAL_MERCHANT_ID=ZJM1234567XZC\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "csec")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "ZJM1234567XZC")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")

    with _mock_paypal_http({"email_address": "sb-only@business.example.com"}) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=True, http_client=http, load_env=False)

    out = capsys.readouterr().out
    assert code == 0
    assert info["status"] == "MISMATCH"
    assert info["wrote_env"] is False
    assert "PayPal returned payee.email_address without payee.merchant_id." in out
    assert env_file.read_text(encoding="utf-8") == original


def test_discover_merchant_refuses_non_sandbox_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] Non-sandbox PAYPAL_ENV refuses to run and makes no HTTP calls."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    env_file.write_text("PAYPAL_ENV=live\n", encoding="utf-8")
    monkeypatch.setenv("PAYPAL_ENV", "live")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "csec")

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Should not make HTTP calls when not sandbox")

    with httpx.Client(transport=httpx.MockTransport(fail_handler)) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=False, http_client=http, load_env=False)

    err = capsys.readouterr().err
    assert code == 1
    assert info["status"] == "refused_non_sandbox"
    assert "PAYPAL_ENV must be 'sandbox'" in err


def test_discover_merchant_reports_paypal_error_details_mocked(tmp_path: Path, monkeypatch, capsys):
    """[MOCKED] PayPal error on GET order reports exact status, name, and debug_id."""
    mod = _load_discover_module()
    env_file = tmp_path / ".env"
    env_file.write_text("PAYPAL_MERCHANT_ID=ZJM1234567XZC\n", encoding="utf-8")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "csec")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "ZJM1234567XZC")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")

    with _mock_paypal_http({}, order_status=403) as http:
        code, info = mod.run_discovery(env_path=env_file, write_env=False, http_client=http, load_env=False)

    err = capsys.readouterr().err
    assert code == 1
    assert info["status"] == "get_error"
    assert "HTTP 403" in err
    assert "NOT_AUTHORIZED" in err
    assert "DBG-DISC-403" in err

