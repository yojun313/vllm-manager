#!/usr/bin/env python3
"""GPU 별로 새 모델에 줄 수 있는 여유 메모리(MiB)를 계산한다.

사용: ./vllm 의 list_containers 출력(탭 구분: 이름 GPU 모델 포트 예약MiB 상태 ID)을 stdin 으로 받아
      gpufree.py <교체될 컨테이너 이름 또는 -> <SAFETY_MIB>
출력: "<GPU번호> <여유MiB>" 줄들
(admin_server/run.py 는 gpu_usage() 를 직접 import 해서 쓴다)

GPU 사용량 = nvidia-smi 실사용량에서, 우리가 띄운 컨테이너 몫만 max(실사용, 예약량)으로 바꿔 계산한다.
→ 아직 로딩 중이라 메모리를 덜 잡은 모델도 예약량만큼 차지한 것으로 보고,
  다른 사람 프로세스나 예약 라벨 없는 예전 컨테이너는 실사용량 그대로 반영된다.
"""
import re
import subprocess
import sys


def smi(query, kind="gpu"):
    out = subprocess.run(["nvidia-smi", f"--query-{kind}={query}", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return [[x.strip() for x in line.split(",")] for line in out.strip().splitlines() if line.strip()]


def gpu_usage(containers, skip="-", safety=0):
    """containers: [(이름, "0,1", 예약MiB 또는 None, 짧은ID)]
    반환: [{idx, name, total, used, other, ours: {이름: MiB}, free_new}]  (단위 MiB)"""
    gpus = {g[1]: {"idx": g[0], "name": g[4], "total": int(g[2]), "used": int(g[3])}
            for g in smi("index,uuid,memory.total,memory.used,name")}
    ours = {cid[:12]: (name, cgpus.split(","), mem) for name, cgpus, mem, cid in containers if cid}

    # GPU 프로세스 → 컨테이너 (cgroup 경로의 64자리 컨테이너 ID)
    actual = {}  # (container id, gpu idx) → MiB
    for pid, used, uuid in smi("pid,used_memory,gpu_uuid", "compute-apps"):
        try:
            m = re.search(r"[0-9a-f]{64}", open(f"/proc/{pid}/cgroup").read())
        except OSError:
            m = None
        if m and m.group(0)[:12] in ours and uuid in gpus:
            key = (m.group(0)[:12], gpus[uuid]["idx"])
            actual[key] = actual.get(key, 0) + int(used)

    result = []
    for g in sorted(gpus.values(), key=lambda g: int(g["idx"])):
        other, mine = g["used"], {}
        for cid, (name, cgpus, mem) in ours.items():
            if g["idx"] not in cgpus:
                continue
            real = actual.get((cid, g["idx"]), 0)
            other -= real
            if name != skip:
                mine[name] = max(real, mem or 0)
        other = max(other, 0)
        result.append({**g, "other": other, "ours": mine,
                       "free_new": g["total"] - other - sum(mine.values()) - safety})
    return result


if __name__ == "__main__":
    containers = []
    for line in sys.stdin:
        f = line.rstrip("\n").split("\t")
        if len(f) >= 7 and f[0] and f[0] != "-":
            containers.append((f[0], f[1], int(f[4]) if f[4].isdigit() else None, f[6]))
    for g in gpu_usage(containers, sys.argv[1], int(sys.argv[2])):
        print(g["idx"], g["free_new"])
