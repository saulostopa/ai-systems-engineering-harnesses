#!/usr/bin/env python3
"""check-contrast.py — measure every colour token in an Archify theme overlay.

A palette applied by hand is a palette nobody measured. This walks each block of
eleanor-theme.css, resolves the colours against that block's own `--bg`, and
fails when a token is below its floor.

Two floors, on purpose:
  text tokens    WCAG 1.4.3 contrast (minimum)     4.5:1
  stroke tokens  WCAG 1.4.11 non-text contrast     3.0:1

Using one bar for both would be wrong in either direction — too lax for the
labels a person has to read, too strict for the outline of a box.

Usage: python3 scripts/check-contrast.py scripts/eleanor-theme.css
"""

from __future__ import annotations

import re
import sys

TEXT_FLOOR = 4.5
STROKE_FLOOR = 3.0


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blocks(css: str) -> list[tuple[str, dict[str, str]]]:
    """Each `selector { … }` block, with its solid-hex declarations."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(match.group(1).split())[-72:]
        decls = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", match.group(2)))
        if decls:
            out.append((selector, decls))
    return out


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "scripts/eleanor-theme.css"
    css = open(path, encoding="utf-8").read()
    failures = 0
    checked = 0

    for selector, decls in blocks(css):
        background = decls.get("--bg")
        if not background:
            # A block with no --bg of its own inherits one; measuring against a
            # guess would produce numbers that mean nothing.
            continue
        print(f"\n{selector}\n  background {background}")
        for name, colour in decls.items():
            if name == "--bg":
                continue
            is_text = name.startswith("--text")
            is_stroke = name.endswith("-stroke") or name.startswith("--arrow")
            if not (is_text or is_stroke):
                continue
            floor = TEXT_FLOOR if is_text else STROKE_FLOOR
            ratio = contrast(colour, background)
            ok = ratio >= floor
            checked += 1
            if not ok:
                failures += 1
            print(f"    {name:22} {colour}  {ratio:5.2f}:1  floor {floor}  {'OK' if ok else 'FAIL'}")

    print(f"\n{checked} token(s) checked, {failures} below floor")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
