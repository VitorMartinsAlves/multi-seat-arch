"""Canonical public GUI entry point.

Versioned GUI modules are retained temporarily as implementation layers while
phase-1 stabilization adds coverage. New callers should import from this module;
that lets the implementation be consolidated later without changing installed
entry points again.
"""

from .gui_v4 import MainWindow, main

__all__ = ["MainWindow", "main"]
