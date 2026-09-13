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
    sync_devices_now,
    validate,
)
from .discovery import (
    discover_bluetooth_controllers,
    discover_displays,
    discover_inputs,
)
from .hotplug import watch_inputs
from .live import ensure_multiseat_running, sync_live
from .operation import input_sync_lock
from .status import runtime_status
from .transitions import before_activation, before_restore


def _slots_dict(obj):
    return {key: getattr(obj, key) for key in obj.__slots__}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="multi-seat-arch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("doctor")
    sub.add_parser("status")

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("config")

    for name in ("apply", "apply-sync", "apply-start"):
        apply_parser = sub.add_parser(name)
        apply_parser.add_argument("config")

    sub.add_parser("start")
    sub.add_parser("sync")
    sub.add_parser("stop")
    sub.add_parser("restore")
    sub.add_parser("_activate", help=argparse.SUPPRESS)
    sub.add_parser("_restore-now", help=argparse.SUPPRESS)
    sub.add_parser("_watch-inputs", help=argparse.SUPPRESS)
    return parser


def _installed_config_or_none():
    try:
        return cfg.load()
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _load_validated(path: str):
    config = cfg.load(path)
    errors = validate(config)
    if errors:
        raise ValueError("\n".join(errors))
    return config


def _apply_sync_transaction(config) -> None:
    ensure_multiseat_running()
    with input_sync_lock():
        ensure_multiseat_running()
        previous = _installed_config_or_none()
        cfg.save(config)
        try:
            sync_devices_now(config)
        except Exception as original:
            if previous is None:
                raise RuntimeError(
                    f"Falha ao aplicar periféricos: {original}. Não havia configuração "
                    "anterior para rollback. Use 'multi-seat-arch restore' se necessário."
                ) from original
            cfg.save(previous)
            try:
                sync_devices_now(previous)
            except Exception as rollback_error:
                raise RuntimeError(
                    f"Falha ao aplicar periféricos: {original}. O rollback também falhou: "
                    f"{rollback_error}. Use 'multi-seat-arch restore'."
                ) from original
            raise RuntimeError(
                f"Falha ao aplicar periféricos: {original}. A configuração e as rotas "
                "anteriores foram restauradas."
            ) from original


def main() -> int:
    args = _build_parser().parse_args()

    try:
        if args.cmd == "discover":
            print(
                json.dumps(
                    {
                        "displays": [_slots_dict(item) for item in discover_displays()],
                        "inputs": [_slots_dict(item) for item in discover_inputs()],
                        "bluetooth_controllers": discover_bluetooth_controllers(),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.cmd == "doctor":
            checks = doctor(_installed_config_or_none())
            for check in checks:
                print(("OK   " if check.ok else "FALHA"), check.message)
            return 0 if all(check.ok for check in checks) else 1

        if args.cmd == "status":
            print(json.dumps(runtime_status(), indent=2, ensure_ascii=False))
            return 0

        if args.cmd == "validate":
            errors = validate(cfg.load(args.config))
            print("OK" if not errors else "\n".join(errors))
            return 0 if not errors else 2

        if args.cmd in {"apply", "apply-sync", "apply-start"}:
            config = _load_validated(args.config)
            if args.cmd == "apply-sync":
                _apply_sync_transaction(config)
                print("Configuração salva e periféricos sincronizados.")
            elif args.cmd == "apply-start":
                before_activation()
                cfg.save(config)
                start(config)
                print("Configuração salva e inicialização agendada.")
            else:
                cfg.save(config)
                print("Configuração instalada.")
            return 0

        if args.cmd == "start":
            before_activation()
            start(cfg.load())
            print("Inicialização agendada.")
            return 0

        if args.cmd == "sync":
            sync_live(cfg.load())
            print("Periféricos sincronizados sem reiniciar os seats.")
            return 0

        if args.cmd in {"stop", "restore"}:
            before_restore()
            restore()
            print("Restauração agendada.")
            return 0

        if args.cmd == "_activate":
            activate_now(cfg.load())
            return 0

        if args.cmd == "_restore-now":
            restore_now()
            return 0

        if args.cmd == "_watch-inputs":
            watch_inputs(cfg.load)
            return 0

        return 1
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
