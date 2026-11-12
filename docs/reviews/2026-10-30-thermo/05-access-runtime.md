# Access, audit, and runtime review

Coordinator review and fixes, October 30-31, 2026. The frontend worker independently reviewed the new security boundary and added a regression test for malformed CSRF headers.

## Reproduced findings

The original `/api/session` returned the same value used as the bearer cookie. Five initial hardening tests failed for public cookie exposure, missing server-side expiry, absent logout revocation, absent body-size enforcement, and missing browser security headers. The implementation now passes those checks with a separately hashed cookie, an eight-hour credential lifetime, and server-side revocation.

Re-login initially created a new financial owner and lost access to past purchases. The single-operator access-key deployment now keeps a durable operator workspace while rotating its cookie and CSRF token. A regression test proves that grants survive logout/re-login and that a copied old cookie stops working. Anonymous development sessions remain separate. This is one configured operator identity, not a multi-user identity provider.

Production configuration rejects HTTP origins, insecure cookies, and missing/short access keys. Browser mutations check Origin and CSRF, reject agent Authorization headers on human routes, and use bounded request bodies. Request logs omit credentials and body contents. Shared PostgreSQL rate buckets count failed login attempts and limit HTTP/model work across processes. The HTTP middleware runs its blocking rate transaction in a thread pool.

An authenticated request with a non-ASCII CSRF header reproduced a Python TypeError. Comparing encoded values now returns the intended 403. Separately, an audit reader with an old ORM checkpoint falsely reported corruption after another transaction appended an event. Verification now refreshes and locks the checkpoint before reading the chain; the concurrency regression passes.

The installed wheel's old static-path default pointed into Python's installation directory rather than the application directory. Runtime `.env` and frontend paths now resolve from the documented working directory. An installed-layout regression proves those paths. Production startup refuses a missing frontend bundle, and readiness detects an unavailable reconciliation task or database.

## Validation and operator impact

See `test_security_hardening.py`, `test_root_security_review.py`, `test_audit_snapshot.py`, `test_runtime_paths.py`, and `test_setup_check.py`. They cover credential isolation, expiry, logout, login continuity, wrong-key throttling, atomic rate updates, Origin/Host restrictions, production fail-closed configuration, safe database errors, coherent audit verification, runtime paths, readiness, and value-free setup reporting.

Before local prototype adoption, the coordinator saved a PostgreSQL custom-format backup under ignored `.local`. Strict migration validation detected an older prototype variant: an empty rate-limit helper created by an earlier test startup, and a missing payment CHECK constraint. Existing payments were checked against the bounds, the empty helper was retained in a separate archive schema, and the validated constraint was added before explicit adoption. Every prior public financial/audit row count was retained. Old prototype bearer access was intentionally revoked; financial history was not erased.

The complete database is now at `0002_hardening`. A backup restore remains the rollback mechanism. Do not force-stamp an unexpected schema on another installation. API access is protected by one operator key; keep that secret out of model prompts and public setup material, and provide judge access through an appropriate private testing channel.

The session expiry and invalidation decisions follow [OWASP's session-management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html). No automated control can substitute for testing the actual configured PayPal account and public HTTPS endpoint before release.
