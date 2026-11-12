from mandate.check_setup import integration_checks


def test_setup_check_reports_names_and_never_values():
    values = {"PAYPAL_CLIENT_ID": "private-client", "PAYPAL_CLIENT_SECRET": "private-secret",
              "PAYPAL_MERCHANT_ID": "private-merchant", "PAYPAL_WEBHOOK_ID": "private-webhook",
              "GROQ_API_KEY": "private-model-key"}
    checks = integration_checks(values)
    assert all(ready for _, ready in checks)
    assert all(value not in repr(checks) for value in values.values())
    values["PAYPAL_CLIENT_SECRET"] = "   "
    assert dict(integration_checks(values))["PAYPAL_CLIENT_SECRET"] is False
