"""목표 cycle. 261022-jipsa-15 추천안 B에서 시작해 261023-jipsa-21 1안(Cycle 세 단계 정의)으로 다시 정했다.

목표는 할 일 파일의 시킨 cycle 칸 줄이고 scheduler/auto.py가 한 차례씩 이 모듈의 advance를 부른다(261025-jipsa-24, Auto 절은 261029-jipsa-17에서 뗐다).
수치 지표와 목표값이 없는 cycle은 거절해 돌리지 않는다(workitem.Cycle.reject). 옛 주간 파일 `## cycle` 절, Auto 범위 계약(scope),
Main 지휘(conductor), jipsa goal과 jipsa cycle 명령은 261025-jipsa-42에서 뗐다. 아래 설명의 cycle 절과 Main 주체 이야기는 옛 기록을 읽는 데만 남는다.

Cycle 하나는 세 단계이고 순서는 고정이다.
- 명령 이행: 서브에이전트나 작업자가 이번 Cycle의 명령을 수행하고 지표를 잰다. result.json의 cycle 칸에 지표를 쓴다(prompts.cycle_run).
- 분석과 피드백: 새 서브에이전트나 작업자가 이행 결과를 읽고 지표를 다시 확인한 뒤 피드백(잘된 것, 모자란 것, 다음 명령 1순위와 차순위)을
  result.json의 cycle 칸에 쓴다(prompts.cycle_analysis).
- 목표 판정: jipsa가 확인된 지표를 목표값과 방향에 대어 O와 X를 정한다. 실행 기록을 만들지 않고 cycle 기록의 judge 칸으로만 남는다.
  O이면 끝이다. 다만 Auto 목록 목표는 줄에 "도달하면 끝"을 적지 않았으면 O여도 끝내지 않고 처음 닿은 Cycle을 기록의 reached 칸에
  남긴 뒤 X와 같이 다음 명령을 골라 마감까지 돈다(261026-jipsa-03). X이면 멈춤 조건을 보고, 걸린 것이 없으면 피드백 1순위를 다음 Cycle의 명령으로 삼는다.
  1순위가 금지 사항(푸시, torch 변경, 외부 쓰기)에 걸리면 차순위를 쓰고, 차순위도 걸리면 끝낸다.
목표 미정 Cycle(261026-jipsa-11): 할 일 줄 cycle 칸의 지표나 목표값이 비었으면 첫 Cycle 이행은 지표 후보를 찾는 명령(PENDING_PLAN)이고
  지표 칸이 비어도 된다. 그 Cycle의 분석이 결과지 goal 칸에 지표, 목표값, 방향, 근거를 쓰면 jipsa가 빈 칸만 할 일 줄에 채우고(todo.fill_cycle)
  그 값으로 판정을 잇는다(set_goal). 상한은 분석이 정하지 않는다. 사람이 비운 상한은 비운 채 두고 마감까지 돈다(261029-jipsa-03 1안). 분석이 확인 필요로 멈추거나 두 번 다 goal 칸을 채우지 못하면 확인 필요로 끝낸다.
  이행 앞에 따로 정하는 단계를 두지 않은 까닭은 Cycle 순서(이행, 분석, 판정)가 고정이고, 분석이 이행 산출물에서 지표를 다시 재는 독립 판정 단계라
  정한 지표로 첫 값을 바로 잴 수 있어서다.
판정 앞에는 칸 점검만 한다. 이행의 지표 칸이나 분석의 지표 칸과 피드백 칸이 비었거나 단계가 실패하면 그 단계를 한 번 다시 시킨다.
이행이 다시 비거나 실패하면 그 Cycle을 실패(나아지지 않음)로 판정하고 같은 명령으로 다음 Cycle을 연다(261026-jipsa-03, 옛 동작은 이행 2번 연속 실패로 끝). 분석이 다시 비거나 실패하면 그 Cycle을 실패(나아지지 않음)로 세고 같은 명령으로 다음 Cycle을 연다.
끝 조건은 판정 O(목표 도달, Auto 목록 줄은 "도달하면 끝"을 적었을 때만), 상한만큼 연속 나아지지 않음(Auto 목록 줄은 적었을 때만),
다음 명령이 금지 사항, 그리고 Auto 마감이다(Auto 목록 줄은 마감으로 끝나지 않는다). 연속 나아지지 않음은 방향 전환 바퀴도 센다. 두 순위가 모두 버린 가설이면 기본 명령으로 잇는다(261026-jipsa-03).
Auto 마감은 Auto 모드의 마감 하나(modes.cutoff_for, 모드 종료 시각과 범위 절 시각을 합친 값)이고,
cycle 줄에 따로 적은 시각이 더 이르면 그 목표만 일찍 마감한다. 유인 모드에서는 cycle 줄 시각만 본다(261023-jipsa-39).
Cycle 수와 cycle 전체 시간에는 상한이 없다(261023-jipsa-21 사용자 답 "상한은 정하지 않는다"). 단계 하나의 상한은 공통 규칙대로 둔다.
마감 여유(261027-jipsa-03): 마감까지 남은 시간이 새로 열 단계(이행은 명령 예상 시간, 분석은 ANALYSIS_MIN)의 상한보다 짧으면 열지 않고
  paused 칸에 이유를 남긴다(deadline_room). 목표는 끝내지 않으며 시키기가 마감 결과지를 쓰고 닫는다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계).
탐색(261027-jipsa-03): 분석 지시문에 지난 Cycle 전체, 사람 답과 피드백, 지난 분석의 후보 가운데 시도한 것과 안 한 것, 같은 프로젝트의
  다른 Cycle 목표, 로컬 수집 자료 위치, 웹 검색 지시를 넣는다(explore_material). 분석이 쓴 explore 칸은 Cycle의 explore로 옮긴다.
아이디어 갈래(261029-jipsa-10 1안): Cycle 1 이행이 사람 지시에 맞춘 갈래 3~6개(이름, 가설, 첫 명령, 끝낼 조건)를 만들고 Cycle 1 분석이 고친다.
  분석은 다음 명령마다 갈래를 붙이고 이번 명령의 갈래를 다시 본다. 같은 갈래가 연속 2번 나아지지 않으면 닫고 그 갈래 명령은 버린 가설처럼 건너뛴다.
  전환 바퀴는 지난 미개선 바퀴와 다른 열린 갈래로 가고(안 간 갈래, 덜 간 갈래 순) 범위 칸 밖 갈래는 사람 확인으로 넘긴다.
  열린 갈래가 없으면 분석이 새 갈래 하나를 더하고, 더하지 않으면 확인 필요로 끝낸다. 갈래 기록이 없는 옛 목표는 그대로 돈다.
방향 전환(261029-jipsa-03 1안): 연속 나아지지 않음이 PIVOT_AFTER(2)의 배수에 닿으면 상한과 별개로 다음 Cycle을 방향 전환 바퀴로 연다(pivot_due).
  새 Cycle은 늘 최고 기록 브랜치에서 시작한다. 전환이 다가온 분석(이번에도 나아지지 않으면 전환인 Cycle)과 전환 바퀴의 분석 지시문에 전환 절과
  지난 미개선 Cycle의 명령 요지를 넣고, 앞의 분석은 전환 명령을 next의 rank 3(pivot)으로 더 쓴다. 전환이면 판정이 그 명령을 먼저 고른다.
  상한이 있고 그 바퀴에서 상한에 닿으면 끝이 먼저다(상한 2 이하는 전환 없이 끝난다). 최고 기록과 같은 값은 지금처럼 나아지지 않음이다.
나아짐은 jipsa가 정한다. 지표가 지금 최고 기록보다 목표 방향으로 나아졌으면 나아짐이고, 첫 측정은 기준선 차의 방향으로 본다.
사용 창 비율은 cycle을 멈추지 않는다(261102-jipsa-50). 실제 한도 오류는 실행기가 대기하거나 실패로 끝낸다.
범위 계약은 cycle이 모두 끝나거나 거절되어야 소진이다.

피드백 장치 셋(261023-jipsa-32, 31번 1안 가운데 사용자가 고른 1, 2, 5번).
- 독립 판정: 분석 지시문은 이행의 대화, 보고서, 완료 주장을 넘기지 않고 산출물 위치, 측정 방법, 목표, 시도 기록만 넘긴다.
  판정은 분석이 다시 잰 값으로 하고, cycle 절에 측정 명령이 있으면 jipsa가 이행 작업 폴더에서 직접 잰 값으로 한다.
  이행이 적은 값과 다르면 judge 칸에 둘 다 남긴다.
- 시도 기록: 기록의 attempts 칸에 Cycle마다 명령, 결과 판정(긍정, 중립, 부정), 실패 범주, 버린 가설과 이유를 쌓는다(최근 20줄).
  다음 명령이 버린 가설(같은 명령 문자열이나 같은 가설 key)과 같으면 차순위로 바꾼다. 둘 다 같으면 끝낸다.
- 실패 원인 분류: 이행 실패와 정체를 환경과 운영, 명령 오해, 측정 오류, 아이디어 무효, 외부 의존 가운데 하나로 적는다.
  환경과 운영, 측정 오류는 5 Cycle 연속 나아지지 않음과 이행 2번 연속 실패에서 빼고 따로 센다.
  이 두 범주의 이행 실패는 같은 Cycle 안에서 3번까지 다시 시키고, 4번째면 확인 필요로 cycle을 끝낸다.

cycle 기록은 상태 폴더 cycles/<프로젝트>-<이름>.json이다. 기록 안의 rounds 칸이 Cycle 목록이고(옛 이름을 그대로 둔다), Cycle마다 번호, 명령,
두 단계의 실행ID, 지표, 차, 피드백, 판정, 다음 명령, 걸린 시간을 남긴다.
자동 확인(261023-jipsa-33).
- 자동 확인: Cycle이 다음 단계로 넘어가면 넘어간 단계의 실행(이행, 분석, 다시 시킨 앞 시도)을 확인 기록에 자동 확인으로 남긴다.
  상태 값은 바꾸지 않는다. 상태 값이 확인 필요인 단계, 범위 밖 플랜의 확인 필요, 그리고 금지 사항, 환경 실패 상한,
  두 순위 모두 버린 가설로 끝난 cycle의 마지막 Cycle은 사람이 보도록 남긴다.
- 끝난 목표의 결과지는 scheduler/auto.py가 한 장 쓴다. 옛 종합 보고 단계(Cycle 종합 보고, Auto 종합 보고)와 지시 목표의 목표 정하기 단계(목표 카드,
  다시 정하기, 승인)는 261026-jipsa-07에서 만들기를 뗐다. 지난 기록의 final, setup, card 칸은 화면과 보고가 읽기만 한다.
주체(261023-jipsa-10): 한 cycle은 한 주체만 연다. 기록의 owner가 main이면 Main 세션이 서브에이전트로 두 단계를 돌리고,
없거나 worker면 스케줄러 작업자가 돌린다. 스케줄러의 step은 Main이 맡은 cycle을 건너뛴다.
261025-jipsa-42부터 새 기록은 늘 작업자 주체다.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from scheduler import claude_window, codex_window, modes, prompts, queue, record, report, workitem
from scheduler.config import STATE, now, now_iso, parse_hhmm, parse_iso
from scheduler.nowindow import hidden
from scheduler.registry import Project

CYCLE_DIR = STATE / "cycles"
TIER = "cycle"
RUN, ANALYSIS, JUDGE = "명령 이행", "분석과 피드백", "목표 판정"
SETUP = "목표 정하기"  # 지시 목표의 첫 단계(261023-jipsa-40). Cycle 번호 없이 판 번호로 센다
UNMEASURED = "측정 불가"
FINAL = "종합 보고"  # cycle이 끝난 뒤 한 번 여는 보고 단계(261023-jipsa-33)
AUTO_WHY = "자동 확인: cycle 진행"
_OLD_STEPS = {"수행": RUN, "분석": ANALYSIS}  # 261023-jipsa-25 전 기록의 단계 이름
LIVE, ENDED, WAITING = "진행 중", "끝", "대기"
REJECTED = "거절"  # 수치 지표나 목표값이 없어 받지 않은 cycle. 기록을 만들지 않고 화면과 status에 이유를 보인다
FIRST, PRIMARY, SECONDARY, SAME = "첫 명령", "1순위", "차순위", "같은 명령"
MAIN, WORKER = "main", "worker"  # cycle을 여는 주체. 기록에 owner가 없으면 작업자다
FIRST_PLAN = "지표를 고정 조건으로 재는 방법과 지금 값을 먼저 확인하고, 목표 방향으로 가장 효과가 클 것 하나를 고친다"
# 목표 미정 Cycle의 첫 명령(261026-jipsa-11). 지표와 목표값은 이어지는 Cycle 1 분석이 정한다
PENDING_PLAN = ("목표가 아직 미정이다. 할 일 문장이 바라는 결과를 재는 수치 지표나 기계 O/X 체크 후보와 재는 방법을 찾아 지금 값을 재고, "
                "할 일 방향으로 가장 효과가 클 것 하나를 고친 뒤 같은 방법으로 다시 잰다")
GOAL_HOLD = "확인 필요(Cycle 목표 미정"  # 분석이 목표를 정하지 못해 끝낸 사유의 머리. HOLD_END로 시작해 사람이 본다
# 분석이 쓴 두 순위가 모두 버린 가설이거나 비었을 때 다음 Cycle의 명령. 끝내지 않고 이 명령으로 잇는다(261026-jipsa-03)
FALLBACK_PLAN = "시도 기록에서 버린 가설과 다른 새 가설 하나를 골라 목표 지표 방향으로 고치고 같은 조건으로 다시 잰다"
FALLBACK = "기본 명령"
PIVOT, PIVOT_AFTER, PIVOT_TEXT = "전환 명령", 2, "방향 전환"  # 연속 나아지지 않음이 PIVOT_AFTER의 배수면 다음 Cycle은 방향 전환 바퀴다(261029-jipsa-03 1안)
PIVOT_BASE = "전환 기본 명령"  # 전환인데 분석이 쓸 만한 전환 명령을 내지 않았을 때 jipsa가 쓰는 전환 명령의 출처
# 아이디어 갈래(261029-jipsa-10 1안). 첫 이행이 갈래 3~6개를 만들고 첫 분석이 고친다. 같은 갈래가 연속 2번 나아지지 않으면 닫는다
BRANCH_MIN, BRANCH_MAX, BRANCH_CLOSE = 3, 6, 2
OPEN, CLOSED, ASK = "열림", "닫힘", "사람 확인"  # 사람 확인은 범위 칸 밖(설치, 모델 내려받기) 갈래라 jipsa가 고르지 않는다
BRANCH = "갈래 명령"  # 분석의 명령이 다 걸려 jipsa가 열린 갈래에서 만든 명령의 출처
FIRST_BRANCH = " 이 Cycle에서 목표에 맞춘 아이디어 갈래 목록도 만든다"
_TORCH = re.compile(r"^(torch|torchvision|torchaudio)\b|cuda", re.I)
_PUSH = re.compile(r"git\s+push|푸시|\bpush\b|발행|배포", re.I)
_FATAL = re.compile(r"torch|외부 쓰기|푸시")  # 이행이 이 규칙의 확인 필요로 끝나면 그 cycle을 끝낸다
STOP_END = "사람 멈춤"  # 사람이 jipsa cycle stop이나 대시보드 멈춤 단추로 끝낸 목표의 끝 사유(261024-jipsa-16 1안)
_FEEDBACK = (("good", "잘된 것"), ("lack", "모자란 것"))
ENV, MISREAD, MEASURE_ERR, IDEA, EXTERNAL = "환경과 운영", "명령 오해", "측정 오류", "아이디어 무효", "외부 의존"
FAIL_CLASSES = (ENV, MISREAD, MEASURE_ERR, IDEA, EXTERNAL)
UNCOUNTED = (ENV, MEASURE_ERR)  # 연속 횟수에서 빼고 따로 센다
ENV_RETRY = 3  # UNCOUNTED 범주의 이행 실패를 같은 Cycle 안에서 다시 시키는 횟수. 넘으면 확인 필요다
VERDICTS = ("긍정", "중립", "부정")
ATTEMPT_KEEP = 20  # 시도 기록 줄 상한
MEASURE_TIMEOUT = 600  # jipsa 직접 측정의 초 상한
_ENV_HINT = re.compile(r"시간 초과|타임아웃|timeout|한도|rate.?limit|\b429\b|GPU|out of memory|OOM|메모리 부족|연결|네트워크|끊김|멈춤|stall|디스크", re.I)
HOLD_END = "확인 필요"  # 끝 사유가 이것으로 시작하면 주간 파일 줄에 확인 필요를 붙인다
# 이 사유로 끝난 cycle은 마지막 Cycle의 단계를 자동 확인하지 않는다. 금지 사항, 환경 실패 상한, 두 순위 모두 버린 가설이다
HELD_ENDS = (HOLD_END, "이행 확인 필요", "다음 명령이 금지 사항", "다음 명령 1순위와 차순위가 모두 버린 가설")


# ----- 기록 -----
def record_path(c: workitem.Cycle) -> Path:
    slug = re.sub(r"-+", "-", re.sub(r"[^\w가-힣-]+", "-", c.title)).strip("-")[:40] or "cycle"
    if getattr(c, "origin", "") == "todo":
        return CYCLE_DIR / f"todo-{c.project}-{slug}.json"  # Auto 목록 Cycle 목표. 옛 cycle 절 기록과 섞이지 않게 머리를 붙인다
    return CYCLE_DIR / f"{c.project}-{slug}.json"


# ----- 사람 피드백(261026-jipsa-19) -----
FEEDBACK_FILE = STATE / "cycle_feedback.jsonl"  # 줄 덧붙이기만 한다. 명령은 스케줄러가 꺼져 있어도 여기에만 쓰고, cycle 기록은 스케줄러만 쓴다
_fb_lock = threading.Lock()


def feedback_add(key: str, text: str) -> dict:
    """Cycle 목표(프로젝트::할 일 문장)에 사람 피드백 한 건을 덧붙인다. 읽는 쪽이 정해진 단계에서 가져가고 이 파일은 고쳐 쓰지 않는다."""
    at = now_iso()
    e = {"id": hashlib.sha1(f"{key}|{at}|{text}".encode("utf-8")).hexdigest()[:8], "key": key, "text": text, "at": at}
    with _fb_lock:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def feedback_clear(key: str) -> None:
    """끝난 목표의 기록을 옮길 때 그 앞의 피드백은 읽힌 것으로 닫는다. 같은 줄을 다시 올려도 옛 피드백이 되살아나지 않는다."""
    with _fb_lock:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "clear": now_iso()}, ensure_ascii=False) + "\n")


def feedback_entries(key: str) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue  # 쓰는 도중의 끝 줄은 다음에 읽는다
        if e.get("key") != key:
            continue
        if e.get("clear"):
            rows = []
        elif e.get("id") and e.get("text"):
            rows.append(e)
    return rows


def feedback_for(c: workitem.Cycle, rec: dict, step: str, n: int) -> list[str]:
    """이 Cycle의 이 단계(명령 이행, 분석과 피드백)가 읽을 사람 피드백 원문. 단계 종류마다 한 번만 읽히고(다른 Cycle 번호에서 읽혔으면 뺀다),
    같은 Cycle의 다시 시키기는 같은 글을 다시 받는다. 읽힌 사실은 cycle 기록의 feedback 칸에 Cycle 번호와 단계로 남긴다(저장은 부르는 쪽)."""
    log = rec.setdefault("feedback", [])
    out = []
    for e in feedback_entries(c.key):
        row = next((x for x in log if x["id"] == e["id"]), None)
        if row is None:
            row = {"id": e["id"], "text": e["text"], "at": e["at"], "read": []}
            log.append(row)
        if any(r["step"] == step and r["n"] != n for r in row["read"]):
            continue
        if not any(r["step"] == step and r["n"] == n for r in row["read"]):
            row["read"].append({"n": n, "step": step})
        out.append(e["text"])
    return out


LIVE_HEAD = "## 사람 피드백(실행 중 전달)"  # 돌던 단계의 plan.md에 덧붙이는 절 머리. 피드백 id를 줄에 적어 두 번 넣지 않는다


def feedback_late(q: dict) -> list[dict]:
    """이 단계 큐 줄이 열린 뒤 들어와 지시문에 없는 피드백. 단계 지시문은 열 때 정해지므로 돌던 단계는 이것을 따로 받아야 한다(261027-jipsa-02)."""
    if not q.get("cycle"):
        return []
    since, crit = str(q.get("added") or ""), str(q.get("criteria") or "")
    return [e for e in feedback_entries(q["cycle"]) if str(e.get("at") or "") >= since and e["text"] not in crit]


def live_note(entries: list[dict]) -> str:
    """돌던 단계에 넘기는 피드백 문장. 명령과 판정 조건은 그대로 두고 보고서에서 다루게 한다."""
    return ("사람 피드백(이 단계가 열린 뒤 들어온 원문이다): " + " ".join(f"[{e['id']}] {e['text']}" for e in entries) + " 끝. "
            "돌고 있는 학습이나 측정은 끊지 않고 이번 명령과 판정 조건도 바꾸지 않는다. 남은 단계에서 반영할 수 있는 것은 반영하고, "
            "보고서에 '사람 피드백' 절을 두어 이번 단계에서 한 것과 다음 Cycle에서 할 것을 적는다. 다음 명령은 분석 단계가 이 피드백을 읽고 정한다.")


def live_plan(run_id: str) -> Path | None:
    """돌던 단계 실행의 마지막 시도 plan.md. 작업자는 구간마다 이 파일의 다음 단계를 읽는다(구간 지시문이 이 파일을 가리킨다)."""
    dirs = record.attempt_dirs(run_id) if run_id else []
    return dirs[-1] / "plan.md" if dirs else None


def feedback_push(key: str) -> list[str]:
    """이 Cycle 목표의 돌던 단계(큐 줄이 실행 중)에 늦게 온 피드백을 그 실행의 plan.md 끝에 절로 덧붙인다. 스케줄러가 코드를 다시 읽지 않아도
    다음 구간부터 닿는다. 이미 넣은 id는 건너뛴다. 넣은 실행ID 목록이다. 아직 시작 전인 단계는 실행기가 첫 지시문에 붙인다."""
    out = []
    for q in queue.load():
        if q.get("cycle") != key or q.get("status") != queue.RUNNING or not q.get("run_id"):
            continue
        plan = live_plan(q["run_id"])
        if plan is None:
            continue
        try:
            text = plan.read_text(encoding="utf-8")
        except OSError:
            text = ""
        new = [e for e in feedback_late(q) if f"[{e['id']}]" not in text]
        if not new:
            continue
        with plan.open("a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + f"\n{LIVE_HEAD}\n\n{live_note(new)}\n")
        out.append(q["run_id"])
    return out


PRIOR_DAYS = 7  # 같은 프로젝트의 다른 목표에 적은 피드백을 이어 읽는 기간
PRIOR_KEEP = 6  # 이어 읽는 건수 상한(최근 것부터)


def feedback_prior(c: workitem.Cycle, rec: dict, step: str, n: int) -> list[str]:
    """같은 프로젝트의 다른 Cycle 목표에 사람이 적은 피드백 원문(최근 PRIOR_DAYS일, 최근 PRIOR_KEEP건, 오래된 것이 앞).
    피드백은 할 일 줄 문장으로 묶이므로 새 줄로 목표를 바꿔 올리면 앞 줄에 적은 글이 읽히지 않았다(261027-jipsa-02).
    앞 목표가 끝나며 남긴 지운 표시와 무관하게 원문을 참고로 넘긴다. 읽힌 사실은 cycle 기록의 feedback_prior 칸에 남긴다(저장은 부르는 쪽)."""
    try:
        lines = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    since = (now() - timedelta(days=PRIOR_DAYS)).isoformat(timespec="seconds")
    own = {e["text"] for e in feedback_entries(c.key)}
    rows: list[dict] = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        key = str(e.get("key") or "")
        if (e.get("id") and e.get("text") and key != c.key and key.startswith(f"{c.project}::") and str(e.get("at") or "") >= since
                and e["text"] not in own and all(r["text"] != e["text"] for r in rows)):
            rows.append(e)
    rows = rows[-PRIOR_KEEP:]
    log = rec.setdefault("feedback_prior", [])
    for e in rows:
        row = next((x for x in log if x["id"] == e["id"]), None)
        if row is None:
            row = {"id": e["id"], "key": e["key"], "at": e["at"], "read": []}
            log.append(row)
        if not any(r["step"] == step and r["n"] == n for r in row["read"]):
            row["read"].append({"n": n, "step": step})
    return [e["text"] for e in rows]


def _upgrade(rec: dict) -> dict:
    """옛 기록의 단계 이름(수행, 분석)을 지금 이름으로 바꿔 읽는다. 판정 칸이 없는 옛 Cycle은 다음 플랜 칸으로 판정이 끝난 것으로 본다."""
    for r in rec.get("rounds") or []:
        r["steps"] = {_OLD_STEPS.get(k, k): v for k, v in r.get("steps", {}).items()}
        if "judge" not in r:
            r["judge"] = {"ox": "X", "metric": r.get("score"), "next": ((r.get("next") or {}).get("plan") or {}).get("plan", ""),
                          "next_rank": (r.get("next") or {}).get("chosen", ""), "forbidden": "", "failed": ""} if r.get("next") is not None else None
    return rec


def load(c: workitem.Cycle) -> dict:
    """cycle 기록. 기록이 없으면 작업자 주체로 새 기록을 만든다. Main 지휘는 261025-jipsa-42에서, 목표 카드 덧씌우기는 261026-jipsa-07에서 뗐다."""
    try:
        rec = _upgrade(json.loads(record_path(c).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        rec = {"key": c.key, "project": c.project, "title": c.title, "status": WAITING, "started": None, "finished": None,
               "report_date": None, "base": c.base, "score": c.base, "target": c.target, "baseline_ref": "",
               "rounds": [], "violations": 0, "holds": [], "end_reason": ""}
        if getattr(c, "origin", "") == "todo":
            rec.update(origin="todo", owner=WORKER)  # Auto 목록 Cycle 목표는 스케줄러 작업자만 돌린다(Main 지휘 없음)
    return rec


# ----- 목표 정하기(261023-jipsa-40) -----


def setup_view(rec: dict) -> dict | None:
    """목표 정하기 단계의 상태. 화면, status, 보고가 같은 값을 쓴다. 지시 목표가 아니면 None이다.
    state는 정하는 중, 확인 필요, 다시 정하기 대기, 박음 가운데 하나다."""
    s = rec.get("setup")
    if not s and not rec.get("card"):
        return None
    hold = rec.get("hold") or {}
    drafting = s and s.get("v") != rec.get("version")
    if hold:
        state = "확인 필요"  # 멈춘 이유(카드 확인, 승인 필요 선행)는 hold 칸에 있다
    elif rec.get("resetup") and not drafting:
        state = "다시 정하기 대기"
    elif drafting:
        state = "정하는 중"
    else:
        state = "박음"
    card = rec.get("card") or {}
    return {"state": state, "version": rec.get("version") or 0, "drafting": (s or {}).get("v") if drafting else None,
            "run_id": (s or {}).get("run_id") or "", "hold": hold.get("why") or "", "resetup": (rec.get("resetup") or {}).get("why") or "",
            "approved": bool(hold) and rec.get("approved_v") == hold.get("v"),  # 사람이 승인했고 다음 걸음에 박는다
            "goal": card.get("goal") or "", "checks": len(card.get("checks") or []), "human": len(card.get("human") or []),
            "cycles_est": card.get("cycles_est"), "first_command": card.get("first_command") or "",
            "versions": [{"v": x["v"], "why": x.get("why", ""), "at": x.get("at", ""), "run_id": x.get("run_id", "")} for x in rec.get("cards") or []]}


def _cur_rounds(rec: dict) -> list[dict]:
    """지금 판의 Cycle들. 수치 목표와 옛 기록은 판 번호가 0이라 모두 든다."""
    v = int(rec.get("version") or 0)
    return [r for r in rec["rounds"] if int(r.get("v") or 0) == v]


def save(c: workitem.Cycle, rec: dict) -> None:
    path = record_path(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec["updated"] = now_iso()
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if rec.get("rounds"):
        auto_confirm(rec)  # 기록이 바뀔 때마다 넘어간 단계를 자동 확인한다. 다음 단계를 연 그 걸음에 앞 단계가 초록이 된다


def _row(key: str) -> dict | None:
    rows = [r for r in queue.load() if r["key"] == key]
    return rows[-1] if rows else None


def _row_minutes(row: dict | None, at: datetime) -> int:
    if not row or not row.get("started"):
        return 0
    end = parse_iso(row["finished"]) if row.get("finished") else at
    return max(0, int((end - parse_iso(row["started"])).total_seconds() // 60))


def _meta(run_id: str | None) -> dict:
    return (record.meta_of(run_id) or {}) if run_id else {}


def _sync_step(step: dict, at: datetime) -> dict | None:
    """큐 줄과 실행 기록에서 단계의 상태, 시간, 공급자를 옮겨 적는다."""
    row = _row(step["key"])
    if not row:
        return None
    meta = _meta(row.get("run_id"))
    step.update(status=row["status"], run_id=row.get("run_id") or "", minutes=_row_minutes(row, at) + step.get("minutes_before", 0))
    if meta.get("worker_provider"):
        step["provider"] = meta["worker_provider"]
        step["switched"] = meta.get("worker_switched") or ""
    if meta.get("branch"):
        step["branch"] = meta["branch"]
    return row


def used_minutes(rec: dict) -> int:
    return sum(int(s.get("minutes") or 0) for r in rec["rounds"] for s in r["steps"].values())


def history(rec: dict, keep: int = 6) -> list[str]:
    """작업자 완료 기준에 넣는 지난 Cycle 요약. cycle 기록 파일을 못 읽어도 이것으로 잇는다."""
    out = []
    for r in rec["rounds"][-keep:]:
        j = r.get("judge")
        if not j:
            continue
        what = r["plan"].get("plan", "")
        score = "없음" if j.get("metric") is None else f"{j['metric']:g}"
        atk = attack_notes(r)  # 이행과 분석이 받은 Sol 공격 요약을 다음 이행이 참고한다. 판정 규칙은 그대로다(261024-jipsa-11)
        out.append(f"Cycle {r['n']} {what[:60]} 지표 {score} 판정 {j['ox']} {'나아짐' if r.get('adopt') else '나아지지 않음'}"
                   + (f" ({atk})" if atk else ""))
    return out


def attack_notes(rnd: dict) -> str:
    """Cycle 하나의 이행과 분석이 받은 Sol 공격 요약 한 줄. 공격 기록이 없으면 빈 값이다. 자세한 지적은 각 시도 폴더의 attack.md다."""
    from scheduler import attack

    bits = []
    for k in (RUN, ANALYSIS):
        rid = (rnd["steps"].get(k) or {}).get("run_id") or ""
        note = attack.note_line(rid) if rid else ""
        if note:
            bits.append(f"{k} {note}, runs/{rid}의 attack.md")
    return "; ".join(bits)


def _number(v) -> float | None:
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


# ----- 시도 기록, 실패 범주, 독립 측정(261023-jipsa-32) -----
def attempt_lines(rec: dict) -> list[str]:
    """분석 지시문에 넣는 시도 기록. Cycle마다 명령, 결과 판정, 지표, 실패 범주, 버린 가설과 이유다."""
    out = []
    for a in (rec.get("attempts") or [])[-ATTEMPT_KEEP:]:
        score = "없음" if a.get("metric") is None else f"{a['metric']:g}"
        bits = [f"Cycle {a['n']} 명령 '{a.get('command', '')[:60]}'", f"판정 {a.get('verdict') or '없음'}", f"지표 {score}"]
        if a.get("fail_class"):
            bits.append(f"범주 {a['fail_class']}")
        bits += [f"버린 가설 {d.get('key') or '-'}: {d.get('hypothesis', '')[:50]}(이유 {d.get('why', '')[:50]})" for d in a.get("dropped") or []]
        out.append(", ".join(bits))
    return out


def fail_class(block: dict | None, row: dict | None) -> str:
    """이행 실패의 범주. 이행이 적은 범주가 있으면 그것이고, 없으면 실행 기록의 사유로 환경과 운영을 가린다.
    끝났는데 지표 칸이 빈 것은 명령 오해, 나머지 실패는 아이디어 무효로 본다."""
    v = str((block or {}).get("fail_class") or "").strip()
    if v in FAIL_CLASSES:
        return v
    if row and row.get("status") == queue.SKIPPED:
        return ENV
    meta = _meta((row or {}).get("run_id"))
    text = " ".join(str(meta.get(k) or "") for k in ("reason", "rule", "summary", "error")) + " " + str((block or {}).get("fail_why") or "")
    if _ENV_HINT.search(text):
        return ENV
    return MISREAD if row and row.get("status") == queue.DONE else IDEA


def _norm(s) -> str:
    return re.sub(r"[\s.,。'\"]+", "", str(s or "")).lower()


CARRY = "지난 목표의 다음 명령"  # 끝난 목표와 같은 줄을 다시 올렸을 때 첫 Cycle 명령의 출처(261026-jipsa-03)


def carry_plan(rec: dict) -> dict | None:
    """끝난 목표 기록에서 다음 목표의 첫 Cycle 명령으로 이을 명령. 마지막으로 판정한 Cycle이 고른 다음 명령이 있으면 그것이고,
    없으면(목표 도달이나 금지 사항으로 끝나 고르지 않았으면) 그 Cycle 분석이 쓴 다음 명령 가운데 금지 사항도 버린 가설도 아닌 첫 순위다.
    잇는 것이 없으면 None이다. 돌려주는 칸은 plan(명령 dict), n(지난 Cycle 번호), rank(순위), run_id(분석 실행ID)다."""
    for rnd in reversed(rec.get("rounds") or []):
        if not rnd.get("judge"):
            continue
        ana = (rnd.get("steps") or {}).get(ANALYSIS) or {}
        nxt = (rnd.get("next") or {}).get("plan")
        if isinstance(nxt, dict) and str(nxt.get("plan") or "").strip():
            return {"plan": dict(nxt), "n": rnd["n"], "rank": (rnd.get("next") or {}).get("chosen") or "", "run_id": ana.get("run_id") or ""}
        cmds = _commands(_cycle_block(ana.get("run_id") or "") or {})
        for n, rank in ((1, PRIMARY), (2, SECONDARY)):
            x = cmds.get(n)
            if x and x.get("plan") and not forbidden(x) and not dropped_hit(rec, x):
                return {"plan": {**x, "project": rec.get("project") or x.get("project") or ""}, "n": rnd["n"], "rank": rank,
                        "run_id": ana.get("run_id") or ""}
        return None
    return None


def dropped_hit(rec: dict, cmd: dict) -> str:
    """다음 명령이 시도 기록의 버린 가설과 같으면 그 문장이다. 같은 가설 key이거나 명령 문자열이 버린 가설이나 그 Cycle 명령과 같으면 같다고 본다."""
    key = str(cmd.get("key") or "").strip().lower()
    text = _norm(cmd.get("plan"))
    for a in reversed((rec.get("attempts") or [])[-ATTEMPT_KEEP:]):
        for d in a.get("dropped") or []:
            same_key = key and key == str(d.get("key") or "").strip().lower()
            same_text = text and text in (_norm(d.get("hypothesis")), _norm(d.get("command")))
            if same_key or same_text:
                return f"버린 가설 {d.get('key') or d.get('hypothesis', '')[:30]}(Cycle {a['n']}, {d.get('why', '')[:40]})"
    return ""


def _dropped(block: dict, rnd: dict) -> list[dict]:
    """분석이 적은 버린 가설. 명령 문자열은 그 가설을 시험한 이번 Cycle 명령이다."""
    fb = block.get("feedback") if isinstance(block.get("feedback"), dict) else {}
    out = []
    for d in fb.get("dropped") or []:
        if isinstance(d, str):
            d = {"hypothesis": d}
        if not isinstance(d, dict) or not (str(d.get("key") or "").strip() or str(d.get("hypothesis") or "").strip()):
            continue
        out.append({"key": str(d.get("key") or "").strip(), "hypothesis": str(d.get("hypothesis") or "").strip(),
                    "why": str(d.get("why") or "").strip(), "command": rnd["plan"].get("plan", "")})
    return out


def _workspace(rnd: dict) -> str:
    """독립 측정을 돌릴 폴더. 이행의 작업 폴더가 산출물이고, 없으면 같은 브랜치에서 시작한 분석의 작업 폴더다."""
    for k in (RUN, ANALYSIS):
        ws = _meta((rnd["steps"].get(k) or {}).get("run_id")).get("workspace")
        if ws and Path(ws).exists():
            return ws
    return ""


def measure(c: workitem.Cycle, rnd: dict) -> tuple[float | None, str]:
    """cycle 절의 측정 명령을 jipsa가 직접 돌려 출력의 마지막 수를 읽는다. (값, 사유). 명령이 없거나 못 재면 값이 None이다."""
    if not c.measure:
        return None, ""
    ws = _workspace(rnd)
    if not ws:
        return None, "측정 폴더 없음"
    try:
        p = subprocess.run(c.measure, shell=True, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=MEASURE_TIMEOUT, **hidden())
    except subprocess.TimeoutExpired:
        return None, f"측정 {MEASURE_TIMEOUT}초 초과"
    nums = re.findall(r"-?\d+(?:\.\d+)?", p.stdout or "")
    if p.returncode or not nums:
        return None, f"측정 실패(코드 {p.returncode}, 수 {'없음' if not nums else '있음'})"
    return float(nums[-1]), "jipsa 측정"


def fail_counts(rec: dict) -> dict[str, int]:
    """실패 범주별 수. 이행 실패와 나아지지 않은 Cycle의 범주를 함께 센다."""
    out = {k: 0 for k in FAIL_CLASSES}
    for r in rec["rounds"]:
        for f in r.get("run_fails") or []:
            if f.get("class") in out:
                out[f["class"]] += 1
        if r.get("fail_class") in out:
            out[r["fail_class"]] += 1
    return out


def feedback_lines(rec: dict) -> list[str]:
    """아침 보고와 cycle show에 붙이는 짧은 줄. 실패 범주 수, 버린 가설 요지, 판정에 쓴 다시 잰 값이다."""
    counts = {k: v for k, v in fail_counts(rec).items() if v}
    out = ["실패 범주: " + (", ".join(f"{k} {v}" for k, v in counts.items()) if counts else "없음")]
    drops = [f"{d.get('key') or d.get('hypothesis', '')[:20]}({d.get('why', '')[:30]})" for a in rec.get("attempts") or [] for d in a.get("dropped") or []]
    out.append("버린 가설: " + ("; ".join(drops[-5:]) if drops else "없음"))
    last = next((r for r in reversed(rec["rounds"]) if r.get("judge") and r["judge"].get("metric") is not None), None)
    if last:
        j = last["judge"]
        fmt = lambda x: "-" if x is None else f"{x:g}"  # noqa: E731
        diff = f", 이행이 적은 값 {fmt(j.get('run_metric'))}와 다름" if j.get("mismatch") else ""
        out.append(f"판정 값: Cycle {last['n']} {fmt(j['metric'])}({j.get('metric_src') or '분석 재측정'}{diff})")
    return out


# ----- 칸 점검과 금지 사항 -----
def run_missing(block: dict | None, pending: list[str] | None = None) -> list[str]:
    """이행 결과의 cycle 칸에서 빈 칸. 지표 값이 숫자로 있어야 한다. 목표 미정 Cycle은 지표가 아직 없어 비어도 된다."""
    if pending:
        return []
    return [] if block and _number(block.get("score")) is not None else ["지표"]


def _commands(block: dict) -> dict[int, dict]:
    """분석 피드백의 다음 명령. {순위: 명령}. 옛 틀(plans 칸)도 읽는다."""
    fb = block.get("feedback") if isinstance(block.get("feedback"), dict) else {}
    rows = fb.get("next") if isinstance(fb.get("next"), list) else block.get("plans") or []
    out = {}
    for i, p in enumerate(rows):
        if isinstance(p, str):
            p = {"command": p}
        if not isinstance(p, dict):
            continue
        text = str(p.get("command") or p.get("plan") or "").strip()
        out[int(_number(p.get("rank")) or i + 1)] = {**p, "plan": text}
    return out


_PROXY = re.compile(r"대리 지표|사람이|사람 확인|주관|만족도|느낌|자연스러움 평가")


def goal_missing(block: dict | None, pending: list[str]) -> list[str]:
    """목표 미정 Cycle에서 분석 결과 goal 칸의 빈 칸이나 틀린 칸(261026-jipsa-11). 비운 칸(pending)만 본다.
    지표는 대리 지표나 사람 확인이 아니어야 하고, 목표값은 숫자, 방향은 이상이나 이하다. 상한은 분석이 정하지 않아 보지 않는다."""
    g = (block or {}).get("goal") if isinstance((block or {}).get("goal"), dict) else {}
    out = []
    metric = str(g.get("metric") or "").strip()
    if "지표" in pending and (not metric or _PROXY.search(metric)):
        out.append("목표 지표" if not metric else "목표 지표(대리 지표나 사람 확인)")
    if "목표값" in pending:
        if _number(g.get("target")) is None:
            out.append("목표값")
        if str(g.get("dir") or "").strip() not in ("이상", "이하"):
            out.append("목표 방향")
    if not str(g.get("why") or "").strip():
        out.append("목표 근거")
    return out


def explore_missing(block: dict | None) -> list[str]:
    """탐색 지시를 받은 분석의 explore 칸에서 빈 칸(261027-jipsa-03). 찾아본 곳(searched)이 한 줄 이상 있고,
    후보가 한 개 이상이며 후보마다 출처(source나 ref)와 근거(why)가 있어야 한다."""
    ex = _explore_of(block)
    out = [] if ex["searched"] else ["탐색 searched"]
    if not ex["candidates"]:
        out.append("탐색 candidates")
    elif any(not (x["source"] or x["ref"]) or not x["why"] for x in ex["candidates"]):
        out.append("탐색 후보의 출처나 근거")
    return out


def analysis_missing(block: dict | None, pending: list[str] | None = None, explore: bool = False, branches: bool = False,
                     names: list[str] | None = None) -> list[str]:
    """분석 결과의 cycle 칸에서 빈 칸. 지표 값, 잘된 것, 모자란 것, 결과 판정, 다음 명령 1순위와 차순위가 있어야 한다. 버린 가설은 비어도 된다.
    목표 미정 Cycle이면 goal 칸(정한 지표, 목표값, 방향, 근거)도 있어야 한다(goal_missing).
    explore면 탐색 지시를 받은 분석이라 explore 칸도 있어야 한다(explore_missing). 옛 지시문으로 연 분석은 보지 않는다.
    branches면 Cycle 1 이행이 갈래 목록을 내지 못해 이 분석이 만들어야 한다(branch_list).
    names는 기록의 갈래 이름이다. 있으면 1순위와 차순위가 그 가운데 하나(Cycle 1은 이번에 고친 목록 포함)를 붙여야 한다."""
    if not block:
        return ["cycle"]
    out = goal_missing(block, pending) if pending else []
    out += [] if _number(block.get("score")) is not None else ["지표"]
    fb = block.get("feedback") if isinstance(block.get("feedback"), dict) else {}
    out += [name for k, name in _FEEDBACK if not str(fb.get(k) or "").strip()]
    if str(fb.get("verdict") or "").strip() not in VERDICTS:
        out.append("결과 판정")
    cmds = _commands(block)
    out += [f"다음 명령 {rank}" for n, rank in ((1, PRIMARY), (2, SECONDARY)) if not (cmds.get(n) or {}).get("plan")]
    out += ["갈래 목록"] if branches and not branch_list(block.get("branches")) else []
    known = set(names or []) | {b["name"] for b in branch_list(block.get("branches"))} | {(_branch_row(block.get("branch_new")) or {}).get("name")}
    if names or branches:
        out += [f"다음 명령 {rank} 갈래" for n, rank in ((1, PRIMARY), (2, SECONDARY))
                if (cmds.get(n) or {}).get("plan") and str((cmds.get(n) or {}).get("branch") or "").strip() not in known]
    return out + (explore_missing(block) if explore else [])


def forbidden(cmd: dict) -> list[str]:
    """다음 명령이 걸린 금지 사항. 푸시나 발행, torch 계열 변경, 외부 쓰기다. 범위 칸 대조는 하지 않는다(261023-jipsa-21 1안)."""
    out = []
    text = str(cmd.get("plan") or "")
    if cmd.get("push") or _PUSH.search(text):
        out.append("푸시나 발행")
    deps = [str(d) for d in cmd.get("deps") or [] if str(d).strip()]
    if any(_TORCH.search(d) for d in deps):
        out.append("torch 계열 의존성 변경")
    if cmd.get("external_write"):
        out.append("외부 쓰기")
    return out


# ----- 판정과 끝 조건 -----
def _deadline(c: workitem.Cycle, mode: dict) -> datetime | None:
    """Auto 마감. Auto 모드에서는 모드의 마감 하나이고, cycle 줄 시각이 더 이르면 그 시각이다. 유인 모드에서는 cycle 줄 시각만 본다."""
    cut = modes.cutoff_for(mode)
    own = None
    if c.no_new_after:
        t = datetime.combine(cut.date(), parse_hhmm(c.no_new_after))
        own = t - timedelta(days=1) if t > cut else t
    if mode.get("mode") == modes.AUTO:
        return min(cut, own) if own else cut
    return own


ANALYSIS_MIN = 40  # 분석과 피드백 단계의 상한(분). 서브에이전트 분석 24건 중 8건이 20분을 넘겨 올렸다(261029-jipsa-22 1안)


def run_est(c: workitem.Cycle, plan: dict, project: Project) -> int:
    """명령 이행 단계의 상한(분). 명령의 예상 시간, 줄의 Cycle 예상, 등록부 총 상한 순이다."""
    return int(_number(plan.get("est_minutes")) or c.round_est or project.total_minutes)


def deadline_room(c: workitem.Cycle, mode: dict, at: datetime, minutes: int | None) -> str:
    """새 단계를 열 여유(261027-jipsa-03). Auto 마감까지 남은 시간이 그 단계의 상한(분)보다 짧으면 열지 않은 이유이고, 열어도 되면 빈 문자열이다.
    목표에 닿은 뒤에도 마감까지 같은 지표 방향으로 잇되 마감에 끊길 단계는 열지 않는다. 목표는 끝내지 않고 다음 Auto가 잇는다.
    마감이 없으면(유인 모드에 cycle 줄 시각도 없음) 늘 연다."""
    dl = _deadline(c, mode)
    if not dl or not minutes:
        return ""
    left = (dl - at).total_seconds() / 60
    if left >= minutes:
        return ""
    # 남은 분을 넣지 않는다. 문장이 주기마다 바뀌면 기록을 매번 다시 쓴다
    # "마감 "으로 시작해야 한다. 시키기가 이 멈춤을 보고 마감까지 기다리지 않고 바로 닫는다(auto.DEADLINE_HOLD, 261029-jipsa-17)
    return f"마감 {dl:%H:%M} 전에 단계 상한 {int(minutes)}분을 마칠 수 없어 새 단계를 열지 않는다. 다시 시키면 잇는다"


def no_gain_streak(rec: dict) -> int:
    """끝에서부터 이어진 나아지지 않은 Cycle 수. 범주가 환경과 운영이나 측정 오류인 Cycle은 세지도 끊지도 않는다."""
    n = 0
    for r in reversed(_cur_rounds(rec)):
        if r.get("adopt") is None or r.get("fail_class") in UNCOUNTED:
            continue
        if r["adopt"]:
            break
        n += 1
    return n


def pivot_due(c: workitem.Cycle, streak: int) -> bool:
    """연속 나아지지 않음 streak 뒤의 다음 Cycle이 방향 전환 바퀴인지. 상한과 별개로 PIVOT_AFTER의 배수마다 전환한다.
    상한이 있고 streak가 상한에 닿았으면 끝이 먼저라 전환하지 않는다."""
    if streak < PIVOT_AFTER or streak % PIVOT_AFTER:
        return False
    return not (c.no_gain_limit and streak >= c.no_gain_limit)


def pivot_misses(rec: dict) -> list[str]:
    """전환 절에 넣을 끝에서부터의 나아지지 않은 Cycle 명령 요지(최근 PIVOT_AFTER개, 오래된 것이 앞). 판정 전인 마지막 Cycle도 든다."""
    out = []
    for r in reversed(_cur_rounds(rec)):
        if r.get("fail_class") in UNCOUNTED:
            continue
        if r.get("adopt"):
            break
        out.append(f"Cycle {r['n']}: {str((r.get('plan') or {}).get('plan') or '')[:100]}")
        if len(out) >= PIVOT_AFTER:
            break
    return out[::-1]


def pivot_plan(c: workitem.Cycle, rec: dict) -> dict:
    """분석이 전환 명령을 내지 않았거나 금지 사항, 버린 가설에 걸렸을 때의 전환 명령. 지난 명령을 되풀이하지 않고
    마지막 분석이 낸 안 한 후보 가운데 하나를 이행이 고르게 한다. 후보가 없으면 이행이 탐색 칸에서 찾는다."""
    cands = [str(x.get("method") or "")[:120] for r in reversed(_cur_rounds(rec)) for x in (r.get("explore") or {}).get("candidates") or []
             if x.get("method") and not x.get("tried")][:3]
    text = ("방향 전환 바퀴다. 최고 기록에서 다시 출발해, 지난 바퀴들과 다른 쪽의 안 한 후보 하나를 골라 이행하고 같은 조건으로 다시 잰다. "
            f"지난 {PIVOT_AFTER}바퀴의 방향을 되풀이하지 않는다. 지난 미개선 Cycle의 명령 요지: {' / '.join(pivot_misses(rec)) or '없음'}. "
            + ("안 한 후보: " + " / ".join(cands) + "." if cands else "안 한 후보는 cycle 기록의 지난 분석 탐색 칸에서 고른다."))
    return {"plan": text, "project": c.project, "pivot": True}


# ----- 아이디어 갈래(261029-jipsa-10 1안) -----
def _branch_row(x) -> dict | None:
    """갈래 한 줄. 이름, 가설, 첫 명령, 끝낼 조건이 다 있어야 한다."""
    if not isinstance(x, dict):
        return None
    b = {k: " ".join(str(x.get(k) or "").split())[:200] for k in ("name", "hypothesis", "first", "done_when")}
    return {**b, "needs_approval": bool(x.get("needs_approval"))} if all(b.values()) else None


def branch_list(rows) -> list[dict]:
    """이행이나 분석이 적은 갈래 목록. 칸이 빠졌거나 이름이 겹친 줄을 뺀 뒤 BRANCH_MIN~BRANCH_MAX개가 아니면 빈 목록이다."""
    out = []
    for x in rows if isinstance(rows, list) else []:
        b = _branch_row(x)
        if b and b["name"] not in {o["name"] for o in out}:
            out.append(b)
    return out if BRANCH_MIN <= len(out) <= BRANCH_MAX else []


def _branch(rec: dict, name) -> dict | None:
    name = str(name or "").strip()
    return next((b for b in rec.get("branches") or [] if b["name"] == name), None) if name else None


def set_branches(rec: dict, rows: list[dict], n: int, by: str) -> None:
    """갈래 목록을 기록에 둔다. 이름이 같은 갈래는 바퀴, 연속 미개선, 최고값, 상태를 잇는다. 범위 칸 밖 갈래는 사람 확인으로 넘긴다."""
    old = {b["name"]: b for b in rec.get("branches") or []}
    out = []
    for b in rows:
        o = old.get(b["name"]) or {}
        st = ASK if b["needs_approval"] and o.get("status") != CLOSED else o.get("status") or OPEN
        out.append({**b, "status": st, "rounds": o.get("rounds") or [], "streak": int(o.get("streak") or 0), "best": o.get("best"),
                    "closed_at": o.get("closed_at"), "added": o.get("added") or {"n": n, "by": by}})
    rec["branches"] = out


def branch_update(rec: dict, rnd: dict, block: dict) -> None:
    """분석이 적은 갈래 칸을 기록에 옮긴다. Cycle 1 분석은 목록 전체를 고쳐 쓰고, 그 뒤 분석은 새 갈래를 한 번에 하나만 더한다.
    이번 Cycle 명령의 갈래는 분석이 다시 본 값(branch_this)이 먼저다. 명령에 붙은 갈래와 다르면 고친 사실을 남긴다."""
    rows = branch_list(block.get("branches")) if rnd["n"] == 1 else []
    if rows:
        set_branches(rec, rows, rnd["n"], ANALYSIS)
    new, raw = _branch_row(block.get("branch_new")), block.get("branch_new") or {}
    why = " ".join(str(raw.get("why") or "").split())[:200] if isinstance(raw, dict) else ""
    same = new and any(_norm(new[k]) == _norm(b[k]) for b in rec.get("branches") or [] for k in ("hypothesis", "first"))
    if new and why and not same and rec.get("branches") and not _branch(rec, new["name"]):
        # 다른 점(why)이 없거나 기존 갈래의 가설이나 첫 명령을 그대로 쓴 새 갈래는 이름만 바꾼 재진입으로 보고 받지 않는다
        rec["branches"].append({**new, "status": ASK if new["needs_approval"] else OPEN, "rounds": [], "streak": 0, "best": None,
                                "closed_at": None, "added": {"n": rnd["n"], "by": ANALYSIS, "why": why}})
    this = str(block.get("branch_this") or "").strip()
    if _branch(rec, this):
        if rnd.get("branch") and rnd["branch"] != this:
            rnd["branch_fixed"] = rnd["branch"]  # 분석이 앞 분석이 붙인 갈래를 고쳤다
        rnd["branch"] = this


def branch_count(c: workitem.Cycle, rec: dict, rnd: dict, better: bool, cls: str) -> str:
    """이번 Cycle을 그 갈래에 센다. 나아지면 그 갈래 연속 미개선이 0, 나아지지 않으면 1 오르고 BRANCH_CLOSE에 닿으면 닫는다.
    환경과 운영, 측정 오류는 바퀴에만 넣고 세지 않는다. 닫은 갈래 이름이고, 없으면 빈 문자열이다."""
    b = _branch(rec, rnd.get("branch"))
    if not b:
        return ""
    if rnd["n"] not in b["rounds"]:
        b["rounds"].append(rnd["n"])
    if cls in UNCOUNTED:
        return ""
    if _better(c, rnd.get("score"), b.get("best"), None) and rnd.get("score") is not None:
        b["best"] = rnd["score"]
    if better:
        b["streak"] = 0
        return ""
    b["streak"] = int(b.get("streak") or 0) + 1
    if b["streak"] >= BRANCH_CLOSE and b["status"] == OPEN:
        b.update(status=CLOSED, closed_at=rnd["n"])
        return b["name"]
    return ""


def branch_hit(rec: dict, cmd: dict) -> str:
    """다음 명령의 갈래가 닫혔거나 사람 확인으로 넘긴 갈래, 또는 목록에 없는 갈래(안 붙임 포함)면 그 문장이다. 갈래 목록이 없는 목표는 막지 않는다."""
    b = _branch(rec, cmd.get("branch"))
    if rec.get("branches") and not b:
        return f"목록에 없는 갈래 '{str(cmd.get('branch') or '').strip() or '없음'}'"
    if b and b["status"] == CLOSED:
        return f"닫힌 갈래 {b['name']}(Cycle {b['closed_at']})"
    if b and b["status"] == ASK:
        return f"사람 확인 갈래 {b['name']}"
    return ""


def recent_branches(rec: dict) -> list[str]:
    """전환 바퀴가 피할 갈래. 끝에서부터 나아지지 않은 Cycle(최근 PIVOT_AFTER개)의 갈래다."""
    out = []
    for r in reversed(_cur_rounds(rec)):
        if r.get("fail_class") in UNCOUNTED:
            continue
        if r.get("adopt"):
            break
        if r.get("branch"):
            out.append(r["branch"])
        if len(out) >= PIVOT_AFTER:
            break
    return list(dict.fromkeys(out))


def branch_pick(rec: dict, avoid: list[str]) -> dict | None:
    """다음에 갈 열린 갈래. avoid 밖에서 안 간 갈래가 먼저, 그다음 덜 간 갈래이고 같으면 목록 차례다. avoid 밖에 없으면 None이다."""
    opened = [b for b in rec.get("branches") or [] if b["status"] == OPEN]
    pool = [b for b in opened if b["name"] not in avoid]
    return min(pool, key=lambda b: (len(b["rounds"]), opened.index(b))) if pool else None


def branch_plan(c: workitem.Cycle, b: dict, pivot: bool) -> dict:
    """jipsa가 고른 갈래의 명령. 안 간 갈래면 그 갈래의 첫 명령이고, 간 갈래면 그 갈래 안의 새 명령을 이행이 고르게 한다."""
    head = "방향 전환 바퀴다. 최고 기록에서 다시 출발한다. " if pivot else ""
    body = (f"갈래 '{b['name']}'의 첫 명령: {b['first']}" if not b["rounds"] else
            f"갈래 '{b['name']}'(가설: {b['hypothesis']})에서 지난 바퀴와 다른 명령 하나를 골라 이행한다")
    return {"plan": f"{head}{body}. 같은 조건으로 다시 잰다. 이 갈래의 끝낼 조건: {b['done_when']}.", "project": c.project,
            "branch": b["name"], "pivot": pivot}


def branches_out(rec: dict) -> str:
    """갈래가 있는데 열린 갈래가 없으면 확인 필요 끝 사유다. 분석이 새 갈래를 더하지 못한 경우다."""
    bs = rec.get("branches") or []
    stuck = rec.get("branch_stuck")
    if isinstance(stuck, list) and any(b["status"] == OPEN for b in bs):
        return f"{HOLD_END}(전환 바퀴에 갈 다른 갈래 없음: 열린 갈래가 지난 미개선 갈래 {', '.join(stuck)}뿐이고 분석이 새 갈래를 더하지 않음)"
    if not bs or any(b["status"] == OPEN for b in bs):
        return ""
    closed = [b["name"] for b in bs if b["status"] == CLOSED]
    ask = [b["name"] for b in bs if b["status"] == ASK]
    return (f"{HOLD_END}(갈래가 모두 닫힘: 닫힘 {', '.join(closed) or '없음'}"
            + (f", 사람 확인 {', '.join(ask)}" if ask else "") + ". 분석이 새 갈래를 더하지 않음)")


def branch_view(rec: dict) -> list[dict]:
    """화면과 결과지가 읽는 갈래 줄."""
    return [{k: b.get(k) for k in ("name", "hypothesis", "status", "streak", "best", "closed_at", "needs_approval")} | {"rounds": len(b.get("rounds") or [])}
            for b in rec.get("branches") or []]


def _branch_or_pivot(c: workitem.Cycle, rec: dict, avoid: list[str], turn: bool) -> tuple[str, dict | None]:
    """jipsa가 만드는 다음 명령. 갈래가 있으면 열린 갈래(avoid 밖 먼저)의 명령이고, 갈래가 없으면 전환 바퀴만 전환 기본 명령이다.
    열린 갈래가 없거나 전환 바퀴에 지난 미개선 갈래 밖의 열린 갈래가 없으면 명령 없이 두고 rec의 branch_stuck에 남긴다.
    끝 판정(branches_out)이 확인 필요로 끝낸다."""
    if rec.get("branches"):
        b = branch_pick(rec, avoid)
        if not b:
            rec["branch_stuck"] = avoid or True
        return (BRANCH, branch_plan(c, b, turn)) if b else ("", None)
    return (PIVOT_BASE, pivot_plan(c, rec)) if turn else ("", None)


def reached(c: workitem.Cycle, score: float | None) -> bool:
    """목표값과 방향으로 본 도달 여부."""
    if c.target is None or score is None:
        return False
    return score <= c.target if c.direction == "이하" else score >= c.target


def _better(c: workitem.Cycle, score: float | None, best: float | None, delta: float | None) -> bool:
    """지표가 지금 최고 기록보다 목표 방향으로 나아졌는지. 최고 기록이 없으면 첫 측정이라 나아짐으로 보고 최고 기록이 된다."""
    if score is None:
        return False
    if best is None:
        return True
    return score < best if c.direction == "이하" else score > best


def end_reason(c: workitem.Cycle, rec: dict, mode: dict, at: datetime) -> str:
    """새 Cycle을 열기 전에 본다. 닿은 끝 조건 문장이고, 없으면 빈 문자열이다. Cycle 수와 cycle 전체 시간 상한은 없다.
    사용 창 비율은 끝 조건이 아니다."""
    cur = _cur_rounds(rec)
    last = cur[-1] if cur else None
    j = (last or {}).get("judge") or {}
    if j.get("ox") == "O" and getattr(c, "stop_on_reach", True):
        human = f", 사람 확인 {len(c.human)}개 대기" if c.human else ""
        return f"목표 도달(Cycle {last['n']} 지표 {j['metric']:g}, 목표 {c.target:g} {c.direction}{human})"
    if j.get("forbidden"):
        return f"다음 명령이 금지 사항({j['forbidden']})"
    out = branches_out(rec)
    if out:
        return out
    streak = no_gain_streak(rec)
    if c.no_gain_limit and streak >= c.no_gain_limit:  # 0이면 상한 없음. Auto 목록 줄은 사람이 상한을 적었을 때만 둔다
        return f"{streak} Cycle 연속 나아지지 않음"
    if getattr(c, "origin", "") == "todo":
        return ""  # 할 일 줄 Cycle 목표는 마감으로 끝나지 않는다. 시키기가 마감 결과지를 쓰고 닫으며 다시 시키면 잇는다(auto._finish)
    dl = _deadline(c, mode)
    if dl and at >= dl:
        return f"Auto 마감 {dl:%H:%M}"
    if dl and c.round_est and at + timedelta(minutes=c.round_est) > dl:
        return f"Auto 마감 {dl:%H:%M} 전에 Cycle({c.round_est}분)을 마칠 수 없음"
    return ""


def judge(c: workitem.Cycle, rec: dict, rnd: dict, block: dict | None, at: datetime, failed: str = "") -> None:
    """목표 판정. 실행 기록을 만들지 않고 Cycle의 judge 칸(O/X, 지표, 목표값, 다음 명령)으로만 남긴다.
    failed가 있으면 분석이 칸을 채우지 못한 Cycle이다. 나아지지 않음으로 세고 같은 명령을 다음 Cycle에 다시 쓴다.
    판정 값은 jipsa가 측정 명령으로 직접 잰 값, 없으면 분석이 다시 잰 값이다. 이행이 적은 값은 기록에만 남긴다(독립 판정)."""
    block = block or {}
    run_metric = _number((_cycle_block(rnd["steps"][RUN].get("run_id") or "") or {}).get("score"))
    remeasured = _number(block.get("score"))
    jipsa, jipsa_why = (None, "") if failed else measure(c, rnd)
    score, src = (jipsa, jipsa_why) if jipsa is not None else (remeasured, "분석 재측정")
    delta = _number(block.get("delta"))
    fb = block.get("feedback") if isinstance(block.get("feedback"), dict) else {}
    better = not failed and _better(c, score, rec.get("score"), delta)
    verdict = str(fb.get("verdict") or "").strip()
    cls = "" if better or failed else (str(fb.get("fail_class") or "").strip() if str(fb.get("fail_class") or "").strip() in FAIL_CLASSES else IDEA)
    rnd.update(delta=delta, low=_number(block.get("low")), high=_number(block.get("high")), score=score, adopt=better,
               feedback={k: str(fb.get(k) or "") for k, _ in _FEEDBACK}, verdict=verdict, fail_class=cls)
    if not failed:
        rnd["explore"] = _explore_of(block)  # 분석이 찾은 후보와 출처. 다음 분석과 끝 결과지가 읽는다(261027-jipsa-03)
        branch_update(rec, rnd, block)
    shut = branch_count(c, rec, rnd, better, cls)
    rec.pop("branch_stuck", None)  # 같은 갈래 연속 미개선 BRANCH_CLOSE면 닫는다(261029-jipsa-10 1안)
    if better:
        rec["score"] = score
        rec["baseline_ref"] = rnd["steps"][RUN].get("branch") or rec.get("baseline_ref") or ""
        rec["baseline_round"] = rnd["n"]
    # 시도 기록. 다음 명령을 고르기 전에 쌓아 이번 Cycle에 버린 가설도 대조에 든다
    rec["attempts"] = ((rec.get("attempts") or []) + [{
        "n": rnd["n"], "command": rnd["plan"].get("plan", ""), "key": str(rnd["plan"].get("key") or ""), "branch": rnd.get("branch") or "", "verdict": verdict or ("분석 실패" if failed else ""),
        "metric": score, "fail_class": cls, "dropped": [] if failed else _dropped(block, rnd)}])[-ATTEMPT_KEEP:]
    ox = "O" if not failed and reached(c, score) else "X"
    if ox == "O":
        # 목표 도달 기록. 처음 닿은 Cycle과 닿은 Cycle 목록을 남긴다. 끝내지 않는 목표는 이 칸으로 Auto 끝 글과 결과지가 도달을 적는다
        rec.setdefault("reached", {"n": rnd["n"], "metric": score, "at": at.isoformat(timespec="seconds")})
        rec["reached_rounds"] = sorted(set((rec.get("reached_rounds") or []) + [rnd["n"]]))
    chosen, cmd, stops, skips = "", None, [], []
    turn = pivot_due(c, no_gain_streak(rec))
    avoid = recent_branches(rec) if turn else []  # 전환 바퀴는 지난 미개선 바퀴의 갈래로 가지 않는다
    if failed and (turn or branch_hit(rec, rnd["plan"])):
        chosen, cmd = _branch_or_pivot(c, rec, avoid, turn)  # 전환 바퀴나 닫힌 갈래에는 같은 명령을 다시 쓰지 않는다
    elif failed:
        chosen, cmd = SAME, {k: v for k, v in rnd["plan"].items()}
    elif ox == "X" or not getattr(c, "stop_on_reach", True):
        cmds = _commands(block)
        order = ((3, PIVOT),) if turn else ((1, PRIMARY), (2, SECONDARY))  # 전환이면 전환이 다가온 분석이 쓴 rank 3 명령만 본다
        for n, rank in order:
            x = cmds.get(n)
            if not x or not x.get("plan"):
                continue
            why = forbidden(x)
            hit = dropped_hit(rec, x) or branch_hit(rec, x)
            if not hit and x.get("branch") in avoid:
                hit = f"지난 미개선 바퀴와 같은 갈래 {x['branch']}"
            if not why and not hit:
                chosen, cmd = rank, {**x, "project": c.project}
                break
            if why:
                stops.append(f"{rank} {', '.join(why)}")
            if hit:
                skips.append(f"{rank} {hit}")
        if turn and not cmd:
            chosen, cmd = _branch_or_pivot(c, rec, avoid, turn)  # 전환 명령이 없거나 걸렸다. 1순위로 돌아가지 않고 열린 다른 갈래나 jipsa의 전환 명령을 쓴다
        elif not cmd and not stops and rec.get("branches") and skips:
            chosen, cmd = _branch_or_pivot(c, rec, [], False)  # 두 순위가 닫힌 갈래나 버린 가설이다. 기본 명령 대신 열린 갈래의 명령을 쓴다
    started = parse_iso(rnd["started"]) if rnd.get("started") else at
    mismatch = run_metric is not None and score is not None and abs(run_metric - score) > 1e-9
    checks = {}
    for x in (block.get("checks") or []) if not failed and c.checks else []:
        if isinstance(x, dict) and str(x.get("id") or "").strip():
            v = str(x.get("ox") or "").strip()
            checks[str(x["id"]).strip()] = v if v in ("O", "X") else UNMEASURED
    need = str((cmd or {}).get("plan", ""))[:60] if (cmd or {}).get("needs_approval") else ""
    rnd["judge"] = {"ox": ox, "metric": score, "target": c.target, "direction": c.direction, "better": better,
                    "checks": checks, "needs_approval": need, "version": c.version,
                    "run_metric": run_metric, "remeasured": remeasured, "jipsa_metric": jipsa, "jipsa_why": jipsa_why,
                    "metric_src": src if score is not None else "", "mismatch": mismatch, "verdict": verdict, "fail_class": cls,
                    "next": (cmd or {}).get("plan", ""), "next_rank": chosen, "forbidden": "; ".join(stops) if not cmd and stops else "",
                    "skipped": "; ".join(skips), "failed": failed, "branch": rnd.get("branch") or "", "closed": shut,
                    "next_branch": (cmd or {}).get("branch") or "", "minutes": max(0, int((at - started).total_seconds() // 60)),
                    "at": at.isoformat(timespec="seconds")}
    rnd["steps"][JUDGE] = {"key": "", "status": queue.DONE, "minutes": 0, "at": at.isoformat(timespec="seconds"), "provider": "jipsa"}
    # 대시보드 카드가 읽는 다음 명령 칸. 범위 칸 대조를 없애 checks는 금지 사항에 걸린 순위만 든다
    rnd["next"] = {"chosen": chosen, "plan": cmd, "checks": {s.split(" ")[0]: [s] for s in stops}}


# ----- 사용 창 표시 -----
def window_view(at: datetime | None = None) -> dict:
    """사용 창 글자. 표시만 하고 새 시작, 동시 수, Do를 막지 않는다(261102-jipsa-32, 42, 50 사용자 답). 실제 한도 오류만 실행기가 처리한다."""
    at = at or now()
    w = codex_window.window(at)
    measured = w["state"] == codex_window.LIMIT or w.get("source") != "어림"
    return {"claude": claude_window.usage(at)["text"], "codex": codex_window.env_text(w) if measured else "Codex 창 실측 없음"}


# ----- 진행 -----
def _entry(c: workitem.Cycle, project: Project, title: str, criteria: str, est: int | None, start_ref: str = "",
           step: str = "", n: int | None = None) -> dict:
    item = workitem.Item(c.project, title, criteria, est, c.file, c.line, None, False, TIER)
    e = queue._entry_from_item(item, project, TIER)
    e["file"] = ""  # cycle 단계는 주간 파일에 줄이 따로 없다. 결과는 cycle 기록과 범위 패널에 남는다
    e["cycle"] = c.key
    e.update(getattr(c, "entry_extra", None) or {})
    if step:
        e["cycle_step"] = step  # 작업자 실행 기록에도 옮겨 화면이 Cycle 줄과 종합 보고 줄을 가른다
    if n is not None:
        e["cycle_round"] = n
    if c.priority is not None:
        e["priority"] = c.priority
    if start_ref:
        e["start_ref"] = start_ref  # 나아진 앞 Cycle 브랜치에서 작업 트리를 만든다
    return queue.add_entry(e)


def owner(rec: dict) -> str:
    return rec.get("owner") or WORKER


def _start(c: workitem.Cycle, rec: dict, project: Project, title: str, criteria: str, est: int | None, start_ref: str = "",
           step: str = RUN, n: int = 0) -> dict:
    """Cycle의 한 단계를 연다. 큐 대기 줄이다. Main 지휘(서브에이전트 실행 기록)는 261025-jipsa-42에서 뗐다."""
    return _entry(c, project, title, criteria, est, start_ref, step, n)


def _open_round(c: workitem.Cycle, rec: dict, project: Project, plan: dict, source: str, at: datetime) -> None:
    n = len(rec["rounds"]) + 1
    if not rec["rounds"]:
        rec["branch_v"] = 1  # 갈래를 쓰는 목표. 옛 기록은 이 칸이 없어 갈래 없이 돈다(261029-jipsa-10 1안)
    streak = no_gain_streak(rec)
    pivot = {"streak": streak, "misses": pivot_misses(rec), "from": rec.get("baseline_round")} if _cur_rounds(rec) and pivot_due(c, streak) else None
    title = f"{c.title} Cycle {n} {RUN}" + (f" ({PIVOT_TEXT})" if pivot else "")
    est = run_est(c, plan, project)
    crit = prompts.cycle_run(c, n=n, plan=plan, record_file=record_path(c), history=history(rec), feedback=feedback_for(c, rec, RUN, n),
                             prior=feedback_prior(c, rec, RUN, n) if n == 1 else None, branches=run_branches(rec, n))
    e = _start(c, rec, project, title, crit, est, rec.get("baseline_ref") or "", RUN, n)
    rec["rounds"].append({"n": n, "v": int(rec.get("version") or 0), "plan": plan, "source": source, "start_ref": rec.get("baseline_ref") or "",
                          "started": at.isoformat(timespec="seconds"), "steps": {RUN: {"key": e["key"], "status": e["status"], "run_id": e.get("run_id") or ""}},
                          "delta": None, "low": None, "high": None, "score": None, "adopt": None, "judge": None, "next": None, "pivot": pivot,
                          "branch": plan.get("branch") if _branch(rec, plan.get("branch")) else ""})
    if pivot:
        from scheduler import events

        events.emit("cycle_pivot", cycle=c.key, n=n, streak=streak, source=source)
    if rec["status"] != LIVE:
        rec.update(status=LIVE, started=rec.get("started") or at.isoformat(timespec="seconds"),
                   report_date=modes.cutoff_for().date().isoformat())


def _end(c: workitem.Cycle, rec: dict, why: str, at: datetime) -> None:
    rec.update(status=ENDED, end_reason=why, finished=at.isoformat(timespec="seconds"))
    if not rec.get("report_date"):
        rec["report_date"] = modes.cutoff_for().date().isoformat()
    if rec["rounds"] and rec["rounds"][-1].get("judge"):
        rec["rounds"][-1]["judge"]["end"] = why
    # 끝 결과지와 할 일 파일 정리는 auto가 한다. 주간 파일 끝 표시는 261025-jipsa-42에서 뗐다


def _close_step(step: dict, reason: str, at: datetime) -> str:
    """돌던 단계 하나를 실패로 닫는다. 실행 기록이 진행 중이면 마감하고, 시작 전 큐 줄은 실패로 바꾼다. 닫은 실행ID나 큐 key, 없으면 빈 값이다.
    작업자 프로세스가 이미 돌고 있으면 끊지는 않는다. 목표가 끝났으므로 그 결과는 cycle에 쓰이지 않는다."""
    row = _row(step["key"]) if step.get("key") else None
    run_id = step.get("run_id") or (row or {}).get("run_id") or ""
    if (_meta(run_id).get("status") or "") == "진행 중":
        record.finish(run_id, status="실패", result={"reason": reason, "summary": reason, "category": STOP_END, "written_by": "jipsa"}, notify=False)
        step["status"] = queue.FAILED
        return run_id
    if row and row["status"] in (queue.PENDING, queue.RUNNING):
        queue.update(row["key"], status=queue.FAILED, reason=reason, finished=at.isoformat(timespec="seconds"))
        step["status"] = queue.FAILED
        return run_id or row["key"]
    return ""


def stop(c: workitem.Cycle, why: str, at: datetime | None = None) -> tuple[bool, str]:
    """사람이 목표를 멈춘다(261024-jipsa-16 1안). 끝 사유 사람 멈춤으로 끝내고, 돌던 단계는 실패로 닫고, Main의 할 일을 비운다.
    끝난 목표는 더 진행하지 않는다.
    이미 끝난 목표면 아무것도 바꾸지 않는다. (바꿨는지, 알릴 문장)이다."""
    at = at or now()
    rec = load(c)
    if rec["status"] == ENDED:
        return False, f"이미 끝난 목표다({rec.get('end_reason') or '사유 없음'}). 아무것도 바꾸지 않았다"
    why = " ".join(str(why or "").split())[:120] or "이유 없음"
    reason = f"{STOP_END}: {why}"
    steps = [s for r in rec["rounds"][-1:] for k, s in r["steps"].items() if k in (RUN, ANALYSIS)]
    s = rec.get("setup")
    if s and s.get("v") != rec.get("version"):
        steps.append(s)  # 박지 않은 목표 정하기 단계
    closed = [x for x in (_close_step(st, reason, at) for st in steps) if x]
    hold = rec.pop("hold", None)
    if hold and hold.get("run_id"):
        from scheduler import confirm

        confirm.ack(hold["run_id"])  # 승인 대기 카드는 사람이 멈춤으로 답한 것이다
    for k in ("todo", "resetup", "paused", "reclaim", "approved_v"):
        rec.pop(k, None)
    _end(c, rec, f"{STOP_END}({why})", at)
    save(c, rec)
    from scheduler import events

    events.emit("cycle_stop", cycle=c.key, why=why, closed=closed)
    return True, f"목표를 끝냈다(끝 사유 {STOP_END}: {why}). 닫은 단계 {', '.join(closed) if closed else '없음'}"


def _cycle_block(run_id: str) -> dict | None:
    """단계 결과지(result.json)의 cycle 칸. 다시 돌린 시도가 있으면 마지막 것이다."""
    dirs = record.attempt_dirs(run_id) if run_id else []
    for d in reversed(dirs):
        res = record.read_json(d / "result.json") or {}
        if isinstance(res.get("cycle"), dict):
            return res["cycle"]
    return None


def _redo_run(c: workitem.Cycle, rec: dict, rnd: dict, project: Project, why: str) -> None:
    """같은 명령으로 이행을 다시 시킨다. 앞 이행 시간은 Cycle 시간에 남긴다. 실패 내역은 rnd의 run_fails 칸에 쌓인다."""
    run = rnd["steps"][RUN]
    tries = len(rnd.get("run_fails") or [])
    title = f"{c.title} Cycle {rnd['n']} {RUN} 다시" + (f" {tries}" if tries > 1 else "")
    crit = prompts.cycle_run(c, n=rnd["n"], plan=rnd["plan"], record_file=record_path(c), history=history(rec), retry=why,
                            feedback=feedback_for(c, rec, RUN, rnd["n"]), prior=feedback_prior(c, rec, RUN, 1) if rnd["n"] == 1 else None,
                            branches=run_branches(rec, rnd["n"]))
    est = int(_number(rnd["plan"].get("est_minutes")) or c.round_est or project.total_minutes)
    e = _start(c, rec, project, title, crit, est, rnd.get("start_ref") or "", RUN, rnd["n"])
    rnd["steps"][RUN] = {"key": e["key"], "status": e["status"], "run_id": e.get("run_id") or "", "retry": True, "first_run": run.get("run_id"),
                         "first_status": run.get("status"), "first_why": why, "minutes_before": run.get("minutes", 0)}


def artifacts(rnd: dict) -> dict:
    """분석에 넘기는 이행 산출물 위치. 브랜치, 커밋, 바뀐 파일, 작업 폴더만 담고 이행의 보고와 지표 주장은 담지 않는다."""
    run = rnd["steps"][RUN]
    meta = _meta(run.get("run_id"))
    res = {}
    for d in reversed(record.attempt_dirs(run["run_id"]) if run.get("run_id") else []):
        res = record.read_json(d / "result.json") or {}
        if res:
            break
    files = res.get("changed_files") if isinstance(res.get("changed_files"), list) else []
    return {"branch": run.get("branch") or meta.get("branch") or "", "commit": str(res.get("commit") or meta.get("commit") or ""),
            "changed_files": [str(f) for f in files][:20], "workspace": meta.get("workspace") or ""}


def set_goal(c: workitem.Cycle, rec: dict, rnd: dict, block: dict, at: datetime) -> str:
    """목표 미정 Cycle에서 분석이 정한 목표를 할 일 줄 cycle 칸의 빈 칸에 적고 c를 그 값으로 바꾼다(261026-jipsa-11).
    사람이 적은 칸은 그대로다. 기록의 goal_set 칸에 값, 근거, 분석 실행ID를 남긴다. 적지 못하면 그 이유이고, 적었으면 빈 문자열이다."""
    from scheduler import todo

    g = dict(block.get("goal") or {})
    # 상한은 분석이 정하지 않는다. 분석이 cap을 적어도 버리고 사람이 비운 상한은 비운 채 둔다(261029-jipsa-03 1안)
    goal = {"metric": str(g.get("metric") or "").strip(), "target": _number(g.get("target")), "unit": str(g.get("unit") or "").strip(),
            "dir": str(g.get("dir") or "").strip(), "cap": None}
    key = (c.entry_extra or {}).get("todo_key") or c.key
    try:
        item, filled = todo.fill_cycle(key, goal)
    except todo.TodoError as e:
        return str(e)
    if item is not None and item.cycle:
        cy = item.cycle
    else:  # 사람이 그 사이 줄을 지웠다. 이번 판정만 분석이 정한 값으로 한다. 끝내기는 시키기가 줄이 없어진 것을 보고 한다
        cy = {"metric": c.metric or goal["metric"], "target": f"{c.target:g}" if c.target is not None else f"{goal['target']:g}",
              "unit": goal["unit"], "dir": c.direction if "목표값" not in c.pending else goal["dir"], "cap": c.no_gain_limit or None}
        filled = list(c.pending)
    miss = todo.cycle_pending(cy)
    if miss:
        return f"정한 뒤에도 {', '.join(miss)}이 비었다"
    c.metric, c.target, c.direction = cy["metric"], float(cy["target"]), cy.get("dir") or "이상"
    c.success = f"{cy['target']}{cy.get('unit') or ''} {c.direction}"
    c.no_gain_limit = int(cy.get("cap") or 0)
    c.pending = []
    text = todo.cycle_text(cy)
    rec["target"] = c.target
    rec["goal_set"] = {"n": rnd["n"], "run_id": (rnd["steps"].get(ANALYSIS) or {}).get("run_id") or "", "filled": filled, "text": text,
                       "metric": c.metric, "target": c.target, "unit": cy.get("unit") or "", "dir": c.direction, "cap": cy.get("cap"),
                       "why": str(g.get("why") or "")[:400], "at": at.isoformat(timespec="seconds")}
    rnd["goal_set"] = text
    from scheduler import events

    events.emit("cycle_goal_set", cycle=c.key, n=rnd["n"], text=text, filled=filled)
    return ""


# ----- 탐색 자료(261027-jipsa-03) -----
EXPLORE_KEEP = 12  # 후보와 다른 목표 줄 상한. 분석 지시문이 너무 길어지지 않게 자른다


def _explore_of(block: dict | None) -> dict:
    """분석 결과 cycle 칸의 explore를 기록에 옮길 모양으로 줄인다. 시도한 것, 후보(방법, 출처, 근거, 시도 여부), 찾아본 곳, 반복 이유다."""
    ex = (block or {}).get("explore") if isinstance((block or {}).get("explore"), dict) else {}
    cands = []
    for x in ex.get("candidates") or []:
        if isinstance(x, str):
            x = {"method": x}
        if isinstance(x, dict) and str(x.get("method") or "").strip():
            cands.append({k: str(x.get(k) or "")[:200] for k in ("method", "source", "ref", "why", "fit")} | {"tried": bool(x.get("tried"))})
    return {"tried": [str(t)[:160] for t in ex.get("tried") or [] if str(t).strip()][:EXPLORE_KEEP],
            "candidates": cands[:EXPLORE_KEEP], "searched": [str(t)[:160] for t in ex.get("searched") or [] if str(t).strip()][:EXPLORE_KEEP],
            "repeat_why": str(ex.get("repeat_why") or "")[:300]}


def _other_goals(c: workitem.Cycle) -> list[str]:
    """같은 프로젝트의 다른 Cycle 목표 기록(돌고 있거나 끝난 것). 목표 문장, 상태, 최고 기록, 마지막 다음 명령, 기록 파일이다.
    다른 목표가 만든 모델 후보와 방법론을 이 목표의 분석이 놓치지 않게 넘긴다."""
    own = record_path(c).resolve()
    paths = [p for p in CYCLE_DIR.glob("*.json") if f"{c.project}-" in p.name and p.resolve() != own] if CYCLE_DIR.exists() else []
    out = []
    for p in sorted(paths, key=lambda q: q.stat().st_mtime, reverse=True)[:6]:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("project") and r.get("project") != c.project:
            continue
        rounds = r.get("rounds") or []
        nxt = next((str((x.get("next") or {}).get("plan", {}).get("plan") or "") for x in reversed(rounds)
                    if isinstance((x.get("next") or {}).get("plan"), dict)), "")
        title = str(r.get("key") or p.stem).split("::")[-1]
        out.append(f"'{title[:60]}' {r.get('status') or '-'}, {len(rounds)} Cycle, 최고 {r.get('score') if r.get('score') is not None else '없음'}"
                   + (f", 마지막 다음 명령 '{nxt[:120]}'" if nxt else "") + f", 기록 {p.as_posix()}")
    return out


def explore_material(c: workitem.Cycle, rec: dict, n: int) -> dict:
    """분석 단계가 더 좋은 방법을 찾을 때 읽을 자료(261027-jipsa-03). 기록을 바꾸지 않고 읽기만 한다.
    rounds는 지난 Cycle 전체의 명령과 판정, sheets는 지난 단계 결과지 위치, answers는 단계 결과지에 사람이 넣은 답,
    feedback은 이 목표의 사람 피드백 원문 전체(읽힌 것 포함), tried와 untried는 지난 분석들이 낸 후보 가운데 시도한 것과 아직 안 한 것,
    others는 같은 프로젝트의 다른 Cycle 목표, sources는 로컬 수집 자료 위치다."""
    from scheduler.config import SEARCH_SOURCES

    rounds, sheets, answers, tried_plans = [], [], [], []
    seen = set()
    cands: list[dict] = []
    for r in rec.get("rounds") or []:
        plan = str((r.get("plan") or {}).get("plan") or "")
        tried_plans.append((_norm(plan), str((r.get("plan") or {}).get("key") or "")))
        if r["n"] >= n and not r.get("judge"):
            continue  # 이번 Cycle은 명령만 시도한 것으로 세고 결과는 산출물로만 본다(독립 판정)
        j = r.get("judge") or {}
        score = "없음" if j.get("metric") is None else f"{j['metric']:g}"
        rounds.append(f"Cycle {r['n']} 명령 '{plan[:100]}' 지표 {score} 판정 {j.get('ox') or '-'} "
                      + ("나아짐" if r.get("adopt") else "나아지지 않음") + (f" 결과 {j.get('verdict')}" if j.get("verdict") else ""))
        for k in (RUN, ANALYSIS):
            rid = (r["steps"].get(k) or {}).get("run_id") or ""
            if not rid:
                continue
            if k == ANALYSIS:
                sheets.append(f"Cycle {r['n']} 분석 runs/{rid}/result.md")
            ans = str(_meta(rid).get("answer") or "").strip()
            if ans:
                answers.append(f"Cycle {r['n']} {k} 결과지에 단 답: {ans[:300]}")
        ana = (r["steps"].get(ANALYSIS) or {}).get("run_id") or ""
        blk = _cycle_block(ana) if ana else None
        for rank, x in sorted(_commands(blk).items()) if blk else []:
            text = str(x.get("plan") or "")
            if text and _norm(text) not in seen:
                seen.add(_norm(text))
                cands.append({"n": r["n"], "rank": rank, "plan": text, "key": str(x.get("key") or "")})
        for x in (r.get("explore") or {}).get("candidates") or []:
            text = str(x.get("method") or "")
            if text and _norm(text) not in seen:
                seen.add(_norm(text))
                cands.append({"n": r["n"], "rank": x.get("source") or "후보", "plan": text, "key": "", "ref": x.get("ref") or "",
                              "tried": bool(x.get("tried"))})
    dropped = {str(d.get("key") or "") for a in rec.get("attempts") or [] for d in a.get("dropped") or []} - {""}
    tried, untried = [], []
    for x in cands:
        done = x.get("tried") or any(x["plan"] and _norm(x["plan"]) == p or (x["key"] and x["key"] == k) for p, k in tried_plans)
        line = f"Cycle {x['n']} {x['rank']}: {x['plan'][:140]}" + (f" (출처 {x['ref'][:100]})" if x.get("ref") else "")
        if done:
            tried.append(line)
        elif x["key"] not in dropped:
            untried.append(line)
    return {"rounds": rounds, "sheets": sheets[-EXPLORE_KEEP:], "answers": answers[-EXPLORE_KEEP:],
            "feedback": [e["text"] for e in feedback_entries(c.key)],  # 사람 원문은 자르지 않고 모두 넘긴다
            "tried": tried[-EXPLORE_KEEP:], "untried": untried[-EXPLORE_KEEP:], "others": _other_goals(c),
            "sources": [(label, path.as_posix()) for label, path in SEARCH_SOURCES if path.exists()],
            "reached": rec.get("reached") or None}


def run_branches(rec: dict, n: int) -> dict | None:
    """이행 지시문의 갈래 절. Cycle 1 이행은 갈래 목록을 만들고, 그 뒤 이행은 이번 명령의 갈래와 끝낼 조건만 본다."""
    if not rec.get("branch_v"):
        return None
    if n == 1 and not rec.get("branches"):
        return {"make": True}
    return {"list": branch_view(rec)} if rec.get("branches") else None


def analysis_branches(c: workitem.Cycle, rec: dict, rnd: dict, turn: bool) -> dict | None:
    """분석 지시문의 갈래 절 자료. 목록, 이번 명령의 갈래, 전환 때 피할 갈래, 열린 갈래 수다."""
    if not rec.get("branch_v"):
        return None
    view = branch_view(rec)
    avoid = (rnd.get("pivot") or {}).get("avoid") or recent_branches(rec) if turn else []
    return {"list": view, "this": rnd.get("branch") or "", "first": rnd["n"] == 1, "avoid": avoid,
            "open": sum(1 for b in view if b["status"] == OPEN), "close": BRANCH_CLOSE}


def _analysis_crit(c: workitem.Cycle, rec: dict, rnd: dict) -> str:
    # 방향 전환 절. now는 이번 Cycle이 전환 바퀴, ahead는 이번에도 나아지지 않으면 다음이 전환 바퀴다(판정 전이라 이번 Cycle은 연속 수에 들지 않는다)
    before = no_gain_streak(rec)
    now_pv = rnd.get("pivot") or {}  # 전환 바퀴는 연 때 적은 미개선 Cycle을 쓴다. 판정 전인 이번 Cycle은 넣지 않는다
    pivot = {"now": bool(now_pv), "ahead": pivot_due(c, before + 1), "streak": now_pv.get("streak", before),
             "misses": now_pv.get("misses") or pivot_misses(rec), "best": rec.get("baseline_round")}
    return prompts.cycle_analysis(c, n=rnd["n"], artifacts=artifacts(rnd), attempts=attempt_lines(rec), baseline=rec.get("score"),
                                  feedback=feedback_for(c, rec, ANALYSIS, rnd["n"]), prior=feedback_prior(c, rec, ANALYSIS, rnd["n"]),
                                  explore=explore_material(c, rec, rnd["n"]), pivot=pivot if pivot["now"] or pivot["ahead"] else None,
                                  branches=analysis_branches(c, rec, rnd, pivot["now"] or pivot["ahead"]))


def _redo_analysis(c: workitem.Cycle, rec: dict, rnd: dict, project: Project, why: str) -> None:
    """분석과 피드백을 한 번 다시 시킨다. 앞 분석은 기록에 남긴다."""
    run = rnd["steps"][RUN]
    old = rnd["steps"][ANALYSIS]
    title = f"{c.title} Cycle {rnd['n']} {ANALYSIS} 다시"
    crit = _analysis_crit(c, rec, rnd)
    crit += f" 앞 분석 {old.get('run_id') or ''}은 칸 점검에서 막혔다({why}). 지표 칸, 피드백 칸, 결과 판정을 모두 채운다."
    e = _start(c, rec, project, title, crit, ANALYSIS_MIN, run.get("branch") or rnd.get("start_ref") or "", ANALYSIS, rnd["n"])
    rnd.setdefault("analysis_before", []).append({**old, "why": why})
    rnd["steps"][ANALYSIS] = {"key": e["key"], "status": e["status"], "run_id": e.get("run_id") or "", "redo": True, "explore": True}


# ----- 자동 확인과 종합 보고(261023-jipsa-33) -----
def held_end(rec: dict) -> bool:
    """사람이 마지막 Cycle을 직접 봐야 하는 끝인지. 금지 사항, 환경 실패 상한, 두 순위 모두 버린 가설로 끝난 cycle이다."""
    return rec["status"] == ENDED and str(rec.get("end_reason") or "").startswith(HELD_ENDS)


def passed_runs(rec: dict) -> list[str]:
    """다음 단계로 넘어간 단계의 실행ID. 다시 시켜 밀려난 앞 시도는 늘 넘어간 것이다.
    이행은 같은 Cycle의 분석이 열렸거나 판정이 났으면, 분석은 판정이 났으면 넘어간 것이다. 끝난 cycle은 마지막 Cycle도 넘어간 것으로 본다.
    예외: 사람이 봐야 하는 끝(held_end)의 마지막 Cycle과 범위 밖 플랜으로 확인 필요가 된 실행은 넣지 않는다."""
    rounds = rec["rounds"]
    keep = {h.get("run_id") for h in rec.get("holds") or [] if h.get("run_id")}
    # 사람 확인 없이 박은 목표 정하기 실행(261024-jipsa-13 전 기록)과 다시 시켜 밀려난 앞 시도도 넘어간 것이다. 승인으로 박은 실행은 사람이 이미 봤다
    out: list[str] = [x.get("run_id") for x in rec.get("cards") or [] if x.get("run_id") and not x.get("approved")]
    if (rec.get("setup") or {}).get("first_run") and rec.get("version") == (rec.get("setup") or {}).get("v"):
        out.append(rec["setup"]["first_run"])
    for i, r in enumerate(rounds):
        last = i == len(rounds) - 1
        if last and held_end(rec):
            continue
        over = not last or rec["status"] == ENDED
        st = r["steps"]
        run, ana = st.get(RUN) or {}, st.get(ANALYSIS) or {}
        old = [run.get("first_run"), run.get("handed_from")] + [f.get("run_id") for f in r.get("run_fails") or []]
        old += [a.get("run_id") for a in r.get("analysis_before") or []]
        ids = [x for x in old if x and x != run.get("run_id")]
        if over or ana or r.get("judge"):
            ids.append(run.get("run_id"))
        if over or r.get("judge"):
            ids.append(ana.get("run_id"))
        out += [x for x in ids if x and x not in keep and x not in out]
    return out


def auto_confirm(rec: dict) -> list[str]:
    """넘어간 단계의 실행을 확인 기록에 자동 확인으로 남긴다. 상태 값이 확인 필요인 실행은 두고 사람이 답한다. 새로 확인한 실행ID 목록이다."""
    from scheduler import confirm

    ids = [x for x in passed_runs(rec) if (_meta(x).get("status") in (queue.DONE, queue.FAILED))]
    return confirm.auto(ids, AUTO_WHY) if ids else []


def final_view(rec: dict) -> dict | None:
    """종합 보고 실행의 상태. 화면과 보고가 같은 값을 쓴다. shown은 확인 기록까지 대조한 보이는 상태다."""
    f = rec.get("final")
    if f and f.get("night"):
        from scheduler import night  # Auto 모드에서 끝난 cycle은 Auto 종합 보고 하나를 가리킨다

        rid = night.report_run(f["night"], f.get("since") or "")  # 같은 날 여러 구간이면 끝난 구간의 보고다
        if not rid:
            return {"run_id": "", "status": "대기", "shown": "Auto 종합 보고 대기", "title": night.TITLE, "night": f["night"]}
        f = {**f, "run_id": rid}
    if not f or not f.get("run_id"):
        return None
    from scheduler import confirm

    meta = _meta(f["run_id"])
    status = meta.get("status") or f.get("status") or "진행 중"
    shown = confirm.shown({**meta, "run_id": f["run_id"], "status": status})  # 화면, jipsa status, 보고와 같은 기준 하나다(261025-jipsa-04)
    return {"run_id": f["run_id"], "status": status, "shown": shown, "title": meta.get("title") or f.get("title") or "", "night": f.get("night") or ""}


def advance(c: workitem.Cycle, registry: dict, mode: dict, at: datetime | None = None, actor: str = WORKER) -> bool:
    """cycle 하나를 한 걸음 나아가게 한다. 단계를 열거나 기록이 바뀌면 True다.
    actor는 부른 주체다. 기록의 주체와 다르면 아무것도 하지 않는다(한 cycle에 주체 하나)."""
    at = at or now()
    if c.reject:
        return False  # 거절한 cycle은 기록도 만들지 않는다. 화면과 status가 이유를 보인다
    rec = load(c)
    if owner(rec) != actor:
        return False
    if rec["status"] == ENDED:
        return False  # 끝난 목표의 결과지와 할 일 파일 정리는 auto가 한다. 종합 보고 단계는 261026-jipsa-07에서 뗐다
    if c.marker and rec["status"] == WAITING:
        return False

    def finish(why: str) -> bool:
        _end(c, rec, why, at)
        save(c, rec)
        return True

    def hold(why: str) -> bool:
        changed = rec.get("paused") != why
        rec["paused"] = why
        save(c, rec)
        return changed

    def open_or_pause(plan: dict, source: str) -> bool:
        why = deadline_room(c, mode, at, run_est(c, plan, project))
        if why:
            return hold(why)
        rec.pop("paused", None)
        _open_round(c, rec, project, plan, source, at)
        save(c, rec)
        return True
    project = registry.get(c.project)
    if not project or project.manual_only or c.missing:
        return finish("등록부에 없거나 세션 전용 프로젝트" if not project or project.manual_only else f"칸 비어 있음({', '.join(c.missing)})")
    if not _cur_rounds(rec):
        why = end_reason(c, rec, mode, at)
        if why:
            return finish(why)
        carry = (rec.get("carry") or {}).get("plan") if not rec["rounds"] else None
        if carry:  # 끝난 목표와 같은 줄을 다시 올렸다. 지난 분석의 다음 명령으로 첫 Cycle을 연다(261026-jipsa-03)
            return open_or_pause({**carry, "project": c.project, "est_minutes": carry.get("est_minutes") or c.round_est}, CARRY)
        first = c.first_plan or (PENDING_PLAN if c.pending else FIRST_PLAN)  # 목표 미정이면 지표 후보를 찾는 첫 명령(261026-jipsa-11)
        return open_or_pause({"plan": first + FIRST_BRANCH, "project": c.project, "est_minutes": c.round_est}, FIRST)
    rnd = rec["rounds"][-1]
    if rnd.get("judge") is None:
        # 1단계 명령 이행. 실패하거나 지표 칸이 비면 한 번 다시 시키고, 또 그러면 이행 2번 연속 실패로 끝낸다
        run = rnd["steps"][RUN]
        row = _sync_step(run, at)
        if not row or row["status"] in (queue.PENDING, queue.RUNNING):
            save(c, rec)
            return False
        bad = ""
        if row["status"] in (queue.FAILED, queue.SKIPPED):
            bad = f"이행 {row['status']}"
        elif row["status"] == queue.HOLD:
            rule = str(_meta(row.get("run_id")).get("rule") or "")
            if _FATAL.search(rule) or _PUSH.search(rule):
                return finish(f"이행 확인 필요(Cycle {rnd['n']}, 금지 사항: {rule[:60]})")
            run["hold_passed"] = rule[:120] or "확인 필요"  # 금지 사항이 아닌 확인 필요는 추천안으로 보고 잇는다
        blk = _cycle_block(run.get("run_id") or "")
        if not bad:
            miss = run_missing(blk, c.pending)
            bad = f"이행 결과의 빈 칸 {', '.join(miss)}" if miss else ""
        if bad:
            # 실패 범주를 적는다. 환경과 운영, 측정 오류는 이행 2번 연속 실패에서 빼고 따로 세어 3번까지 다시 시킨다
            cls = fail_class(blk, row)
            rnd.setdefault("run_fails", []).append({"class": cls, "why": bad, "run_id": run.get("run_id") or "",
                                                     "fail_why": str((blk or {}).get("fail_why") or "")[:120]})
            fails = rnd["run_fails"]
            counted = [f for f in fails if f["class"] not in UNCOUNTED]
            apart = len(fails) - len(counted)
            if len(counted) >= c.fail_limit or apart > ENV_RETRY:
                # 다시 시켜도 실패했다. 목표를 끝내지 않고 이 Cycle을 실패로 판정한 뒤 같은 명령으로 다음 Cycle을 연다(261026-jipsa-03)
                gave = f"이행 {len(fails)}번 실패(Cycle {rnd['n']}, {cls}, {bad})"
                judge(c, rec, rnd, None, at, failed=gave)
                rnd["fail_class"] = rnd["judge"]["fail_class"] = cls if cls in FAIL_CLASSES else ""
                rnd["run_gave_up"] = gave
                why = end_reason(c, rec, mode, at)
                if why:
                    return finish(why)
                return open_or_pause(rnd["next"]["plan"], rnd["next"]["chosen"])
            _redo_run(c, rec, rnd, project, f"{bad}, 범주 {cls}")
            save(c, rec)
            return True
        if rec.get("branch_v") and rnd["n"] == 1 and not rec.get("branches"):
            # Cycle 1 이행이 만든 갈래 목록. 모자라면 버리고 Cycle 1 분석이 만든다(261029-jipsa-10 1안)
            rows = branch_list((blk or {}).get("branches"))
            if rows:
                set_branches(rec, rows, 1, RUN)
                rnd["branch"] = str((blk or {}).get("branch") or "").strip() if _branch(rec, (blk or {}).get("branch")) else ""
        # 2단계 분석과 피드백. 이행의 대화와 주장은 넘기지 않는다(독립 판정)
        ana = rnd["steps"].get(ANALYSIS)
        if not ana:
            why = deadline_room(c, mode, at, ANALYSIS_MIN)
            if why:
                return hold(why)  # 이행 결과는 그대로 두고 다시 시키면 이 분석부터 잇는다
            rec.pop("paused", None)
            title = f"{c.title} Cycle {rnd['n']} {ANALYSIS}"
            crit = _analysis_crit(c, rec, rnd)
            e = _start(c, rec, project, title, crit, ANALYSIS_MIN,run.get("branch") or rnd.get("start_ref") or "", ANALYSIS, rnd["n"])
            rnd["steps"][ANALYSIS] = {"key": e["key"], "status": e["status"], "run_id": e.get("run_id") or "", "explore": True}
            save(c, rec)
            return True
        arow = _sync_step(ana, at)
        if not arow or arow["status"] in (queue.PENDING, queue.RUNNING):
            save(c, rec)
            return False
        if c.pending and arow["status"] == queue.HOLD:
            # 목표 미정 Cycle에서 분석이 잴 수단을 찾지 못해 확인 필요로 멈췄다. 목표 없이는 판정할 수 없어 끝내고 사람이 본다(261026-jipsa-11)
            rule = str(_meta(arow.get("run_id")).get("rule") or _meta(arow.get("run_id")).get("reason") or "분석이 목표를 정하지 못함")
            rule = re.sub(r"^Cycle 목표 미정\s*[:：]\s*", "", rule)
            return finish(f"{GOAL_HOLD}, Cycle {rnd['n']} 분석: {rule[:80]})")
        block = _cycle_block(ana.get("run_id") or "") if arow["status"] == queue.DONE else None
        bad = f"분석 {arow['status']}" if arow["status"] != queue.DONE else ""
        if not bad:
            miss = analysis_missing(block, c.pending, explore=bool(ana.get("explore")),
                                    branches=bool(rec.get("branch_v")) and rnd["n"] == 1 and not rec.get("branches"),
                                    names=[b["name"] for b in rec.get("branches") or []])
            bad = f"분석 결과의 빈 칸 {', '.join(miss)}" if miss else ""
        if bad and not ana.get("redo"):
            why = deadline_room(c, mode, at, ANALYSIS_MIN)
            if why:
                return hold(why)
            rec.pop("paused", None)
            _redo_analysis(c, rec, rnd, project, bad)
            save(c, rec)
            return True
        if c.pending:
            # 목표 미정 Cycle. 분석이 정한 목표를 할 일 줄에 적고 그 값으로 판정한다. 두 번 막혔으면 판정할 목표가 없어 끝낸다
            why = bad or set_goal(c, rec, rnd, block or {}, at)
            if why:
                return finish(f"{GOAL_HOLD}, Cycle {rnd['n']} 분석이 목표를 정하지 못함: {why[:80]})")
        # 3단계 목표 판정. 분석이 두 번 막혔으면 그 Cycle을 실패로 센다
        judge(c, rec, rnd, None if bad else block, at, failed=bad)
        goes_on = rnd["judge"]["ox"] == "X" or not getattr(c, "stop_on_reach", True)
        if goes_on and not rnd["next"]["plan"] and not rnd["judge"]["forbidden"]:
            # 두 순위가 모두 버린 가설이거나 비었다. 끝내지 않고 기본 명령으로 다음 Cycle을 연다(261026-jipsa-03)
            rnd["next"]["plan"] = {"plan": FALLBACK_PLAN, "project": c.project}
            rnd["next"]["chosen"] = FALLBACK
            rnd["judge"]["next"], rnd["judge"]["next_rank"] = FALLBACK_PLAN, FALLBACK
    why = end_reason(c, rec, mode, at)
    if why:
        return finish(why)
    return open_or_pause(rnd["next"]["plan"], rnd["next"]["chosen"])


# ----- 화면과 보고 -----
def _state(r: dict) -> str:
    steps = r["steps"]
    live = [k for k in (RUN, ANALYSIS) if k in steps and steps[k].get("status") in (queue.PENDING, queue.RUNNING)]
    return f"{live[0]} 중" if live else ("판정 " + r["judge"]["ox"] if r.get("judge") else "판정 없음")


def summary(c: workitem.Cycle, rec: dict, mode: dict, at: datetime | None = None) -> dict:
    """범위 패널의 cycle 카드와 보고가 쓰는 값. 거절한 cycle은 상태가 거절이고 reject에 이유가 든다.
    conds.rounds의 둘째 값은 Cycle 수 상한 자리이고 늘 None이다(상한 없음)."""
    at = at or now()
    if c.reject:
        return {"key": c.key, "project": c.project, "title": c.title, "status": REJECTED, "phase": REJECTED, "reject": c.reject, "pending": "",
                "end_reason": c.reject, "metric": c.metric, "target": c.target, "direction": c.direction, "base": None, "score": None,
                "rounds": [], "next": None, "holds": [], "violations": 0, "paused": "",
                "conds": {"rounds": [0, None], "no_gain": [0, c.no_gain_limit], "goal": [None, c.target],
                          "deadline": c.no_new_after or "", "deadline_left": None},
                "report_date": None, "record": ""}
    rounds = []
    for r in rec["rounds"]:
        steps = r["steps"]
        j = r.get("judge") or {}
        rounds.append({"n": r["n"], "plan": r["plan"].get("plan", ""), "source": r["source"], "delta": r.get("delta"),
                       "low": r.get("low"), "high": r.get("high"), "score": r.get("score"), "adopt": r.get("adopt"),
                       "state": _state(r), "judge": j.get("ox") or "", "next_text": j.get("next") or "",
                       "feedback": r.get("feedback") or {},
                       "retry": bool(steps.get(RUN, {}).get("retry")), "pivot": bool(r.get("pivot")), "branch": r.get("branch") or "",
                       "providers": {k: s.get("provider", "") for k, s in steps.items()},
                       "minutes": sum(int(s.get("minutes") or 0) for s in steps.values()),
                       # Cycle의 실행. 대시보드 타임라인이 목표 줄 아래 Cycle 줄로 묶는다(261023-jipsa-11)
                       "runs": {k: s.get("run_id") for k, s in steps.items() if s.get("run_id")}})
    last = next((r for r in reversed(rec["rounds"]) if r.get("next") is not None), None)
    nxt = None
    if last:
        n = last["next"]
        nxt = {"round": last["n"], "chosen": n["chosen"], "plan": (n["plan"] or {}).get("plan", ""),
               "checks": {k: v for k, v in (n.get("checks") or {}).items()}}
    dl = _deadline(c, mode)
    phase = rec["status"]
    sv = setup_view(rec)
    if rec["status"] == LIVE and rounds:
        phase = f"Cycle {rounds[-1]['n']} {rounds[-1]['state']}"
    if rec["status"] != ENDED and sv and sv["state"] != "박음":
        phase = f"{SETUP} v{sv['drafting'] or int(sv['version'] or 0) + 1} {sv['state']}"
    if rec["status"] != ENDED and rec.get("paused") and not (rounds and rounds[-1]["state"].endswith("중")):
        phase = "새 Cycle 멈춤"
    return {
        "key": c.key, "project": c.project, "title": c.title, "status": rec["status"], "phase": phase, "reject": "",
        "end_reason": rec.get("end_reason", ""), "base": rec.get("base"), "score": rec.get("score"), "target": c.target,
        "metric": c.metric, "direction": c.direction, "paused": rec.get("paused", "") if rec["status"] != ENDED else "",
        "rounds": rounds, "next": nxt, "holds": rec.get("holds", []), "violations": rec.get("violations", 0),
        "conds": {"rounds": [len(rec["rounds"]), None], "no_gain": [no_gain_streak(rec), c.no_gain_limit],
                  "goal": [rec.get("score"), c.target],
                  "deadline": c.no_new_after or "", "deadline_left": int((dl - at).total_seconds() // 60) if dl else None},
        "report_date": rec.get("report_date"), "record": record_path(c).name,
        "owner": owner(rec), "handed": rec.get("handed_why", ""), "reclaim": bool(rec.get("reclaim")),
        "final": final_view(rec), "where": where_text(rec),
        # 옛 목표 정하기 단계(261023-jipsa-40)의 기록. 옛 지시 목표만 값이 있다. 대시보드는 이 값을 읽기만 한다
        "setup": sv, "version": rec.get("version") or 0, "checks": len(c.checks), "human": len(c.human),
        # 목표 미정 Cycle(261026-jipsa-11). pending은 비운 칸 이름, goal_set은 분석이 정해 줄에 적은 cycle 칸 글이다
        "pending": ", ".join(c.pending), "goal_set": (rec.get("goal_set") or {}).get("text") or "",
        "branches": branch_view(rec),  # 아이디어 갈래 줄(261029-jipsa-10 1안). 옛 기록은 빈 목록이다
        **goal_view(c.direction, rec),
    }


def where_text(rec: dict) -> str:
    """목표 줄 머리의 지금 위치 한 마디. 예: "Cycle 3, 분석과 피드백 중", "끝: 목표 도달, 종합 보고 확인 필요"."""
    if rec["status"] == ENDED:
        reason = str(rec.get("end_reason") or "사유 없음")
        why = "환경 실패 상한" if reason.startswith(HOLD_END) else re.split(r"[(]", reason)[0].strip()
        if rec.get("score") is not None:
            why += f"({rec['score']:g})" if reason.startswith("목표 도달") else f"(최고 {rec['score']:g})"
        f = final_view(rec)
        tail = "종합 보고 대기" if not f else (f"Auto 종합 보고 {f['shown'] if f['run_id'] else '대기'}") if f.get("night") else {"진행 중": "종합 보고 중", "확인 필요": "종합 보고 확인 필요", "확인함": "종합 보고 확인함",
                                                 "실패": "종합 보고 실패"}.get(f["shown"], f"종합 보고 {f['shown']}")
        return f"끝: {why}, {tail}"
    sv = setup_view(rec)
    if sv and sv["state"] != "박음":
        return f"{SETUP} v{sv['drafting'] or int(sv['version'] or 0) + 1} {sv['state']}" + (f"({sv['hold'][:60]})" if sv["hold"] else "")
    if not rec["rounds"]:
        return "대기"
    r = rec["rounds"][-1]
    live = [k for k in (RUN, ANALYSIS) if (r["steps"].get(k) or {}).get("status") in (queue.PENDING, queue.RUNNING)]
    if live:
        return f"Cycle {r['n']}, {live[0]} 중"
    if rec.get("paused"):
        return f"Cycle {r['n']} 뒤 새 Cycle 멈춤"
    if r.get("judge"):
        return f"Cycle {r['n']}, 판정 {r['judge']['ox']}"
    return f"Cycle {r['n']}, 다음 단계 대기"


def goal_view(direction: str, rec: dict) -> dict:
    """목표 한 줄의 값. 처음 기록, 최고 기록, 상태 글자, 주체 글자, 주체 이동이다. 대시보드 목표 줄과 아침 보고가 같은 값을 쓴다."""
    scores = [r["score"] for r in rec["rounds"] if r.get("score") is not None]
    first = rec.get("base") if rec.get("base") is not None else (scores[0] if scores else None)
    pool = scores + ([first] if first is not None else [])
    best = rec.get("score") if rec.get("score") is not None else ((min if direction == "이하" else max)(pool) if pool else None)
    if rec["status"] == ENDED:
        state = f"끝남({rec.get('end_reason') or '사유 없음'})"
    elif rec.get("paused") and not any(s.get("status") in (queue.PENDING, queue.RUNNING) for r in rec["rounds"][-1:] for s in r["steps"].values()):
        state = "창 멈춤"
    else:
        state = "진행"
    moves = []
    for t in rec.get("takeovers") or []:
        if t.get("handover_at"):
            moves.append(f"{t['handover_at'][11:16]} Main에서 작업자로({t.get('why', '')})")
        elif t.get("back"):
            moves.append(f"{t['back'][11:16]} Main 이어 부르기 뒤 복귀")
    if rec.get("handed_at") and not any(t.get("handover_at") for t in rec.get("takeovers") or []):
        moves.append(f"{rec['handed_at'][11:16]} Main에서 작업자로({rec.get('handed_why', '')})")
    return {"first": first, "best": best, "state_text": state, "moves": moves,
            "owner_text": "Main" if owner(rec) == MAIN else "작업자"}


def goal_line(rec: dict, direction: str = "이상") -> str:
    """아침 보고의 목표 한 줄. Cycle 수, 처음과 최고, 목표값, 끝난 사유, 주체 이동, 사람이 확인할 것이다."""
    v = goal_view(direction, rec)
    fmt = lambda x: "-" if x is None else f"{x:g}"  # noqa: E731
    target = f", 목표 {rec['target']:g} {direction}" if rec.get("target") is not None else ""
    check = [f"범위 밖 플랜 {len(rec['holds'])}건"] if rec.get("holds") else []
    f = final_view(rec)
    if rec["status"] == ENDED:
        # 끝난 cycle은 종합 보고 실행 하나를 가리킨다(261023-jipsa-33). 열리기 전이면 대기로 적는다
        check.append((f"Auto 종합 보고 {f['run_id'] or '대기'}" if f and f.get("night") else f"종합 보고 {f['run_id']} {f['shown']}") if f else "종합 보고 대기")
    if str(rec.get("end_reason", "")).startswith(("다음 명령이 금지 사항", "다음 명령 1순위와 차순위가 모두 버린 가설", HOLD_END)):
        check.append(rec["end_reason"])
    if (rec.get("hold") or {}).get("why"):
        check.append(f"목표 정하기 확인 필요({rec['hold']['why'][:60]}) {rec['hold'].get('run_id', '')}")
    human = len((rec.get("card") or {}).get("human") or [])
    if human and rec["status"] == ENDED and str(rec.get("end_reason", "")).startswith("목표 도달"):
        check.append(f"사람 확인 {human}개")
    ver = f" | 목표 판 v{rec['version']}" if rec.get("version") else ""
    return (f"- 목표 {rec['project']} | {rec['title']}{ver} | Cycle {len(rec['rounds'])}번, 처음 {fmt(v['first'])}, 최고 {fmt(v['best'])}{target} | "
            f"{v['state_text']} | 주체 {v['owner_text']}" + (f", 이동 {'; '.join(v['moves'])}" if v["moves"] else ", 이동 없음")
            + f" | 사람 확인: {', '.join(check) if check else '없음'}")


def _records_for(date: str) -> list[dict]:
    out = []
    for p in sorted(CYCLE_DIR.glob("*.json")) if CYCLE_DIR.exists() else []:
        try:
            rec = _upgrade(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if rec.get("report_date") == date and (rec.get("rounds") or rec.get("setup")):
            out.append(rec)
    return out


def _cycle_line(r: dict) -> str:
    """아침 보고의 Cycle 한 줄. 명령, 지표, 판정, 피드백 요지다."""
    j = r.get("judge")
    head = f"Cycle {r['n']}: {r['plan'].get('plan', '')[:60]}"
    if not j:
        return f"{head} | {_state(r)}"
    score = "지표 없음" if j.get("metric") is None else f"지표 {j['metric']:g}" + (f"(차 {r['delta']:+g})" if r.get("delta") is not None else "")
    fb = r.get("feedback") or {}
    gist = j.get("failed") or "; ".join(x for x in (fb.get("good"), fb.get("lack")) if x)[:80] or "피드백 없음"
    fails = r.get("run_fails") or []
    retry = f", 이행 다시 {len(fails)}번({', '.join(f['class'] for f in fails)})" if fails else (", 이행 다시" if r["steps"].get(RUN, {}).get("retry") else "")
    if j.get("mismatch"):
        score += f", 이행이 적은 값 {j['run_metric']:g}"
    extra = "".join(f", {x}" for x in (j.get("verdict"), j.get("fail_class")) if x)
    return f"{head} | {score}, 판정 {j['ox']}, {'나아짐' if r.get('adopt') else '나아지지 않음'}{extra}{retry} | {gist}"


def _trend(rec: dict) -> str:
    bits = []
    for r in rec["rounds"]:
        j = r.get("judge")
        if not j:
            bits.append(f"Cycle {r['n']} {_state(r)}")
            continue
        score = "-" if j.get("metric") is None else f"{j['metric']:g}"
        bits.append(f"Cycle {r['n']} {score} {j['ox']}")
    return ", ".join(bits)


def report_lines(date: str) -> tuple[list[str], list[str]]:
    """아침 보고의 cycle 묶음. (전문 줄, Slack 줄). 목표마다 한 줄을 두고 그 아래 Cycle마다 명령, 지표, 판정, 피드백 요지를 한 줄씩 둔다."""
    full, slack = [], []
    for rec in _records_for(date):
        n = len(rec["rounds"])
        target = f" (목표 {rec['target']:g})" if rec.get("target") is not None else ""
        direction = next((r["judge"].get("direction") for r in reversed(rec["rounds"]) if (r.get("judge") or {}).get("direction")), "") or "이상"
        full.append(goal_line(rec, direction))  # 목표마다 한 줄(261023-jipsa-11). 아래 줄은 Cycle별 내역이다
        full.append(f"  - Cycle {n}번, {'끝(' + rec['end_reason'] + ')' if rec['status'] == ENDED else '진행 중'} | {used_minutes(rec)}분")
        for x in (setup_view(rec) or {}).get("versions") or []:
            full.append(f"  - 목표 판 v{x['v']} 박음 {str(x['at'])[11:16]}({x['why']}) {x['run_id']}")
        sv = setup_view(rec)
        if sv and sv["state"] != "박음":
            full.append(f"  - {SETUP}: {sv['state']}" + (f", {sv['hold']}" if sv["hold"] else "") + (f", 다시 정하는 이유 {sv['resetup']}" if sv["resetup"] else ""))
        full += [f"  - {_cycle_line(r)}" for r in rec["rounds"]]
        full += [f"  - {x}" for x in feedback_lines(rec)]
        last = next((r for r in reversed(rec["rounds"]) if r.get("judge")), None)
        if last and rec["status"] != ENDED and last["judge"].get("next"):
            full.append(f"  - 다음 명령(Cycle {last['n']} 피드백 {last['judge']['next_rank']}): {last['judge']['next']}")
        for h in rec.get("holds", []):
            full.append(f"  - 확인 필요: Cycle {h['round']} {h['rank']} 플랜 범위 밖({'; '.join(h['why'])}) {h['run_id']}")
        fin = final_view(rec)
        if rec["status"] == ENDED:
            full.append(f"  - 종합 보고: {fin['run_id']} {fin['shown']}" if fin else "  - 종합 보고: 대기(cycle next나 스케줄러가 연다)")
        v = goal_view(direction, rec)
        fmt = lambda x: "-" if x is None else f"{x:g}"  # noqa: E731
        brief_goal = f"Cycle {n}번, 처음 {fmt(v['first'])} 최고 {fmt(v['best'])}{target}, {v['state_text']}, 주체 {v['owner_text']}"
        slack += ["", f"↻ *{rec['project']}* | {rec['title']} 목표",
                  f"목표: {report._shorten(brief_goal, 80)}",
                  f"추이: {report._shorten(_trend(rec), 80)}",
                  f"피드백: {report._shorten(' | '.join(feedback_lines(rec)), 80)}"]
        if last and rec["status"] != ENDED and last["judge"].get("next"):
            slack.append(f"다음 명령: {report._shorten(last['judge']['next'], 60)}")
        if rec.get("holds"):
            slack.append(f"정할 것: 범위 밖 플랜 확인 필요 {len(rec['holds'])}건")
        if (rec.get("hold") or {}).get("why"):
            slack.append(f"정할 것: 목표 정하기 확인 필요({report._shorten(rec['hold']['why'], 50)})")
        if rec["status"] == ENDED:
            slack.append(f"종합 보고: {fin['run_id']} {fin['shown']}" if fin else "종합 보고: 대기")
        if rec.get("handed_at"):
            slack.append(f"주체: {rec['handed_at'][11:16]} Main 끊김으로 작업자 경로로 넘김")
    return full, slack
