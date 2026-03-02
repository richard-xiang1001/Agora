#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    vals = sorted(values)
    idx = max(0, int((len(vals) - 1) * 0.95))
    return int(vals[idx])


def main() -> int:
    parser = argparse.ArgumentParser(description='Lint prompt embedding live gate trend')
    parser.add_argument('--history', default='governance/audits/prompt_embedding_live_gate_history.jsonl')
    parser.add_argument('--out', default='governance/audits/prompt_embedding_live_trend.json')
    parser.add_argument('--window', type=int, default=7)
    args = parser.parse_args()

    history = _load_rows(Path(args.history))
    windowed = history[-max(1, args.window):]

    total = len(windowed)
    pass_count = sum(1 for x in windowed if x.get('passed'))
    pass_rate = (pass_count / total) if total else 1.0
    p95_total_ms = _p95([int(x.get('total_ms', 0)) for x in windowed])

    auth_failed_recent = [int(x.get('auth_failed_count', 0)) for x in windowed]
    consecutive_auth_failed = bool(len(auth_failed_recent) >= 2 and auth_failed_recent[-1] > 0 and auth_failed_recent[-2] > 0)

    alerts: list[str] = []
    if pass_rate < 0.8:
        alerts.append('pass_rate_below_0.8')
    if p95_total_ms > 120000:
        alerts.append('p95_total_ms_above_120000')
    if consecutive_auth_failed:
        alerts.append('consecutive_auth_failed')

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window': max(1, args.window),
        'sample_count': total,
        'pass_rate': round(pass_rate, 4),
        'p95_total_ms': p95_total_ms,
        'auth_failed_recent': auth_failed_recent,
        'alerts': alerts,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')

    if alerts:
        print('[FAIL] live gate trend alerts: ' + ','.join(alerts))
        return 1
    print('[PASS] live gate trend healthy')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
