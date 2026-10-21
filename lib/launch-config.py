#!/usr/bin/env python3
"""자동 계산한 CLI 옵션과 중복되는 YAML 키를 실행용 사본에서 제거합니다."""

import os
from pathlib import Path
import re
import sys
import tempfile

source, target = map(Path, sys.argv[1:3])
overrides = {arg[2:].split("=", 1)[0] for arg in sys.argv[3:] if arg.startswith("--")}
lines = []
for line in source.read_text(encoding="utf-8").splitlines(keepends=True):
    key = re.match(r"^([a-z0-9-]+):", line)
    if key and key.group(1) in overrides:
        continue
    lines.append(line)
target.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".launch-")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(temporary, target)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
