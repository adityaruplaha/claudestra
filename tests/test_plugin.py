"""claudestra's Claude Code plugin pins the claudestra it installs: plugin.json, the hooks module and the
package must name one version, or a session would install one claudestra while the plugin expects another."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_plugin_pins_the_package_version():
    package = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    manifest = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())["version"]
    [pinned] = re.findall(r"export const VERSION = '([^']+)'", (ROOT / "plugin" / "hooks" / "register.ts").read_text())
    assert package == manifest == pinned


def test_the_marketplace_lists_the_plugin():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["plugins"] == [{"name": "claudestra", "source": "./plugin"}]
