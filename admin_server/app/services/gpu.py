"""GPU 실시간 상태. 메모리 분해(모델별/다른 프로세스/새 모델용 여유)는 ../lib/gpufree.py 를 그대로 써서
CLI(./vllm ps, up 의 용량 검사)와 숫자가 항상 같게 한다."""

import importlib.util

from app.config import LIB_DIR, SAFETY_MIB, managed_gpu_ids
from app.services import docker

_spec = importlib.util.spec_from_file_location("gpufree", LIB_DIR / "gpufree.py")
gpufree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpufree)


def snapshot() -> list[dict]:
    containers = docker.list_containers()
    gpus = gpufree.gpu_usage([(c["name"], c["gpus"], c["mem"], c["id"]) for c in containers], "-", SAFETY_MIB)
    # vllm.env 의 GPU_COUNT / GPU_IDS 로 정한 GPU 만 보여주고 선택지로 쓴다
    allowed = set(managed_gpu_ids([g["idx"] for g in gpus]))
    gpus = [g for g in gpus if g["idx"] in allowed]
    extra = {row[0]: row for row in gpufree.smi("index,utilization.gpu,temperature.gpu,power.draw,power.limit")}
    name_to_model = {c["name"]: c["model"] for c in containers}
    for g in gpus:
        idx, util, temp, power, limit = extra.get(g["idx"], [g["idx"], "0", "0", "0", "0"])
        g["util"] = _num(util)
        g["temp"] = _num(temp)
        g["power"] = _num(power)
        g["power_limit"] = _num(limit)
        g["ours"] = [{"name": n, "model": name_to_model.get(n, n), "mib": m} for n, m in g["ours"].items()]
    return gpus


def _num(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0
