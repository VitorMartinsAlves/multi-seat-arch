from __future__ import annotations

import argparse
import json
from . import config as cfg
from .backend import doctor, restore, start, validate
from .discovery import discover_displays, discover_inputs


def _slots_dict(obj):
    return {k: getattr(obj, k) for k in obj.__slots__}


def main() -> int:
    p = argparse.ArgumentParser(prog="multi-seat-arch")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover"); sub.add_parser("doctor")
    v = sub.add_parser("validate"); v.add_argument("config")
    a = sub.add_parser("apply"); a.add_argument("config")
    sub.add_parser("start"); sub.add_parser("stop"); sub.add_parser("restore")
    args = p.parse_args()

    if args.cmd == "discover":
        print(json.dumps({"displays": [_slots_dict(d) for d in discover_displays()], "inputs": [_slots_dict(d) for d in discover_inputs()]}, indent=2, ensure_ascii=False)); return 0
    if args.cmd == "doctor":
        checks = doctor()
        for c in checks: print(("OK   " if c.ok else "FALHA"), c.message)
        return 0 if all(c.ok for c in checks) else 1
    if args.cmd == "validate":
        errors = validate(cfg.load(args.config)); print("OK" if not errors else "\n".join(errors)); return 0 if not errors else 2
    if args.cmd == "apply":
        c = cfg.load(args.config); cfg.save(c); print("Configuração instalada."); return 0
    if args.cmd == "start": start(cfg.load()); return 0
    if args.cmd in {"stop", "restore"}: restore(); return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
