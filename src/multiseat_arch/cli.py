from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import autostart
from . import backend
from . import config as cfg
from . import dynamic_login
from .runtime_patch import install as install_runtime_patch

install_runtime_patch(backend)

activate_now = backend.activate_now
doctor = backend.doctor
restore = backend.restore
restore_now = backend.restore_now
start = backend.start
sync_devices_now = backend.sync_devices_now
validate = backend.validate

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
from .users import create_seat_user

PLASMA_EXPERIMENTAL = "/usr/local/bin/kwin-wayland-msa"
LABWC_STABLE = "/usr/local/bin/labwc"


def _slots_dict(obj):
    return {key: getattr(obj, key) for key in obj.__slots__}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="multi-seat-arch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("doctor")
    sub.add_parser("status")
    sub.add_parser("plasma-enable", help="ativa o backend KWin/Plasma experimental")
    sub.add_parser("plasma-disable", help="volta ao backend Labwc estável")
    sub.add_parser("login-enable", help="ativa greeter por tela e login de qualquer usuário local")
    sub.add_parser("login-disable", help="desativa o greeter e volta ao usuário fixo por seat")
    sub.add_parser("login-status", help="mostra se o login dinâmico está ativo")
    sub.add_parser("autostart-enable", help="inicia o multiseat automaticamente ao ligar o PC")
    sub.add_parser("autostart-disable", help="desativa o início automático do multiseat")
    sub.add_parser("autostart-status", help="mostra se o início automático está ativo")

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("config")

    for name in ("apply", "apply-sync", "apply-start"):
        apply_parser = sub.add_parser(name)
        apply_parser.add_argument("config")

    user_parser = sub.add_parser("create-user")
    user_parser.add_argument("username")

    sub.add_parser("start")
    sub.add_parser("sync")
    sub.add_parser("stop")
    sub.add_parser("restore")
    sub.add_parser("_activate", help=argparse.SUPPRESS)
    sub.add_parser("_restore-now", help=argparse.SUPPRESS)
    sub.add_parser("_watch-inputs", help=argparse.SUPPRESS)
    sub.add_parser("_boot", help=argparse.SUPPRESS)
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
    ensure_multiseat_running(config)
    with input_sync_lock():
        ensure_multiseat_running(config)
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

            save_error: Exception | None = None
            route_error: Exception | None = None
            try:
                cfg.save(previous)
            except Exception as exc:
                save_error = exc

            try:
                ensure_multiseat_running(previous)
                sync_devices_now(previous)
            except Exception as exc:
                route_error = exc

            if save_error is not None or route_error is not None:
                details: list[str] = []
                if save_error is not None:
                    details.append(f"persistência: {save_error}")
                if route_error is not None:
                    details.append(f"roteamento: {route_error}")
                raise RuntimeError(
                    f"Falha ao aplicar periféricos: {original}. O rollback também falhou "
                    f"({'; '.join(details)}). Use 'multi-seat-arch restore'."
                ) from original

            raise RuntimeError(
                f"Falha ao aplicar periféricos: {original}. A configuração e as rotas "
                "anteriores foram restauradas."
            ) from original


def _set_compositor(path: str) -> None:
    config = cfg.load()
    config.compositor = path
    cfg.save(config)


def _prepare_dynamic_login(config) -> None:
    """Validate the Plasma/Atrium login path before scheduling activation.

    Activation runs later in a transient systemd unit. If this validation were
    deferred until that unit, the GUI would report that startup was scheduled
    and then appear to do nothing when Atrium/KWin prerequisites were missing.
    Fail here while pkexec is still attached to the GUI so the real error is
    shown immediately.
    """
    if not Path(PLASMA_EXPERIMENTAL).is_file():
        raise RuntimeError(
            "KWin experimental não está instalado. Rode: bash scripts/build-kwin-plasma.sh"
        )
    config.compositor = PLASMA_EXPERIMENTAL
    dynamic_login.enable()


def _enable_autostart() -> None:
    config = cfg.load()
    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    _prepare_dynamic_login(config)
    cfg.save(config)
    autostart.enable()


def _boot_multiseat() -> None:
    """Boot-time entry point used by the persistent systemd service.

    This runs before the host display manager. If activation fails, backend's
    existing rollback returns the machine to graphical.target/normal SDDM.
    """
    before_activation()
    config = cfg.load()
    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    _prepare_dynamic_login(config)
    cfg.save(config)
    activate_now(config)


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

        if args.cmd == "plasma-enable":
            if not Path(PLASMA_EXPERIMENTAL).is_file():
                raise RuntimeError(
                    "KWin experimental não está instalado. Rode scripts/build-kwin-plasma.sh primeiro."
                )
            _set_compositor(PLASMA_EXPERIMENTAL)
            print("Backend Plasma/KWin experimental ativado na configuração.")
            return 0

        if args.cmd == "plasma-disable":
            if dynamic_login.enabled():
                raise RuntimeError("Desative primeiro o login dinâmico com: multi-seat-arch login-disable")
            _set_compositor(LABWC_STABLE)
            print("Backend Labwc estável restaurado na configuração.")
            return 0

        if args.cmd == "login-enable":
            if not Path(PLASMA_EXPERIMENTAL).is_file():
                raise RuntimeError(
                    "KWin experimental não está instalado. Rode scripts/build-kwin-plasma.sh primeiro."
                )
            _set_compositor(PLASMA_EXPERIMENTAL)
            dynamic_login.enable()
            print("Login dinâmico ativado: cada tela terá greeter próprio e usuário não fixo.")
            return 0

        if args.cmd == "login-disable":
            dynamic_login.disable()
            print("Login dinâmico desativado; o modo Plasma volta a usar o usuário fixo configurado por seat.")
            return 0

        if args.cmd == "login-status":
            print("ativo" if dynamic_login.enabled() else "desativado")
            return 0

        if args.cmd == "autostart-enable":
            _enable_autostart()
            print("Início automático ativado. No próximo boot, cada seat abrirá diretamente sua tela de login.")
            return 0

        if args.cmd == "autostart-disable":
            autostart.disable()
            print("Início automático desativado. O próximo boot usará o desktop normal.")
            return 0

        if args.cmd == "autostart-status":
            print("ativo" if autostart.enabled() else "desativado")
            return 0

        if args.cmd == "create-user":
            create_seat_user(args.username)
            print(f"Usuário '{args.username}' criado com home próprio.")
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
                _prepare_dynamic_login(config)
                cfg.save(config)
                start(config)
                print("Configuração salva e inicialização agendada.")
            else:
                cfg.save(config)
                print("Configuração instalada.")
            return 0

        if args.cmd == "start":
            before_activation()
            config = cfg.load()
            _prepare_dynamic_login(config)
            cfg.save(config)
            start(config)
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

        if args.cmd == "_boot":
            _boot_multiseat()
            return 0

        return 1
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
