from __future__ import annotations

import argparse
import json
import sys

from . import config as cfg
from .backend import (
    activate_now,
    doctor,
    restore,
    restore_now,
    start,
    validate,
)
from .discovery import discover_displays, discover_inputs


def _slots_dict(obj):
    return {key: getattr(obj, key) for key in obj.__slots__}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="multi-seat-arch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("doctor")

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("config")

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("config")

    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restore")
    sub.add_parser("_activate", help=argparse.SUPPRESS)
    sub.add_parser("_restore-now", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    try:
        if args.cmd == "discover":
            print(
                json.dumps(
                    {
                        "displays": [
                            _slots_dict(item) for item in discover_displays()
                        ],
                        "inputs": [
                            _slots_dict(item) for item in discover_inputs()
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.cmd == "doctor":
            checks = doctor()
            for check in checks:
                print(("OK   " if check.ok else "FALHA"), check.message)
            return 0 if all(check.ok for check in checks) else 1

        if args.cmd == "validate":
            errors = validate(cfg.load(args.config))
            print("OK" if not errors else "\n".join(errors))
            return 0 if not errors else 2

        if args.cmd == "apply":
            config = cfg.load(args.config)
            errors = validate(config)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 2
            cfg.save(config)
            print("Configuração instalada.")
            return 0

        if args.cmd == "start":
            start(cfg.load())
            print("Inicialização agendada.")
            return 0

        if args.cmd in {"stop", "restore"}:
            restore()
            print("Restauração agendada.")
            return 0

        if args.cmd == "_activate":
            activate_now(cfg.load())
            return 0

        if args.cmd == "_restore-now":
            restore_now()
            return 0

        return 1
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
