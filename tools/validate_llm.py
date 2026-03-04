"""Validate LLM provider configuration with a single test call."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PathConfig
from src.providers import llm


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate connectivity to the configured LLM provider.")
    parser.add_argument(
        "--llm-provider",
        choices=["mock", "openai", "azure_openai", "anthropic"],
        default="mock",
        help="LLM provider to validate.",
    )
    parser.add_argument("--llm-model", help="Override model/deployment identifier.")
    parser.add_argument("--no-cache", action="store_true", help="Disable cache when validating.")
    parser.add_argument("--prompt", default="ping", help="Custom prompt to send to the provider.")
    parser.add_argument("--llm-timeout-seconds", type=int, default=60, help="Request timeout for the validation call.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache_dir = PathConfig().reports_root / "cache" / "llm"
    llm.set_config(
        provider=args.llm_provider,
        model=args.llm_model,
        cache_enabled=not args.no_cache,
        cache_dir=cache_dir,
        timeout=args.llm_timeout_seconds,
    )
    ok, message, latency, tokens = llm.validate_connection(args.prompt[:200])
    payload = {
        "provider": args.llm_provider,
        "model": args.llm_model or "",
        "success": ok,
        "message": message,
        "latency_seconds": latency,
        "tokens": tokens,
    }
    print(json.dumps(payload, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
