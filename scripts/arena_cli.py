#!/usr/bin/env python3
"""Arena CLI — config validate, catalog refresh, effective limits (DEC-018 B)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.catalog_refresh import refresh_catalog, validate_frozen_config
from backend.observations import get_observation_service
from backend.squad_presets import load_squad_preset


def _cmd_validate(_args: argparse.Namespace) -> int:
    ok, issues = validate_frozen_config()
    print(json.dumps({"ok": ok, "issues": issues}, indent=2))
    return 0 if ok else 1


async def _cmd_refresh(args: argparse.Namespace) -> int:
    result = await refresh_catalog(force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_effective_limits(args: argparse.Namespace) -> int:
    if args.squad:
        preset = load_squad_preset(args.squad)
        model_ids = list(preset["arena_models"])
        squad_name = args.squad
    else:
        from backend.dependencies import load_runtime_settings

        settings = load_runtime_settings()
        model_ids = list(settings.get("arena_models") or [])
        squad_name = settings.get("arena_squad")

    report = get_observation_service().effective_limits_report(
        model_ids,
        squad_name=squad_name,
    )
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="arena", description="LLM Context Arena CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("config", help="Config commands")
    p_validate_sub = p_validate.add_subparsers(dest="config_cmd", required=True)
    p_validate_sub.add_parser("validate", help="Validate frozen YAML schemas")

    p_catalog = sub.add_parser("catalog", help="Catalog commands")
    p_catalog_sub = p_catalog.add_subparsers(dest="catalog_cmd", required=True)
    p_refresh = p_catalog_sub.add_parser("refresh", help="Refresh registered limits from OpenRouter")
    p_refresh.add_argument("--force", action="store_true")
    p_refresh.add_argument("--dry-run", action="store_true")
    p_eff = p_catalog_sub.add_parser(
        "effective-limits",
        help="Show effective limits + pending observations",
    )
    p_eff.add_argument("--squad", default=None, help="Squad preset name")
    p_sweep = p_catalog_sub.add_parser(
        "observation-sweep",
        help="Archive expired accepted observations and flag re-verify",
    )

    args = parser.parse_args()

    if args.command == "config" and args.config_cmd == "validate":
        return _cmd_validate(args)
    if args.command == "catalog" and args.catalog_cmd == "refresh":
        return asyncio.run(_cmd_refresh(args))
    if args.command == "catalog" and args.catalog_cmd == "effective-limits":
        args.squad = getattr(args, "squad", None)
        return _cmd_effective_limits(args)
    if args.command == "catalog" and args.catalog_cmd == "observation-sweep":
        result = get_observation_service().sweep_expired_observations()
        print(json.dumps(result, indent=2))
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())