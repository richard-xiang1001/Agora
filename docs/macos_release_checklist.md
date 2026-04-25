# macOS release checklist

## Build

- `pip install -r requirements.txt`
- `npm install`
- Confirm `git status --short` is empty before the official build.
- `npm run desktop:pack`
- Do not use `npm run desktop:pack:raw` as a release path. It skips reliability preflight and is only for local packaging debugging.
- Confirm `governance/audits/release_evidence_manifest.json` records `decision=pass`, `git.dirty=false`, and the expected release policy.
- Capture release rehearsal output with `npm run desktop:pack -- --dry-run | tee dist/release-evidence/rehearsal-command.log` when doing a rehearsal.
- Build the evidence bundle with `PYTHONPATH=. ./.venv/bin/python scripts/build_release_evidence_bundle.py --command-log dist/release-evidence/rehearsal-command.log --zip`.
- Confirm `dist/release-evidence/<timestamp>/bundle_manifest.json` records `git.dirty=false`, `reliability_gate.decision=pass`, copied artifacts, and any missing optional artifacts.
- Keep `governance/audits/*.json` and `*.jsonl` as release evidence. Attach them as a separate artifact bundle or use a dedicated evidence commit; do not mix them into product-code commits.

## Clean-machine verification

- Install the generated `Agora.dmg` or `.zip` on a clean macOS machine.
- Confirm the app opens without a source checkout.
- Confirm the first screen allows entering through `Mock`.
- Confirm a new session is created automatically on first use.
- Confirm normal chat works in `Mock`.
- Open Settings and verify the displayed data directory exists in the app sandbox.
- Switch to `Live`, enter a valid OpenRouter key, save, and verify model status updates.
- Quit and reopen the app; confirm the mode, sessions, and memory persist.

## Release notes

- Include current version number and release date.
- Include one screenshot of the main chat view.
- Include one screenshot of Settings.
- Call out that this build is an unsigned macOS beta.
- Link to [KNOWN_LIMITATIONS.md](/Users/xiangruichao/Desktop/Agora/KNOWN_LIMITATIONS.md).
