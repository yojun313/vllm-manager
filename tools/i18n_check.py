#!/usr/bin/env python3
"""화면 문구 점검: 코드에서 쓰는 키가 두 언어 사전에 모두 있는지, 두 사전의 키가 같은지 확인한다.

python3 tools/i18n_check.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "server" / "app"
src = (ROOT / "static/js/i18n.js").read_text(encoding="utf-8")


def keys_of(name: str) -> set[str]:
    block = src[
        src.index(f"const {name} = {{") : src.index(
            "};", src.index(f"const {name} = {{")
        )
    ]
    return set(re.findall(r"'([A-Za-z0-9_.]+)':", block))


ko, en = keys_of("ko"), keys_of("en")
used, prefixes = set(), set()
for path in [*ROOT.glob("static/js/**/*.js"), *ROOT.glob("templates/*.html")]:
    text = path.read_text(encoding="utf-8")
    for key, tail in re.findall(r"\bt\('([A-Za-z0-9_.]+)'(\s*\+)?", text):
        (prefixes if tail else used).add(key)
    used.update(re.findall(r'data-i18n="([^"]+)"', text))
    used.update(re.findall(r"key: '([a-z]+\.[A-Za-z0-9_.]+)'", text))

problems = []
problems += [f"missing in ko: {k}" for k in sorted(used - ko)]
problems += [f"missing in en: {k}" for k in sorted(used - en)]
problems += [f"only in ko: {k}" for k in sorted(ko - en)]
problems += [f"only in en: {k}" for k in sorted(en - ko)]
dynamic = {k for k in ko if any(k.startswith(p) for p in prefixes)}
problems += [f"unused: {k}" for k in sorted(ko - used - dynamic)]
print("\n".join(problems) or f"ok: {len(ko)} keys, 2 languages")
sys.exit(1 if problems else 0)
