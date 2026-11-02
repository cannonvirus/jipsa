"""자원 측정과 리스.

측정은 nvidia-smi(VRAM과 점유 프로세스), psutil(RAM), Ollama /api/ps(적재 모델)다. 리스는
runtime/state/leases.json에 작업, 자원, 양, pid, 시작, 만료를 적는다. 만료가 지나면 pid 생존을 확인한 뒤 회수한다.

GPU 장부(261026-jipsa-26): 리스 파일이 장부다. pid는 작업자 프로세스 번호(어댑터가 띄운 직후 spawned로 바꾼다)나
세션 begin의 Claude Code 프로세스 번호다. GPU가 필요 없는 작업자도 몫 0의 감시 줄(watch)로 적어 실측 최댓값을 잰다. 남은 자리는
전체 - 장부 몫 합 - 장부 밖 실측 - 다른 Cycle의 단계 사이 예약이다. 장부 밖 실측은 전체 사용량에서 장부 줄 프로세스 트리의 성능 카운터 실측을
뺀 값이고, 성능 카운터가 비면 전체 사용량에서 장부 합을 뺀 값이다. 대기열, 예약, 실측 초과, 프로젝트별 실측 최댓값은 gpu_ledger.json이다.

실측 기반 예약(261029-jipsa-07, 261029-jipsa-04 2안): 시작 판정은 요구량으로 하고, 시작 뒤 관찰 시간(10분)이 지나면 그 줄의 몫을
그동안의 실측 최댓값 + 1GB로 고친다. 학습, 대량 추론, 모델 서버처럼 큰 GPU 일은 작업이 시작 직전에 신호(jipsa gpu signal)를 보낸다. 신호가 오면
몫을 지난 최댓값으로 되올리고 5분 동안 새 GPU 작업을 들이지 않은 채 실측을 보고, 그 최댓값 + 1GB로 다시 고친다. 끝 신호나 반납 때는 관찰 값으로
돌아간다. 실측은 실행 폴더(worktrees/<실행ID>, runs/<실행ID>)가 명령줄이나 작업 폴더에 든 프로세스를 그 줄에 먼저 붙이고, 나머지는 프로세스 트리로
붙인다. 작업자 셸이 띄운 프로세스가 트리 밖으로 떨어져 장부 밖 사용으로 두 번 세던 문제(261028-jipsa-15)를 막는다.

RAM 예약(261029-jipsa-17, GPU와 같은 방식): 장부 줄마다 RAM 몫(ram_gb)을 둔다. 시작 때는 요구량(한도 칸 RAM, 프로젝트의 지난 실측 최댓값,
기본값 순)이고, 관찰 시간(5분)이 지나면 그 줄 프로세스 트리의 실측 최댓값 + 여유(1GB)로 고친다(reconcile_ram). 새 작업이 쓸 수 있는 RAM은
지금 남은 양에서 장부 줄마다 몫이 실측보다 큰 만큼(아직 쓰지 않은 예약)을 뺀 값이다. 모자라면 GPU와 같은 대기열에 서고, 앞 줄이 먼저 든다.
세션 줄은 트리가 Claude Code 세션 전체라 RAM 몫을 두지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

import psutil
import requests

from scheduler.config import (GPU_JUMP_MIN, GPU_OBSERVE_MIN, GPU_OVER_HOLD_MIN, GPU_PAD_GB, GPU_RESERVE_MIN, GPU_SIGNAL_MIN, OLLAMA_URL, RAM_DEFAULT_GB,
                              RAM_OBSERVE_MIN, RAM_PAD_GB, RUNS, STATE, WORKTREES, now, now_iso, parse_iso)
from scheduler.nowindow import hidden
from scheduler.registry import Project, load_all

LEASES_FILE = STATE / "leases.json"
_lock = threading.Lock()
_OLLAMA_TIMEOUT = (0.3, 3)  # (연결, 응답) 제한. 꺼진 서버에 연결하면 2초를 기다렸다. 로컬 연결은 0.3초면 충분하다
_OLLAMA_DOWN_SEC = 30  # 화면 요약은 꺼져 있던 사실을 이만큼 기억하고 다시 연결하지 않는다(261023-jipsa-17)
_ollama_down_at = 0.0


def _fake_gpu() -> dict | None:
    """시험용 가짜 GPU 값(JIPSA_FAKE_GPU에 JSON 파일 경로). {"total": GB, "used": GB, "mem": {"pid": GB}}. 운영에서는 쓰지 않는다."""
    path = os.environ.get("JIPSA_FAKE_GPU", "").strip()
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"total": 0, "used": 0, "mem": {}, "ok": False}


def gpu_status() -> dict:
    """{"total_gb", "used_gb", "procs": [{"pid","used_gb","name"}], "ok"}"""
    fake = _fake_gpu()
    if fake is not None:
        procs = [{"pid": int(k), "used_gb": 0.0, "name": "fake"} for k in (fake.get("mem") or {})]
        return {"total_gb": float(fake.get("total") or 0), "used_gb": float(fake.get("used") or 0), "procs": procs, "ok": fake.get("ok", True)}
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, check=False, **hidden())
        total, used = [float(x) for x in q.stdout.strip().splitlines()[0].split(",")]
        procs = []
        a = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory,process_name", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, check=False, **hidden())
        for line in a.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0].isdigit():
                # Windows는 used_memory를 [N/A]로 줄 때가 많다. 숫자가 아니면 0으로 본다.
                try:
                    used_gb = round(float(parts[1]) / 1024, 1)
                except ValueError:
                    used_gb = 0.0
                procs.append({"pid": int(parts[0]), "used_gb": used_gb, "name": parts[2] if len(parts) > 2 else ""})
        return {"total_gb": round(total / 1024, 1), "used_gb": round(used / 1024, 1), "procs": procs, "ok": True}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"total_gb": 0.0, "used_gb": 0.0, "procs": [], "ok": False}


_MEM_TTL = 60  # 조회 한 번이 1.6초다. 15초면 화면 주기(15초)마다 다시 돌았다. 지나면 옛 값을 주고 뒤에서 다시 잰다
_mem_cache: tuple[float, dict[int, float]] = (0.0, {})
_mem_refreshing = threading.Lock()
_SYSTEM_DIRS = tuple(f"{os.environ.get('SystemDrive', 'C:').lower()}/{d}/" for d in ("windows", "program files", "program files (x86)", "programdata"))
_SYSTEM_NAMES = {"chrome", "msedge", "firefox", "code", "explorer", "dwm", "slack", "discord", "steam"}


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def gpu_proc_memory() -> dict[int, float]:
    """Windows 성능 카운터의 프로세스별 전용 VRAM(GB). nvidia-smi가 [N/A]를 줘도 이 값은 얻는다. 실패하면 빈 값이다.
    처음에는 기다려 잰다. 그 뒤로는 보관 시간이 지나도 옛 값을 바로 주고 뒤에서 한 번만 다시 잰다."""
    fake = _fake_gpu()
    if fake is not None:
        return {int(k): float(v) for k, v in (fake.get("mem") or {}).items()}
    at, cached = _mem_cache
    if time.time() - at < _MEM_TTL:
        return cached
    if not at:
        return _measure_proc_memory()
    if _mem_refreshing.acquire(blocking=False):
        def run() -> None:
            try:
                _measure_proc_memory()
            finally:
                _mem_refreshing.release()
        threading.Thread(target=run, daemon=True).start()
    return cached


def _measure_proc_memory() -> dict[int, float]:
    global _mem_cache
    out: dict[int, float] = {}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             r"(Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples"
             " | ForEach-Object { '{0} {1}' -f $_.InstanceName, [int64]$_.CookedValue }"],
            capture_output=True, text=True, timeout=10, check=False, **hidden())
        for line in r.stdout.splitlines():
            m = re.match(r"pid_(\d+)_\S+ (\d+)", line.strip())
            if m:
                out[int(m.group(1))] = out.get(int(m.group(1)), 0.0) + int(m.group(2)) / 1024**3
    except (OSError, subprocess.TimeoutExpired):
        out = {}
    _mem_cache = (time.time(), out)
    return out


def _proc_texts(proc: psutil.Process) -> tuple[str, str]:
    """(실행 파일 경로, 명령줄과 작업 폴더를 이은 글). 읽지 못하는 값은 비운다."""
    try:
        exe = proc.exe()
    except (psutil.Error, OSError):
        exe = ""
    parts: list[str] = []
    for fn in (proc.cmdline, proc.cwd):
        try:
            v = fn()
            parts.append(" ".join(v) if isinstance(v, list) else v)
        except (psutil.Error, OSError):
            pass
    return _norm(exe), _norm(" ".join(parts))


def _owner_of(pid: int, projects: dict, ollama_names: list[str]) -> tuple[str, str]:
    """(종류, 이름). 종류는 project, ollama, other다. other의 이름은 프로세스 이름이다."""
    try:
        proc = psutil.Process(pid)
        pname = proc.name().lower().removesuffix(".exe")
    except (psutil.Error, OSError):
        return "other", "알 수 없음"
    exe, _ = _proc_texts(proc)
    if "ollama" in exe or "ollama" in pname:
        return "ollama", "Ollama" + (f"({', '.join(ollama_names)})" if ollama_names else "")
    if exe.startswith(_SYSTEM_DIRS) and "python" not in pname or pname in _SYSTEM_NAMES or "/windowsapps/" in exe:
        return "other", pname
    wt = _norm(str(WORKTREES)) + "/"
    chain = [proc]
    try:
        chain += proc.parents()[:6]
    except (psutil.Error, OSError):
        pass
    for pr in chain:
        e, text = _proc_texts(pr)
        text = e + " " + text
        i = text.find(wt)
        if i >= 0:  # worktrees/<실행ID>는 실행 기록의 프로젝트로 푼다
            run_id = re.split(r"[/ \"']", text[i + len(wt):], maxsplit=1)[0]
            try:
                meta = json.loads((RUNS / run_id / "meta.json").read_text(encoding="utf-8"))
                pj = meta.get("project", "?")
                return "project", f"{'기타' if pj == 'misc' else pj}({run_id})"  # 등록부 misc는 화면에서 기타다
            except (OSError, ValueError):
                return "project", run_id
        best = ""
        for name, pj in projects.items():
            base = _norm(str(pj.path))
            if base in text and len(base) > len(best) and not (name == "misc"):
                best = base
                hit = name
        if best:
            return "project", hit
    return "other", pname


def gpu_owners(procs: list[dict], ollama_names: list[str] | None = None) -> list[dict]:
    """GPU 점유 프로세스를 주인별로 묶는다. [{"kind","name","gb"(모르면 None),"procs"}], 프로젝트가 앞, Ollama가 뒤다.
    프로젝트 폴더에 속하지 않는 일반 점유(브라우저, 데스크톱 등)는 컴퓨터 일반 점유율이라 뺀다.
    ollama_names는 이미 물어 본 적재 모델이다. 없으면 여기서 묻는다."""
    if not procs:
        return []
    try:
        projects = load_all()
    except Exception:  # 등록부 오류로 대시보드가 멈추면 안 된다
        projects = {}
    mem = gpu_proc_memory()
    names = (ollama_loaded() if ollama_names is None else ollama_names) or []
    groups: dict[tuple[str, str], dict] = {}
    for p in procs:
        kind, name = _owner_of(p["pid"], projects, names)
        gb = p["used_gb"] or mem.get(p["pid"])
        if kind == "other":
            continue
        g = groups.setdefault((kind, name), {"kind": kind, "name": name, "gb": None, "procs": 0})
        g["procs"] += 1
        if gb is not None:
            g["gb"] = round((g["gb"] or 0) + gb, 2)
    rows = list(groups.values())
    order = {"project": 0, "ollama": 1}
    rows.sort(key=lambda g: (order[g["kind"]], -(g["gb"] or 0)))
    return rows


def format_owners(owners: list[dict]) -> str:
    """한 줄 요약. 프로젝트 사용이 없으면 그렇게 적는다."""
    def one(g: dict) -> str:
        return f"{g['name']} {'메모리 모름' if g['gb'] is None else format(g['gb'], '.1f') + 'GB'}"
    return ", ".join(one(g) for g in owners) or "프로젝트 사용 없음"


def ram_free_gb() -> float:
    return round(psutil.virtual_memory().available / 1024**3, 1)


def ollama_loaded(remember: bool = False) -> list[str] | None:
    """적재 모델 이름. 서버가 없으면 None. remember면 꺼져 있던 사실을 30초 동안 기억해 다시 연결하지 않는다(화면 요약용).
    모델을 내리거나 자원을 판단하는 곳은 기억한 값을 쓰지 않고 늘 묻는다."""
    global _ollama_down_at
    if remember and time.monotonic() - _ollama_down_at < _OLLAMA_DOWN_SEC:
        return None
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/ps", timeout=_OLLAMA_TIMEOUT)
        if not resp.ok:
            return None
        names = [m.get("name") or m.get("model") for m in resp.json().get("models", [])]
    except requests.ConnectionError:
        _ollama_down_at = time.monotonic()
        return None
    except (requests.RequestException, ValueError):
        return None
    _ollama_down_at = 0.0
    return names


def ollama_unload(name: str) -> bool:
    """keep_alive 0으로 내린다."""
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=15)
        return resp.ok
    except requests.RequestException:
        return False


def _load() -> list[dict]:
    try:
        return json.loads(LEASES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(rows: list[dict]) -> None:
    LEASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEASES_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def leases() -> list[dict]:
    return _load()


def held(rows: list[dict] | None = None) -> list[dict]:
    """GPU 몫을 잡은 장부 줄. GPU가 필요 없는 작업자의 감시 줄(watch)은 빼고 센다."""
    return [r for r in (_load() if rows is None else rows) if not r.get("watch")]


def expire() -> list[dict]:
    """프로세스가 죽은 장부 줄을 회수한다. 작업자 프로세스 번호가 적힌 줄은 그 프로세스가 죽으면 바로, 아직 작업자를 띄우기 전 줄(스케줄러
    번호)과 세션 줄은 만료가 지나고 프로세스가 죽었을 때 회수한다(261026-jipsa-26, 전에는 늘 스케줄러 번호라 작업자가 죽어도 회수하지 못했다)."""
    with _lock:
        rows = _load()
        keep, gone = [], []
        for r in rows:
            expired = parse_iso(r["expires"]) < now()
            alive = r.get("pid") and psutil.pid_exists(int(r["pid"]))
            if not alive and (expired or r.get("pid_kind") == "worker"):
                gone.append(r)
            else:
                keep.append(r)
        if gone:
            _save(keep)
        return gone


HUMAN_GPU_GB = 2.0  # 리스 없이 이만큼 넘게 쓰는 GPU 프로세스는 사람이 띄운 작업으로 본다


def human_gpu_jobs(gpu: dict, rows: list[dict] | None = None) -> list[dict]:
    """jipsa 리스의 pid가 아니면서 GPU를 2GB 넘게 쓰는 프로세스. 사람이 띄운 GPU 작업으로 본다."""
    rows = _load() if rows is None else rows
    mine = {int(r.get("pid") or 0) for r in rows}
    return [p for p in gpu.get("procs") or [] if p["pid"] not in mine and p["used_gb"] >= HUMAN_GPU_GB]


def can_acquire(project: Project, *, key: str = "", kind: str = "", title: str = "", owner: str = "") -> tuple[bool, str]:
    """프로젝트가 지금 자원을 얻을 수 있는지. (가능 여부, 사유).

    GPU 장부(261026-jipsa-26): 남은 자리는 전체 용량에서 장부 합, 장부 밖 실측, 다른 Cycle의 단계 사이 예약을 뺀 값이다.
    key를 주면 GPU 대기열에 선다. 모자라면 대기열에 남고, 자리가 있어도 앞 줄이 먼저 들 수 있으면 기다린다. 맨 앞이 30분을 기다리기 전에는
    앞 줄이 들어가지 못하는 빈 자리에 작은 줄이 먼저 든다. 실측이 장부보다 커 장부를 올린 뒤 10분은 새 GPU 작업을 멈춘다.
    RAM(261029-jipsa-17): 새 작업이 쓸 수 있는 RAM(ram_view의 free)이 요구량보다 적으면 대기열에 선다. GPU를 쓰지 않는 작업은 GPU 대기와
    무관하게 RAM만 보고, 앞에 RAM이 모자라 기다리는 줄이 지금 자리에 들 수 있으면 그 줄이 먼저다."""
    ram = ram_view()
    ram_need = ram_need_gb(project)
    if not project.needs_gpu:
        if ram_need and ram["free"] < ram_need:
            return _queue_wait(key, project, kind, title, f"RAM 부족: 남은 {ram['free']:.1f}GB, 필요 {ram_need:.1f}GB", 0.0)
        if key:
            ahead = _ram_ahead(key, ram["free"])
            if ahead:
                return _queue_wait(key, project, kind, title, ahead, 0.0)
            queue_drop(key)
        return True, ""
    rows = held()
    if any(r.get("exclusive") for r in rows):
        return _queue_wait(key, project, kind, title, "GPU 배타 작업이 돌고 있다")
    if project.gpu_exclusive and rows:
        return _queue_wait(key, project, kind, title, "다른 GPU 작업이 장부에 있다")
    gpu = gpu_status()
    if not gpu["ok"]:
        return False, "nvidia-smi 응답 없음"
    over = ledger_state().get("over")
    if over and parse_iso(over["until"]) > now():
        return _queue_wait(key, project, kind, title, f"실측이 장부보다 커 새 GPU 작업을 {over['until'][11:16]}까지 멈췄다({over.get('project')})")
    sig = next((r for r in rows if _signal_live(r)), None)
    if sig:
        s = sig["signal"]
        until = "자리가 날 때" if s.get("waiting") else f"{s['until'][11:16]}"
        return _queue_wait(key, project, kind, title, f"큰 GPU 작업 관찰 중이라 새 GPU 작업을 {until}까지 들이지 않는다({sig.get('project')} {s.get('kind')})")
    view = ledger_view(gpu, owner=owner)
    free = view["free"]
    need = need_gb(project, gpu)
    if project.gpu_exclusive:
        # 사람이 띄운 학습은 VRAM을 크게 쓴다. 장부 밖 점유가 4GB 넘으면 배타 작업을 시작하지 않는다
        if view["outside"] >= 4.0:
            return _queue_wait(key, project, kind, title, f"장부 밖 VRAM {view['outside']:.1f}GB 사용 중 (사람이 띄운 작업으로 본다)")
    if need and free < need:
        return _queue_wait(key, project, kind, title, f"VRAM 부족: 남은 {free:.1f}GB, 필요 {need:.1f}GB", need)
    if ram_need and ram["free"] < ram_need:
        return _queue_wait(key, project, kind, title, f"RAM 부족: 남은 {ram['free']:.1f}GB, 필요 {ram_need:.1f}GB", need)
    if project.ollama_models:
        loaded = ollama_loaded()
        if loaded:
            foreign = [m for m in loaded if m not in project.ollama_models]
            if foreign and project.gpu_exclusive:
                return False, f"Ollama에 다른 모델이 적재됨: {', '.join(foreign)}"
    # 단계 사이 예약을 가진 Cycle 목표는 그 몫을 먼저 받는다. 대기열 앞 줄 판정을 건너뛴다(261026-jipsa-26 공격 답)
    reserved = bool(owner) and any(x.get("owner") == owner and parse_iso(x["until"]) > now() for x in ledger_state()["reserve"])
    if key and not reserved:
        ahead = _ahead(key, free, ram["free"])
        if ahead:
            return _queue_wait(key, project, kind, title, ahead, need)
    if key:
        queue_drop(key)
    return True, ""


def can_acquire_auto(project: Project, **kw) -> tuple[bool, str]:
    """Auto 목록 줄의 판정. 장부가 장부 밖 점유(사람의 GPU 작업 포함)를 빼고 남은 자리를 세므로 can_acquire와 같다."""
    return can_acquire(project, **kw)


# ----- GPU 장부와 대기열(261026-jipsa-26) -----
LEDGER_FILE = STATE / "gpu_ledger.json"  # 대기열(rows), 단계 사이 예약(reserve), 실측 초과(over), 프로젝트별 지난 실측 최댓값(peak)
_STALE_SEC = 120  # 대기열 줄을 이만큼 다시 보지 않으면 뺀다. 요청이 사라졌거나 다른 사유로 기다리는 줄이다


def ledger_state() -> dict:
    try:
        st = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    for k, v in (("rows", []), ("reserve", []), ("peak", {})):
        st.setdefault(k, v)
    return st


def _ledger_save(st: dict) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_FILE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, LEDGER_FILE)


def need_gb(project: Project, gpu: dict | None = None) -> float:
    """GPU 요구량. 할 일 줄 한도 칸(effective가 넣는다), 등록부, 지난 실측 최댓값 순이다. 배타이고 값이 없으면 전체의 80%다."""
    if project.gpu_vram_gb:
        return float(project.gpu_vram_gb)
    if project.gpu_exclusive:
        gpu = gpu or gpu_status()
        return gpu["total_gb"] * 0.8
    return float(ledger_state()["peak"].get(project.name) or 0)


def with_peak(project: Project) -> Project:
    """등록부와 한도 칸에 GPU 요구량이 없는 프로젝트에 지난 실측 최댓값을 요구량으로 넣는다. 1GB 아래는 넣지 않는다."""
    from dataclasses import replace

    if project.gpu_vram_gb or project.gpu_exclusive:
        return project
    peak = float(ledger_state()["peak"].get(project.name) or 0)
    return replace(project, gpu_vram_gb=round(peak, 1)) if peak >= 1.0 else project


# ----- RAM 예약(261029-jipsa-17) -----
def ram_need_gb(project: Project) -> float:
    """RAM 요구량. 할 일 줄 한도 칸(effective가 넣는다)이나 등록부 값, 프로젝트의 지난 실측 최댓값, 기본값 순이다."""
    if project.ram_gb:
        return float(project.ram_gb)
    peak = float(ledger_state().get("ram_peak", {}).get(project.name) or 0)
    return round(peak, 1) if peak >= 0.5 else RAM_DEFAULT_GB


def _tree_rss(pid: int | None) -> float | None:
    """프로세스 트리의 RAM 실측(GB). 읽지 못하면 None이다."""
    if not pid:
        return None
    total, ok = 0, False
    for p in _tree(pid):
        try:
            total += psutil.Process(p).memory_info().rss
            ok = True
        except (psutil.Error, OSError):
            continue
    return round(total / 1024**3, 2) if ok else None


def ram_view(rows: list[dict] | None = None) -> dict:
    """RAM 계산. {"total","available","reserved","unused","free","rows":[{run, project, gb, measured, basis}]}.
    unused는 장부 줄마다 몫이 실측보다 큰 만큼의 합(예약했으나 아직 쓰지 않은 양)이고, free는 지금 남은 양에서 그것을 뺀 값이다."""
    vm = psutil.virtual_memory()
    total, avail = round(vm.total / 1024**3, 1), round(vm.available / 1024**3, 1)
    out, reserved, unused = [], 0.0, 0.0
    for r in _load() if rows is None else rows:
        gb = float(r.get("ram_gb") or 0)
        if not gb:
            continue
        m = r.get("ram_now")
        reserved += gb
        unused += max(0.0, gb - float(m or 0))
        out.append({"run": r.get("run"), "project": r.get("project"), "gb": round(gb, 1), "measured": m, "owner": r.get("owner") or "",
                    "basis": "실측" if r.get("ram_observed") else "요구량"})
    return {"total": total, "available": avail, "reserved": round(reserved, 1), "unused": round(unused, 1),
            "free": round(avail - unused, 1), "rows": out}


def reconcile_ram() -> list[dict]:
    """30초마다 장부 줄의 RAM 실측을 재고 몫을 고친다. 관찰 시간이 지난 줄은 몫을 그동안의 실측 최댓값 + 여유로 고치고(observe),
    그 뒤 실측이 몫보다 0.5GB 넘게 크면 실측으로 올린다(over). 작업자 줄의 실측 최댓값은 프로젝트별로 남겨 다음 요구량으로 쓴다. 고친 줄이다."""
    out = []
    with _lock:
        rows = _load()
        st = ledger_state()
        peaks = st.setdefault("ram_peak", {})
        changed = peak_changed = False
        at = now()
        for r in rows:
            if not r.get("ram_gb") or r.get("pid_kind") == "session":
                continue
            m = _tree_rss(r.get("pid"))
            if m is None:
                continue
            r["ram_now"] = m
            changed = True
            if m > float(r.get("ram_seen") or 0):
                r["ram_seen"] = m
            if r.get("pid_kind") == "worker" and m >= 0.5 and m > float(peaks.get(r["project"]) or 0):
                peaks[r["project"]] = round(m, 1)
                peak_changed = True
            was = float(r.get("ram_gb") or 0)
            if not r.get("ram_observed") and r.get("pid_kind") == "worker" and at >= parse_iso(r["start"]) + timedelta(minutes=RAM_OBSERVE_MIN):
                new = round(float(r.get("ram_seen") or 0) + RAM_PAD_GB, 1)
                r["ram_claim"], r["ram_gb"], r["ram_observed"] = was, new, now_iso()
                out.append({"kind": "observe", "run": r.get("run"), "project": r.get("project"), "was": was, "now": new})
            elif r.get("ram_observed") and m > was + 0.5:
                r["ram_gb"] = round(m, 1)
                out.append({"kind": "over", "run": r.get("run"), "project": r.get("project"), "was": was, "now": r["ram_gb"]})
        if changed:
            _save(rows)
        if peak_changed:
            _ledger_save(st)
    return out


def _tree(pid: int | None) -> list[int]:
    if not pid:
        return []
    try:
        p = psutil.Process(int(pid))
        return [p.pid] + [c.pid for c in p.children(recursive=True)]
    except (psutil.Error, OSError, ValueError):
        return [int(pid)]


_RUN_IDS_TTL = 60  # 프로세스별 실행ID 조회를 이만큼 기억한다. 화면과 루프가 자주 부른다
_run_ids_cache: dict[int, tuple[float, list[str]]] = {}


def _run_ids(pid: int) -> list[str]:
    """프로세스와 부모 사슬(6단계)의 명령줄과 작업 폴더에 든 실행 폴더 이름(worktrees/<이름>, runs/<이름>). 읽지 못하면 비운다."""
    hit = _run_ids_cache.get(pid)
    if hit and time.time() - hit[0] < _RUN_IDS_TTL:
        return hit[1]
    marks = (_norm(str(WORKTREES)) + "/", _norm(str(RUNS)) + "/")
    found: list[str] = []
    try:
        proc = psutil.Process(pid)
        chain = [proc] + proc.parents()[:6]
    except (psutil.Error, OSError):
        chain = []
    for pr in chain:
        e, text = _proc_texts(pr)
        text = e + " " + text
        for mark in marks:
            i = text.find(mark)
            while i >= 0:
                name = re.split(r"[/ \"']", text[i + len(mark):], maxsplit=1)[0]
                if name and name not in found:
                    found.append(name)
                i = text.find(mark, i + 1)
    _run_ids_cache[pid] = (time.time(), found)
    return found


def _is_ollama(pid: int) -> bool:
    try:
        return "ollama" in psutil.Process(pid).name().lower()
    except (psutil.Error, OSError):
        return False


def _measure_rows(rows: list[dict], mem: dict[int, float]) -> dict[str, float]:
    """장부 줄마다 실측(GB). 프로세스 하나는 한 줄에만 붙인다. 실행 폴더 이름이 줄의 실행ID와 같거나 '실행ID-'로 시작하면 그 줄이 먼저이고,
    아니면 그 프로세스를 트리에 둔 줄(작업자 줄이 세션 줄보다 앞)이다. 세션 줄의 트리는 Claude Code 세션 전체라 여러 줄이 겹치기 때문이다."""
    runs = [r.get("run") for r in rows if r.get("run")]
    ordered = sorted(rows, key=lambda r: r.get("pid_kind") == "session")
    trees = [(r.get("run"), set(_tree(r.get("pid")))) for r in ordered if r.get("run")]
    llm = [r.get("run") for r in rows if r.get("run") and r.get("ollama_models") and not r.get("watch")]
    out = {run: 0.0 for run in runs}
    if not runs:
        return out
    if len(_run_ids_cache) > 500:
        _run_ids_cache.clear()
    for pid, gb in mem.items():
        if gb <= 0.01:
            continue
        names = _run_ids(pid)
        run = next((x for x in runs for n in names if n == x or n.startswith(x + "-")), "")
        if not run:
            run = next((x for x, tree in trees if pid in tree), "")
        if not run and len(llm) == 1 and _is_ollama(pid):
            run = llm[0]  # Ollama 서버는 작업 트리 밖이다. Ollama 모델을 쓰는 줄이 하나면 그 줄의 실측이다
        if run:
            out[run] += gb
    return out


def ledger_view(gpu: dict | None = None, owner: str = "", rows: list[dict] | None = None) -> dict:
    """장부 계산. {"total","used","leased","outside","reserve","free","rows":[{..,"measured"}]}.

    장부 밖 점유는 전체 사용량에서 장부 줄 프로세스(작업자와 그 자손)의 실측 합을 뺀 값이다. Windows의 nvidia-smi는 프로세스별 값을
    비우므로 성능 카운터 값을 쓰고, 그것도 없으면 전체 사용량에서 장부 합을 뺀 값으로 어림한다. owner는 예약을 빼지 않을 Cycle 목표다."""
    gpu = gpu or gpu_status()
    all_rows = _load() if rows is None else rows
    mine = held(all_rows)
    mem = gpu_proc_memory() if gpu.get("ok") else {}
    leased = round(sum(float(r.get("amount_gb") or 0) for r in mine), 2)
    out_rows = []
    measured_sum = 0.0
    per_run = _measure_rows(all_rows, mem) if mem else {}
    for r in all_rows:
        m = round(per_run.get(r.get("run"), 0.0), 2) if mem else None
        measured_sum += m or 0.0
        out_rows.append({**r, "measured": m})
    if mem:
        outside = max(0.0, gpu["used_gb"] - measured_sum)
    else:
        outside = max(0.0, gpu["used_gb"] - leased)
    st = ledger_state()
    reserve = sum(float(x.get("gb") or 0) for x in st["reserve"] if parse_iso(x["until"]) > now() and x.get("owner") != owner)
    free = gpu["total_gb"] - leased - outside - reserve
    return {"total": gpu["total_gb"], "used": gpu["used_gb"], "leased": leased, "outside": round(outside, 2), "reserve": round(reserve, 2),
            "free": round(free, 2), "rows": out_rows, "ok": bool(gpu.get("ok"))}


def _order(rows: list[dict]) -> list[dict]:
    """대기열 순서. 사람이 정한 자리(order 값)가 앞이고, 같으면 먼저 온 순서다. order는 처음 설 때 선 시각이다."""
    return sorted(rows, key=lambda r: (float(r.get("order") or 0), r.get("since") or ""))


def _queue_wait(key: str, project: Project, kind: str, title: str, why: str, need: float | None = None) -> tuple[bool, str]:
    """대기열에 서거나 사유를 고친다. key가 없으면(옛 호출) 대기열에 서지 않고 사유만 돌려준다."""
    if not key:
        return False, why
    with _lock:
        st = ledger_state()
        at = now_iso()
        row = next((r for r in st["rows"] if r["key"] == key), None)
        if row is None:
            row = {"key": key, "project": project.name, "title": title or key, "kind": kind, "since": at, "order": time.time()}
            st["rows"].append(row)
        row.update(need=round(need if need is not None else need_gb(project), 1), ram=round(ram_need_gb(project), 1), why=why, seen=at)
        if title:
            row["title"] = title
        _ledger_save(st)
    return False, why


def _ahead(key: str, free: float, ram_free: float | None = None) -> str:
    """자리가 있어도 기다릴 사유. 앞 줄 가운데 지금 자리에 드는 줄이 있으면 그 줄이 먼저다. 앞 줄이 하나도 들지 못하면
    맨 앞이 30분을 기다리기 전에는 작은 줄이 앞지르고, 넘었으면 맨 앞이 들 때까지 기다린다. ram_free를 주면 RAM도 들어야 드는 줄이다."""
    st = ledger_state()
    cut = now() - timedelta(seconds=_STALE_SEC)
    rows = [r for r in _order(st["rows"]) if parse_iso(r.get("seen") or r["since"]) >= cut]
    keys = [r["key"] for r in rows]
    ahead = rows[:keys.index(key)] if key in keys else rows
    if not ahead:
        return ""
    fit = [r for r in ahead if float(r.get("need") or 0) <= free and (ram_free is None or float(r.get("ram") or 0) <= ram_free)]
    if fit:
        return f"대기열 앞 줄 먼저({fit[0]['project']} {fit[0]['title'][:30]})"
    head = ahead[0]
    waited = (now() - parse_iso(head["since"])).total_seconds() / 60
    if waited >= GPU_JUMP_MIN:
        return f"GPU 대기열 맨 앞이 {int(waited)}분 기다려 앞지르지 않는다({head['project']})"
    return ""


def _ram_ahead(key: str, ram_free: float) -> str:
    """GPU를 쓰지 않는 줄이 기다릴 사유. 앞에 RAM이 모자라 기다리는 줄 가운데 지금 RAM 자리에 드는 줄이 있으면 그 줄이 먼저다.
    GPU를 기다리는 줄은 보지 않는다. GPU를 쓰지 않는 일은 GPU 대기와 무관하게 든다."""
    cut = now() - timedelta(seconds=_STALE_SEC)
    rows = [r for r in _order(ledger_state()["rows"]) if parse_iso(r.get("seen") or r["since"]) >= cut]
    keys = [r["key"] for r in rows]
    ahead = rows[:keys.index(key)] if key in keys else rows
    fit = [r for r in ahead if str(r.get("why") or "").startswith("RAM 부족") and float(r.get("ram") or 0) <= ram_free
           and not float(r.get("need") or 0)]
    return f"대기열 앞 줄 먼저({fit[0]['project']} {fit[0]['title'][:30]})" if fit else ""


def queue_drop(key: str) -> None:
    with _lock:
        st = ledger_state()
        rows = [r for r in st["rows"] if r["key"] != key]
        if len(rows) != len(st["rows"]):
            st["rows"] = rows
            _ledger_save(st)


def queue_rows() -> list[dict]:
    """화면용 대기열. 오래 보지 않은 줄은 빼고 순서대로다."""
    st = ledger_state()
    cut = now() - timedelta(seconds=_STALE_SEC)
    return [r for r in _order(st["rows"]) if parse_iso(r.get("seen") or r["since"]) >= cut]


def queue_move(key: str, where: str) -> bool:
    """사람 순위. where가 top이면 맨 앞, down이면 한 칸 뒤다. 없는 줄이면 거짓이다."""
    with _lock:
        st = ledger_state()
        rows = _order(st["rows"])
        keys = [r["key"] for r in rows]
        if key not in keys:
            return False
        i = keys.index(key)
        if where == "top":
            rows[i]["order"] = float(rows[0].get("order") or 0) - 1
        elif where == "down" and i + 1 < len(rows):
            nxt = float(rows[i + 1].get("order") or 0)
            after = float(rows[i + 2].get("order") or nxt + 2) if i + 2 < len(rows) else nxt + 2
            rows[i]["order"] = (nxt + after) / 2
        rows[i]["moved"] = now_iso()
        _ledger_save(st)
        return True


def _signal_live(r: dict) -> bool:
    """큰 GPU 일 신호의 관찰 시간 안이거나 자리를 기다리는 줄이다. 그동안 새 GPU 작업을 들이지 않는다."""
    s = r.get("signal")
    return bool(s) and not s.get("observed") and (s.get("waiting") or parse_iso(s["until"]) > now())


def reconcile() -> list[dict]:
    """30초마다 실측과 장부를 맞춘다. 장부 줄 프로세스의 실측이 몫보다 0.5GB 넘게 크면 몫을 실측으로 올리고 새 GPU 작업을 10분 멈춘다.
    강제로 끄지 않는다. 작업자 줄의 실측 최댓값은 프로젝트별로 남겨 다음 GPU 요구량으로 쓴다.

    실측 기반 예약(261029-jipsa-07): 시작 뒤 관찰 시간이 지난 줄은 몫을 관찰 실측 최댓값 + 1GB로 고치고(base_gb), 큰 GPU 일 신호의 관찰 시간이
    지난 줄은 신호 뒤 실측 최댓값 + 1GB로 고친다. 고친 줄을 돌려준다. kind는 over(올림), observe(시작 관찰), signal(신호 관찰)이다."""
    gpu = gpu_status()
    if not gpu["ok"]:
        return []
    view = ledger_view(gpu)
    raised, fixed = [], []
    with _lock:
        rows = _load()
        st = ledger_state()
        changed = rows_changed = False
        at = now()
        for r in rows:
            m = next((x["measured"] for x in view["rows"] if x.get("run") == r.get("run")), None)
            if m is None:
                continue
            if r.get("pid_kind") == "worker" and m >= 1.0 and m > float(st["peak"].get(r["project"]) or 0):
                st["peak"][r["project"]] = round(m, 1)
                changed = True
            if r.get("watch"):
                continue
            sig = r.get("signal")
            live = bool(sig) and not sig.get("observed")
            if m > float(r.get("seen_gb") or 0):
                r["seen_gb"] = round(m, 2)
                rows_changed = True
            if live and not sig.get("waiting") and m > float(sig.get("peak") or 0):
                sig["peak"] = round(m, 2)
                rows_changed = True
            if m > float(r.get("amount_gb") or 0) + 0.5:
                # 신호 관찰 중이면 이미 새 GPU 작업을 들이지 않으므로 10분 멈춤을 걸지 않고 몫만 올린다
                (fixed if live else raised).append({"kind": "signal" if live else "over", "run": r.get("run"), "project": r.get("project"),
                                                    "was": r.get("amount_gb"), "now": round(m, 1)})
                r["amount_gb"] = round(m, 1)
                r["raised"] = now_iso()
                if not sig and r.get("base_gb") is not None:
                    r["base_gb"] = r["amount_gb"]  # 신호 없이 커졌으면 이 작업의 평소 몫이 커진 것이다
                rows_changed = True
            if r.get("base_gb") is None and at >= parse_iso(r["start"]) + timedelta(minutes=GPU_OBSERVE_MIN):
                base = round(float(r.get("seen_gb") or 0) + GPU_PAD_GB, 1)
                was = float(r.get("amount_gb") or 0)
                r["base_gb"] = min(base, was)
                r["observed"] = now_iso()
                if not live and base < was:
                    r["claim_gb"], r["amount_gb"] = was, base
                    fixed.append({"kind": "observe", "run": r.get("run"), "project": r.get("project"), "was": was, "now": base})
                rows_changed = True
            if live and not sig.get("waiting") and at >= parse_iso(sig["until"]):
                new = round(float(sig.get("peak") or 0) + GPU_PAD_GB, 1)
                fixed.append({"kind": "signal", "run": r.get("run"), "project": r.get("project"), "was": r.get("amount_gb"), "now": new})
                r["amount_gb"] = new
                sig["observed"], sig["observed_gb"] = now_iso(), new
                rows_changed = True
        if rows_changed:
            _save(rows)
        if raised:
            st["over"] = {"run": raised[0]["run"], "project": raised[0]["project"], "at": now_iso(), "gb": raised[0]["now"],
                          "until": (now() + timedelta(minutes=GPU_OVER_HOLD_MIN)).isoformat(timespec="seconds")}
            changed = True
        live = [x for x in st["reserve"] if parse_iso(x["until"]) > now()]
        if len(live) != len(st["reserve"]):
            st["reserve"] = live  # 10분이 지난 예약은 돌려준다
            changed = True
        if changed:
            _ledger_save(st)
    return raised + fixed


_bound = threading.local()  # 작업자 스레드가 맡은 실행ID. 어댑터가 작업자를 띄우면 그 프로세스 번호를 장부에 적는다


def bind(run_id: str) -> None:
    _bound.run = run_id


def spawned(pid: int) -> None:
    """어댑터가 작업자 프로세스를 띄운 직후 부른다. 이 스레드가 맡은 실행의 장부 줄 번호를 작업자 번호로 바꾼다."""
    run_id = getattr(_bound, "run", "")
    if not run_id:
        return
    with _lock:
        rows = _load()
        hit = False
        for r in rows:
            if r.get("run") == run_id:
                r["pid"], r["pid_kind"] = pid, "worker"
                hit = True
        if hit:
            _save(rows)


def acquire(project: Project, run_id: str, pid: int | None, minutes: int, *, owner: str = "", pid_kind: str = "scheduler",
            check: bool = True) -> bool:
    """장부에 줄을 적는다. GPU가 필요 없는 작업자는 몫 0의 감시 줄(watch)로 적어 실측 최댓값을 잰다(pid가 없으면 적지 않는다).
    owner는 Cycle 목표 key다. 그 목표의 단계 사이 예약은 이 줄이 들면 지운다."""
    needs = project.needs_gpu
    if not needs and not pid:
        return True
    if needs and check:
        ok, _ = can_acquire(project, owner=owner)
        if not ok:
            return False
    with _lock:
        rows = [r for r in _load() if r.get("run") != run_id]
        rows.append({
            "run": run_id, "project": project.name, "resource": "gpu",
            "amount_gb": round(need_gb(project), 1) if needs else 0.0, "exclusive": project.gpu_exclusive,
            "ollama_models": project.ollama_models, "pid": pid, "pid_kind": pid_kind, "owner": owner, "watch": not needs,
            "ram_gb": 0.0 if pid_kind == "session" else round(ram_need_gb(project), 1),  # RAM 몫. 관찰 뒤 reconcile_ram이 실측 + 여유로 고친다
            "start": now_iso(), "expires": (now() + timedelta(minutes=minutes + 10)).isoformat(timespec="seconds"),
        })
        _save(rows)
    if owner:
        st = ledger_state()
        keep = [x for x in st["reserve"] if x.get("owner") != owner]
        if len(keep) != len(st["reserve"]):
            st["reserve"] = keep
            _ledger_save(st)
    return True


def signal(run_id: str, kind: str, gb: float | None = None, *, wait: bool = False, project: Project | None = None, pid: int | None = None,
           minutes: int = 90) -> dict | None:
    """큰 GPU 일 시작 신호(261029-jipsa-07). 그 줄의 몫을 신고량(gb), 없으면 등록부 값, 지난 최댓값, 시작 요구량 가운데 큰 값으로 되올리고
    5분 동안 새 GPU 작업을 들이지 않는다. 그동안의 실측 최댓값 + 1GB로 reconcile이 다시 고친다. wait이면 남은 메모리가 0 아래일 때 관찰을 시작하지 않고
    자리를 기다리는 줄(waiting)로 둔다. 기다리는 동안에도 새 GPU 작업을 들이지 않는다. 장부 줄이 없으면 project를 받아 세션 줄로 만든다(GPU 요구량 0이라
    begin이 적지 않은 세션 실행). 줄도 project도 없으면 None이다. {"amount","free","until","waiting","was"}"""
    with _lock:
        rows = _load()
        r = next((x for x in rows if x.get("run") == run_id), None)
        if r is None and project is not None:
            r = {"run": run_id, "project": project.name, "resource": "gpu", "amount_gb": 0.0, "exclusive": project.gpu_exclusive,
                 "ollama_models": project.ollama_models, "pid": pid, "pid_kind": "session", "owner": "", "watch": False, "start": now_iso(),
                 "expires": (now() + timedelta(minutes=minutes + 10)).isoformat(timespec="seconds")}
            rows.append(r)
        if r is None:
            return None
        reg = 0.0
        try:
            reg = float(load_all()[r["project"]].gpu_vram_gb or 0)
        except Exception:  # noqa: BLE001 - 등록부를 못 읽어도 지난 최댓값으로 간다
            pass
        peak = float(ledger_state()["peak"].get(r["project"]) or 0)
        was = float(r.get("amount_gb") or 0)
        target = float(gb) if gb else max(reg, peak, float(r.get("claim_gb") or 0))
        amount = round(max(target, was), 1)
        was_watch = bool(r.get("watch"))
        r["watch"] = False  # GPU가 필요 없던 작업자도 신호를 보내면 몫을 잡는다
        r["amount_gb"] = amount
        r["signal"] = {"kind": kind, "at": now_iso(), "until": (now() + timedelta(minutes=GPU_SIGNAL_MIN)).isoformat(timespec="seconds"),
                       "peak": 0.0, "from_gb": was, "gb": amount, "from_watch": was_watch}
        _save(rows)
    free = ledger_view()["free"]
    if wait and free < 0:
        with _lock:
            rows = _load()
            for x in rows:
                if x.get("run") == run_id and x.get("signal"):
                    x["signal"]["waiting"] = True
            _save(rows)
    return {"amount": amount, "free": free, "until": r["signal"]["until"], "waiting": wait and free < 0, "was": was}


def signal_ready(run_id: str, force: bool = False) -> dict | None:
    """기다리는 신호가 들 수 있는지 본다. 남은 메모리가 0 이상이거나 force면 관찰 시간을 지금부터 시작한다. {"ready","free","until"}"""
    free = ledger_view()["free"]
    with _lock:
        rows = _load()
        r = next((x for x in rows if x.get("run") == run_id and x.get("signal")), None)
        if r is None:
            return None
        s = r["signal"]
        if not s.get("waiting"):
            return {"ready": True, "free": free, "until": s["until"]}
        if free < 0 and not force:
            return {"ready": False, "free": free, "until": ""}
        s.pop("waiting", None)
        s["at"] = now_iso()
        s["until"] = (now() + timedelta(minutes=GPU_SIGNAL_MIN)).isoformat(timespec="seconds")
        _save(rows)
        return {"ready": True, "free": free, "until": s["until"]}


def signal_done(run_id: str) -> dict | None:
    """큰 GPU 일 끝 신호. 몫을 시작 관찰 값(base_gb)으로 돌리고, 관찰 전이면 시작 요구량으로 돌린다. 신호 기록은 signals에 남긴다. 줄이 없으면 None이다."""
    with _lock:
        rows = _load()
        r = next((x for x in rows if x.get("run") == run_id), None)
        if r is None:
            return None
        was = float(r.get("amount_gb") or 0)
        s = r.pop("signal", None) or {}
        back = r["base_gb"] if r.get("base_gb") is not None else float(r.get("claim_gb") or s.get("from_gb") or was)
        r["amount_gb"] = round(back, 1)
        if s.get("from_watch"):
            r["watch"], r["amount_gb"] = True, 0.0  # 감시 줄로 돌린다
        r.setdefault("signals", []).append({"kind": s.get("kind", ""), "at": s.get("at", ""), "observed_gb": s.get("observed_gb"),
                                            "peak": s.get("peak"), "done": now_iso()})
        _save(rows)
    return {"was": was, "amount": float(r["amount_gb"])}


def release(run_id: str) -> list[str]:
    """장부 줄을 반납한다. Cycle 단계였으면 그 몫을 10분 예약으로 남긴다. 프로젝트가 Ollama를 쓰면 남은 모델을 내린다(5절 Ollama 회수).
    내린 모델을 돌려준다."""
    unloaded: list[str] = []
    with _lock:
        rows = _load()
        mine = [r for r in rows if r.get("run") == run_id]
        rest = [r for r in rows if r.get("run") != run_id]
        _save(rest)
    keep = [r for r in mine if r.get("owner") and not r.get("watch") and float(r.get("amount_gb") or 0) > 0]
    if keep:
        st = ledger_state()
        for r in keep:
            # 관찰을 마친 줄은 큰 GPU 일 신호로 올린 몫이 아니라 관찰 값으로 남긴다(261029-jipsa-07). 다음 단계의 큰 일은 그 단계가 다시 신호를 보낸다
            gb = r["base_gb"] if r.get("base_gb") is not None else r["amount_gb"]
            st["reserve"] = [x for x in st["reserve"] if x.get("owner") != r["owner"]]
            st["reserve"].append({"owner": r["owner"], "project": r["project"], "gb": gb, "run": run_id,
                                  "until": (now() + timedelta(minutes=GPU_RESERVE_MIN)).isoformat(timespec="seconds")})
        _ledger_save(st)
    for r in mine:
        if r.get("ollama_models"):
            loaded = ollama_loaded() or []
            for m in loaded:
                if ollama_unload(m):
                    unloaded.append(m)
    return unloaded


def summary() -> dict:
    gpu = gpu_status()
    ollama = ollama_loaded(remember=True)  # GPU 주인 묶기와 같이 쓴다. 전에는 두 번 연결했다
    return {
        "gpu_total_gb": gpu["total_gb"], "gpu_used_gb": gpu["used_gb"], "gpu_procs": len(gpu["procs"]), "gpu_ok": gpu["ok"],
        "gpu_owners": gpu_owners(gpu["procs"], ollama or []) if gpu["ok"] else [],
        "ram_free_gb": ram_free_gb(), "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 1), "ollama": ollama, "leases": held(),
        "ledger": ledger_summary(gpu),
    }


def ledger_summary(gpu: dict | None = None) -> dict:
    """화면의 GPU 막대와 대기열. 장부 줄(몫, 실측), 장부 밖, 예약, 남은 자리, 대기열(순번, 필요량, 선 시각, 사유), 실측 초과."""
    try:
        view = ledger_view(gpu)
    except Exception:  # noqa: BLE001 - 장부 오류로 화면이 멈추면 안 된다
        return {}
    st = ledger_state()
    over = st.get("over") if st.get("over") and parse_iso(st["over"]["until"]) > now() else None
    rows = [{"run": r.get("run"), "project": r.get("project"), "gb": r.get("amount_gb"), "measured": r.get("measured"), "pid": r.get("pid"), "owner": r.get("owner") or "",
             "kind": "세션" if r.get("pid_kind") == "session" else "작업자", "start": r.get("start"),
             "basis": "신호" if _signal_live(r) else "실측" if r.get("base_gb") is not None else "요구량",
             "signal": (r.get("signal") or {}).get("kind", "")}
            for r in view["rows"] if not r.get("watch")]
    reserve = [x for x in st["reserve"] if parse_iso(x["until"]) > now()]
    try:
        ram = ram_view()
    except Exception:  # noqa: BLE001 - RAM을 못 읽어도 GPU 막대는 그린다
        ram = {}
    return {"total": view["total"], "used": view["used"], "leased": view["leased"], "outside": view["outside"], "reserve": view["reserve"],
            "free": view["free"], "ok": view["ok"], "rows": rows, "reserves": reserve, "queue": queue_rows(), "over": over, "ram": ram}
