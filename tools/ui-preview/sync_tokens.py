#!/usr/bin/env python3
"""Sinh khoi mau Material 3 trong ui-preview/_system/tokens.css tu Color.kt cua adroidClient.

Dung:
  python3 tools/ui-preview/sync_tokens.py <duong-dan-Color.kt> [--source-rev <git-sha>]
  python3 tools/ui-preview/sync_tokens.py <duong-dan-Color.kt> --check

Chi thay the phan giua 2 marker GENERATED trong tokens.css; phan con lai (type, shape,
spacing) giu nguyen. --check tra ma loi 1 neu tokens.css lech voi Color.kt.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[2] / "ui-preview" / "_system" / "tokens.css"
BEGIN = "/* BEGIN GENERATED COLORS"
END = "/* END GENERATED COLORS */"

# Vai tro M3 can xuat (theo ten bien Kotlin, bo hau to Light/Dark).
ROLES = [
    "primary", "onPrimary", "primaryContainer", "onPrimaryContainer",
    "secondary", "onSecondary", "secondaryContainer", "onSecondaryContainer",
    "tertiary", "onTertiary", "tertiaryContainer", "onTertiaryContainer",
    "error", "onError", "errorContainer", "onErrorContainer",
    "background", "onBackground", "surface", "onSurface",
    "surfaceVariant", "onSurfaceVariant", "outline", "outlineVariant", "scrim",
    "inverseSurface", "inverseOnSurface", "inversePrimary",
    "surfaceDim", "surfaceBright",
    "surfaceContainerLowest", "surfaceContainerLow", "surfaceContainer",
    "surfaceContainerHigh", "surfaceContainerHighest",
]

DECL = re.compile(r"^val\s+(\w+)\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)", re.M)


def kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def parse(color_kt: str) -> dict[str, str]:
    out = {}
    for name, argb in DECL.findall(color_kt):
        a, rgb = argb[:2].upper(), argb[2:].lower()
        out[name] = f"#{rgb}" if a == "FF" else f"#{rgb}{a.lower()}"
    return out


def block(colors: dict[str, str], source_rev: str) -> str:
    missing = [f"{r}{m}" for m in ("Light", "Dark") for r in ROLES if f"{r}{m}" not in colors]
    if missing:
        raise SystemExit(f"Color.kt thieu vai tro: {', '.join(missing)}")
    lines = [f"{BEGIN} tu adroidClient presentation/theme/Color.kt @ {source_rev}. KHONG sua tay; chay tools/ui-preview/sync_tokens.py */"]
    lines.append(":root, [data-theme=\"light\"] {")
    lines += [f"  --md-sys-color-{kebab(r)}: {colors[r + 'Light']};" for r in ROLES]
    lines.append("}")
    lines.append("[data-theme=\"dark\"] {")
    lines += [f"  --md-sys-color-{kebab(r)}: {colors[r + 'Dark']};" for r in ROLES]
    lines.append("}")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("color_kt", type=Path)
    ap.add_argument("--source-rev", default="unknown")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    colors = parse(args.color_kt.read_text(encoding="utf-8"))
    css = TOKENS.read_text(encoding="utf-8")
    start, stop = css.find(BEGIN), css.find(END)
    if start < 0 or stop < 0:
        raise SystemExit(f"{TOKENS} thieu marker GENERATED")
    stop += len(END)

    if args.check:
        current = css[start:stop]
        rev = re.search(r"Color\.kt @ (\S+)\.", current)
        expected = block(colors, rev.group(1) if rev else "unknown")
        if current != expected:
            print("tokens.css LECH voi Color.kt — chay lai sync_tokens.py", file=sys.stderr)
            return 1
        print("tokens.css khop Color.kt")
        return 0

    TOKENS.write_text(css[:start] + block(colors, args.source_rev) + css[stop:], encoding="utf-8")
    print(f"Da cap nhat {TOKENS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
