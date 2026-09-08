"""keyrotor CLI.

Subcommands:
    serve  - start the dashboard + OpenAI-compatible HTTP API
    chat   - one-shot chat through the router
    status - pretty summary (keys always masked)

Secrets come exclusively from environment variables (keyrotor.secrets).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from keyrotor import BUILTIN_PROVIDERS, RotatingRouter
from keyrotor.secrets import load_keys, provider_order_from_env


def _env_float_opt(name: str) -> Optional[float]:
    raw = os.environ.get(name, "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int_opt(name: str) -> Optional[int]:
    raw = os.environ.get(name, "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def build_router(provider_order: Optional[List[str]] = None) -> RotatingRouter:
    """Router configured from environment variables only."""
    default_order = list(BUILTIN_PROVIDERS.keys())
    order = provider_order or provider_order_from_env(default_order)
    return RotatingRouter(
        providers=BUILTIN_PROVIDERS,
        keys=load_keys(),
        provider_order=order,
        cache_ttl=_env_float_opt("KEYROTOR_CACHE_TTL"),
        max_retries=_env_int_opt("KEYROTOR_MAX_RETRIES"),
        backoff_factor=_env_float_opt("KEYROTOR_BACKOFF"),
        breaker_threshold=_env_int_opt("KEYROTOR_BREAKER_THRESHOLD") or 5,
        breaker_cooldown=_env_float_opt("KEYROTOR_BREAKER_COOLDOWN") or 60.0,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    from keyrotor.server import run

    run(host=args.host, port=args.port, router=build_router())
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    router = build_router()
    provider_order = None
    if args.provider_order:
        provider_order = [p.strip() for p in args.provider_order.split(",")
                          if p.strip()]
    result = router.chat(
        [{"role": "user", "content": args.prompt}],
        model=args.model,
        provider_order=provider_order,
    )
    if not result.ok:
        print(f"error: {router.redactor.clean(result.error)}", file=sys.stderr)
        return 1
    print(f"provider: {result.provider}")
    print(f"model:    {result.model}")
    print(f"cache:    {'hit' if result.cache_hit else 'miss'}")
    print(f"attempts: {result.attempts}")
    print("---")
    print(result.content)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    router = build_router()
    status = router.status()

    cache = status["cache"]
    print("keyrotor status")
    print("=" * 62)
    print("cache")
    print(f"  entries:   {cache['size']}")
    print(f"  hits:      {cache['hits']}")
    print(f"  misses:    {cache['misses']}")
    print(f"  hit rate:  {cache['hit_rate'] * 100:.1f}%")
    print("providers")
    for provider in status["providers"]:
        print(f"  [{provider['provider']}]")
        print(f"    breaker:      {provider['breaker']}")
        print(f"    keys active:  {provider['keys_active']}")
        print(f"    keys:         {', '.join(provider['keys_masked']) or '(none)'}")
        print(f"    requests:     {provider['requests']}")
        print(f"    successes:    {provider['successes']}")
        print(f"    failures:     {provider['failures']}")
        print(f"    keys dropped: {provider['keys_dropped']}")
        print(f"    cache hits:   {provider['cache_hits']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keyrotor",
        description="multi-provider LLM API key rotation router",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="start HTTP server + dashboard")
    p_serve.add_argument("--host", default=os.environ.get("KEYROTOR_HOST",
                                                          "127.0.0.1"))
    p_serve.add_argument("--port", type=int,
                         default=int(os.environ.get("KEYROTOR_PORT", "8000")))
    p_serve.set_defaults(func=cmd_serve)

    p_chat = sub.add_parser("chat", help="one-shot chat")
    p_chat.add_argument("prompt", help="user prompt")
    p_chat.add_argument("--model", default=None, help="model id")
    p_chat.add_argument("--provider-order", default=None,
                        help="comma-separated provider priority")
    p_chat.set_defaults(func=cmd_chat)

    p_status = sub.add_parser("status", help="router summary")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
