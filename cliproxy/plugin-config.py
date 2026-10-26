#!/usr/bin/env python3
"""Bat plugin deepseek-web-go trong config YAML cua PGSTORE.

DB la nguon su that khi PGSTORE bat, nen config.template.yaml mot minh khong du.
Script chi sua dung khoi plugins.configs, khong dung toi khoa/auth khac.
"""
import pathlib
import sys

PLUGIN = "deepseek-web-go"


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _is_content(line):
    s = line.strip()
    return bool(s) and not s.startswith("#")


def _find(lines, start, end, text, indent):
    for i in range(start, end):
        if _indent(lines[i]) == indent and lines[i].strip() == text:
            return i
    return -1


def _block_end(lines, start, indent):
    """Chi so dong dau tien sau khoi co indent <= indent (bo qua blank/comment)."""
    i = start
    while i < len(lines):
        if _is_content(lines[i]) and _indent(lines[i]) <= indent:
            return i
        i += 1
    return len(lines)


def merge(text):
    lines = text.splitlines()
    plugins = _find(lines, 0, len(lines), "plugins:", 0)
    if plugins < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["plugins:", "  enabled: true", "  configs:", "    %s:" % PLUGIN, "      enabled: true"])
        return "\n".join(lines) + "\n"

    plugins_end = _block_end(lines, plugins + 1, 0)
    configs = _find(lines, plugins + 1, plugins_end, "configs:", 2)
    if configs < 0:
        insert = plugins_end
        lines[insert:insert] = ["  configs:", "    %s:" % PLUGIN, "      enabled: true"]
        return "\n".join(lines) + "\n"

    configs_end = _block_end(lines, configs + 1, 2)
    plugin = _find(lines, configs + 1, configs_end, "%s:" % PLUGIN, 4)
    if plugin >= 0:
        plugin_end = _block_end(lines, plugin + 1, 4)
        enabled = _find(lines, plugin + 1, plugin_end, "enabled: true", 6)
        if enabled < 0:
            enabled = _find(lines, plugin + 1, plugin_end, "enabled: false", 6)
            if enabled >= 0:
                lines[enabled] = "      enabled: true"
            else:
                lines.insert(plugin + 1, "      enabled: true")
        return "\n".join(lines) + "\n"

    insert = configs_end
    lines[insert:insert] = ["    %s:" % PLUGIN, "      enabled: true"]
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("dung: plugin-config.py <config.yaml>")
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    merged = merge(text)
    if merged == text:
        print("plugins.%s: da co" % PLUGIN)
        return
    path.write_text(merged, encoding="utf-8")
    print("plugins.%s: da bat" % PLUGIN)


if __name__ == "__main__":
    main()
