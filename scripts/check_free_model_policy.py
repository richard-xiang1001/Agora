#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def main() -> int:
    model_a = os.getenv("OPENROUTER_MODEL_A", "qwen/qwen3-4b:free")
    model_b = os.getenv("OPENROUTER_MODEL_B", "meta-llama/llama-3.3-70b-instruct:free")
    fallback_env = os.getenv("OPENROUTER_FALLBACK_MODELS", "")
    fallback = [m.strip() for m in fallback_env.split(",") if m.strip()]
    if not fallback:
        fallback = [
            "arcee-ai/trinity-large-preview:free",
            "liquid/lfm-2.5-1.2b-thinking:free",
            "liquid/lfm-2.5-1.2b-instruct:free",
        ]

    configured = [model_a, model_b, *fallback]
    non_free = [m for m in configured if not m.endswith(":free")]
    if non_free:
        print(f"[FAIL] non-free models found in test policy: {non_free}")
        return 1

    print(f"[PASS] free-only model policy ({len(configured)} configured entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
