"""Hugging Face 모델 검색 (다운로드 입력란의 자동 완성)."""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

_cache: dict[str, tuple[float, list]] = {}


def search(query: str, limit: int = 10) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    hit = _cache.get(query)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(
        {"search": query, "limit": limit, "sort": "downloads", "direction": -1}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "vllm-manager"})
    token = Path.home() / ".cache/huggingface/token"
    if token.exists():
        req.add_header("Authorization", "Bearer " + token.read_text().strip())
    with urllib.request.urlopen(req, timeout=8) as r:
        rows = json.loads(r.read())
    out = [
        {
            "id": m.get("id", ""),
            "downloads": m.get("downloads") or 0,
            "likes": m.get("likes") or 0,
            "task": m.get("pipeline_tag") or "",
            "gated": bool(m.get("gated")),
        }
        for m in rows
        if "/" in m.get("id", "")
    ]
    if len(_cache) > 200:
        _cache.clear()
    _cache[query] = (time.time(), out)
    return out
