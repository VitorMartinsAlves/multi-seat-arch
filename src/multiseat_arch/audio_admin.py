from __future__ import annotations

import argparse
import sys

from .audio import save_rules_from_file


def main() -> int:
    parser = argparse.ArgumentParser(prog="multi-seat-arch-audio-admin")
    parser.add_argument("config")
    args = parser.parse_args()
    try:
        save_rules_from_file(args.config)
        return 0
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
