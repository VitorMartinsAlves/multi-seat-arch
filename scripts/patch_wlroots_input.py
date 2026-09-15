#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "Failed to directly open multiseat input"


def transform_text(text: str) -> str:
    if MARKER in text:
        return text

    if "#include <fcntl.h>" not in text:
        anchor = "#include <assert.h>\n"
        if anchor not in text:
            raise RuntimeError("Não achei o bloco de includes esperado em session.c")
        text = text.replace(anchor, anchor + "#include <fcntl.h>\n", 1)

    pattern = re.compile(
        r"(struct wlr_device \*wlr_session_open_file\(struct wlr_session \*session,\s*\n\s*const char \*path\) \{\n)"
    )
    match = pattern.search(text)
    if not match:
        raise RuntimeError("Não achei wlr_session_open_file() em session.c")

    block = (
        "\t/* Multi Seat Arch: direct evdev open for DRM-lease seats. */\n"
        "\tconst char *drm_lease = getenv(\"DRM_LEASE\");\n"
        "\tif (drm_lease && strncmp(path, \"/dev/input/event\", 16) == 0) {\n"
        "\t\tint input_fd = open(path, O_RDWR | O_CLOEXEC | O_NONBLOCK);\n"
        "\t\tif (input_fd < 0) {\n"
        "\t\t\twlr_log_errno(WLR_ERROR,\n"
        "\t\t\t\t\"Failed to directly open multiseat input %s\", path);\n"
        "\t\t\treturn NULL;\n"
        "\t\t}\n"
        "\t\tstruct wlr_device *input_dev = wlr_fd_to_device(session, input_fd);\n"
        "\t\tif (!input_dev) {\n"
        "\t\t\tclose(input_fd);\n"
        "\t\t\treturn NULL;\n"
        "\t\t}\n"
        "\t\treturn input_dev;\n"
        "\t}\n\n"
    )
    text = text[: match.end()] + block + text[match.end() :]

    close_old = "\tdlm_release_lease(dev->drm_lease);\n"
    close_new = (
        "\tif (dev->drm_lease) {\n"
        "\t\tdlm_release_lease(dev->drm_lease);\n"
        "\t}\n"
    )
    if close_new not in text:
        if close_old not in text:
            raise RuntimeError("Não achei dlm_release_lease() esperado em session.c")
        text = text.replace(close_old, close_new, 1)

    if "\\t/* Multi Seat Arch" in text:
        raise RuntimeError("Transformação gerou escape literal \\t em C")
    return text


def patch_file(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    patched = transform_text(original)
    path.write_text(patched, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <backend/session/session.c>", file=sys.stderr)
        return 2
    try:
        patch_file(Path(sys.argv[1]))
    except (OSError, RuntimeError) as exc:
        print(f"Falha ao transformar wlroots: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
