Concurrent workflow activity exists in the current lane.

- Assume another runtime branch or collaborator may be touching adjacent work.
- Do not overwrite, revert, or "clean up" surrounding changes just to simplify your own path.
- Keep changes narrow, state coordination assumptions explicitly, and adapt to current evidence.
- If safe progress depends on another branch finishing first, say so directly instead of pretending the conflict does not exist.
