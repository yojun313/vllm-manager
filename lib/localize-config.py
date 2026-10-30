#!/usr/bin/env python3
"""After a successful pull, point a matching repository config at local weights."""

import os
from pathlib import Path
import re
import sys
import tempfile

path, repo, model_ref = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
model_lines = [i for i, line in enumerate(lines) if re.match(r"^model:\s*", line)]
if len(model_lines) != 1:
    raise SystemExit(0)
i = model_lines[0]
value = lines[i].split(":", 1)[1].split(" #", 1)[0].strip().strip("'\"")
if value != repo:
    raise SystemExit(0)
lines[i] = "model: " + model_ref + "\n"
fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".localize-")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print("로컬 가중치 경로로 설정을 갱신했습니다: " + str(path))
