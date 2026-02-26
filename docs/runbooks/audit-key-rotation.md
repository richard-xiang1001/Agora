# Audit HMAC Key Rotation Runbook (MVP)

## Preconditions
- Audit daemon supports dual-key window: `active_key` + `next_key`.
- Component keys are provided via environment variables (not committed).

## Steps
1. Generate new per-component keys and store securely.
2. Update audit daemon to accept both old and new keys.
3. Roll components one by one with new keys.
4. Verify signed append requests succeed with new `key_id`.
5. Remove old keys from audit daemon.
6. Remove old keys from runtime environments.

## Safety Checks
- Reject unsigned requests.
- Reject unknown `key_id`.
- Ensure append failures are buffered to WAL before key retirement.
- Ensure business APIs do not write `sessions/*/audit.jsonl` directly; all writes must go through `AuditDaemon.append_event`.
- Verify `POST /internal/audit/append` and runtime helper `_append_audit_event(...)` remain the only append entrypoints.
