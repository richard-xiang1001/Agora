## Review Boundary

- [ ] Commit A contains only runtime invariant and legacy migration hardening.
- [ ] Commit B contains only release preflight, evidence manifest, package scripts, and runbook changes.
- [ ] Commit C contains tests only.
- [ ] `governance/audits/*.json` and `*.jsonl` are not mixed into product-code commits.

## Reliability Release Checks

- [ ] `desktop:pack` remains the official release path.
- [ ] `desktop:pack:raw` is used only for local debugging, not release evidence.
- [ ] Dirty workspace policy is preserved: official pack blocks dirty state; dry-run may report dirty state.
- [ ] Release evidence manifest records the gate decision, dirty state, blocking config, and artifact paths.
- [ ] Legacy workflow reconciliation was checked with `scripts/check_runtime_invariants.py --mode mark-legacy-safe --dry-run` when relevant.

## CI / Evidence

- [ ] `npm run release:reliability:ci` passes or the failure is explained.
- [ ] Python reliability tests pass or the failure is explained.
- [ ] Release evidence is attached as a separate artifact bundle or explicit evidence commit when this PR is part of a release.
