# WAL Recovery Runbook (Week 4)

## Trigger Conditions
- Audit daemon enters read-only mode because WAL capacity threshold is reached.
- `GET /v1/governance/failure-mode` reports `audit_mode=readonly`.

## Operational Behavior
- Execution chain is blocked in readonly mode.
- Audit append still accepted into WAL segments.
- Audit daemon background replay keeps draining WAL.

## Recovery Steps
1. Confirm WAL growth cause (audit target unavailable or replay lag).
2. Restore audit append path (filesystem permissions / disk space).
3. Run replay loop until `wal_replay_complete=true`.
4. Verify all WAL `event_id` exist in `audit.jsonl`.
5. Confirm system auto-exits readonly mode.

## Verification Checklist
- No pending WAL segments under `audit/wal/*.jsonl`.
- Projector consistency check is green after replay.
- New events receive strictly increasing `seq_no`.
