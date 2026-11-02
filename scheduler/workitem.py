"""작업 항목과 Cycle 목표의 형식, 작업 종류 추정 규칙.

옛 주간 계획 파일(planner/<주>.md)을 읽고 쓰던 모듈에서 파일 읽기, 쓰기, 표시 함수를 떼고 형식만 남겼다(261025-jipsa-42, 계획 파일 떼기).
할 일 파일은 scheduler/todo.py가 읽는다. Item은 큐 줄 하나의 바탕(queue.add)이고, Cycle은 할 일 줄 cycle 칸을 옛 Cycle 한 바퀴가
읽는 목표로 바꾼 값(auto.as_cycle)이다. 층 이름(필수, 확장, 예비)은 옛 큐 줄과 Cycle 단계 줄의 tier 칸 값으로 남는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED, EXTENSION, RESERVE = "필수", "확장", "예비"
TIERS = (REQUIRED, EXTENSION, RESERVE)
CATEGORIES = ("구현", "글쓰기", "조사", "기획", "실험")
PICK, GUESS = "고를 것", "추정"
# 낱말 규칙. 위에서부터 처음 걸리는 종류다. 지난 128건에서 고른 낱말이고 세션의 값을 돕는 보조다
_RULES = (
    ("구현", ("수집", "구현", "수정", "고치기", "바로잡기", "바꾸기", "단추", "버튼")),
    ("글쓰기", ("초안", "블로그", "기획서")),
    ("기획", ("시안", "제안", "설계", "기획안", "추천", "정의", "선정", "방향")),
    ("실험", ("측정", "재현", "전략 적용", "실험", "대국")),
    ("조사", ("조사", "찾기", "검토", "분석", "원인", "비교", "점검")),
    ("글쓰기", ("문서", "글", "안내", "피드백", "보고서", "규칙", "절차", "정리")),
    ("구현", ("반영", "표시", "추가", "제거", "해결", "적용", "켜기", "숨김", "지원", "보기", "등록", "이전", "옮기기",
              "이동", "만들기", "고침", "연결")),
)
_PICK = re.compile(r"제안|추천(?!\s*\d)|시안|고르|선정|검토|찾기|방향")  # `추천 30 이상`처럼 수가 붙은 추천은 글 고르는 조건이다


@dataclass
class Item:
    project: str
    title: str
    criteria: str
    est_minutes: int | None
    file: Path
    line: int  # 항목 줄의 0부터 세는 번호
    marker: str | None  # "(완료 251022-example_app-01)" 같은 표시
    checked: bool
    tier: str = REQUIRED  # 큐 줄의 층 칸. 옛 범위 절의 필수, 예비 줄과 Cycle 단계 줄(cycle)의 값이다
    category: str = ""  # 작업 종류. 비면 분류 줄이 없는 항목이다
    pick: bool = False  # 사람이 고를 것이 남는 제안형
    guessed: bool = False  # 낱말 규칙으로 추정한 값

    @property
    def key(self) -> str:
        return f"{self.project}::{self.title}"


def guess_category(title: str, criteria: str = "") -> tuple[str, bool]:
    """제목의 낱말 규칙으로 (종류, 고를 것)을 추정한다. 제목에 걸리는 낱말이 없으면 기준을 보고, 그래도 없으면 가장 흔한 구현이다."""
    for text in (title, criteria):
        for cat, words in _RULES:
            if any(w in text for w in words):
                return cat, cat == "기획" or bool(_PICK.search(title))
    return "구현", bool(_PICK.search(title))


def category_text(category: str, pick: bool = False, guessed: bool = False) -> str:
    """분류 줄의 값. `기획, 고를 것, 추정` 꼴이다."""
    return ", ".join([category] + ([PICK] if pick else []) + ([GUESS] if guessed else []))


def category_of(item: Item) -> tuple[str, bool, bool]:
    """(종류, 고를 것, 추정). 분류 줄이 없으면 낱말 규칙으로 추정한 값이다."""
    if item.category:
        return item.category, item.pick, item.guessed
    cat, pick = guess_category(item.title, item.criteria)
    return cat, pick, True


@dataclass
class Cycle:
    """`## cycle` 절의 항목 하나. 사람이 적은 목표, 수치 지표, 목표값, 종료 시각과 선택 칸이다. 다음 플랜은 분석이 쓰고 jipsa가 이 칸에 대조한다."""
    project: str
    title: str
    file: Path
    line: int
    marker: str | None
    checked: bool
    goal: str = ""
    metric: str = ""
    success: str = ""
    judge: str = ""  # 판정 칸. 대리 지표나 사람 확인이면 거절한다
    round_text: str = ""  # 옛 바퀴 줄. 읽기만 하고 쓰지 않는다
    first_plan: str = ""
    measure: str = ""  # 측정 명령. 적었으면 jipsa가 판정 앞에 이행 작업 폴더에서 직접 재고 출력의 마지막 수를 지표로 쓴다
    end_text: str = ""
    round_est: int | None = None  # Cycle 예상(분). 줄 칸 이름은 옛 이름 `바퀴 예상`이다
    round_cap: int | None = None  # Cycle 한 단계에 지시문으로 주는 시간(분). 없으면 Cycle 예상
    priority: int | None = None
    no_gain_limit: int = 5  # 0이면 상한 없음(Auto 목록 줄에 상한을 적지 않았을 때, 261026-jipsa-03)
    fail_limit: int = 2  # 이행 실패가 이 횟수면 그 Cycle을 실패로 판정하고 다음 Cycle로 넘긴다(261026-jipsa-03 전에는 끝냈다)
    stop_on_reach: bool = True  # 목표 도달이면 끝낸다. Auto 목록 줄은 cycle 칸 끝에 "도달하면 끝"을 적었을 때만 참이다
    base: float | None = None
    target: float | None = None
    direction: str = "이상"  # 목표값 방향. 이상이면 점수가 목표값 이상일 때, 이하면 이하일 때 도달이다
    no_new_after: str | None = None  # 종료 시각(HH:MM). 선택 칸이다. 적었으면 이 시각 뒤에는 새 Cycle을 열지 않는다
    allowed_projects: list[str] = field(default_factory=list)
    allowed_dirs: list[str] = field(default_factory=list)  # 비어 있으면 저장소 전체에서 금지 경로만 뺀다
    risks: list[str] = field(default_factory=lambda: ["낮음", "중간"])
    deps_allowed: bool = False
    gpu_min: int | None = None  # Cycle당 GPU 분. None이면 적지 않음, 0이면 쓰지 않음
    caps: dict = field(default_factory=dict)  # 기타 상한. `대국 상한: 바퀴당 200판`이면 {"대국": 200}
    lines: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)  # 박은 목표 카드의 기계 체크 항목. cycle.load가 카드에서 채운다
    human: list[dict] = field(default_factory=list)  # 박은 카드의 사람 확인 항목. 판정에 쓰지 않는다
    version: int = 0  # 박은 카드의 판 번호. 0이면 사람이 적은 수치 목표다
    origin: str = ""  # "todo"면 할 일 파일 Auto 절의 Cycle 목표 줄이다(scheduler/auto.py, 261025-jipsa-24). 주간 파일에 줄이 없다
    entry_extra: dict = field(default_factory=dict)  # 단계 큐 줄에 더할 칸. Auto 목표는 source todo와 todo_key를 넣어 Auto 한 줄로 센다
    pending: list[str] = field(default_factory=list)  # 목표 미정 칸(지표, 목표값). 비어 있지 않으면 Cycle 분석이 정한다(261026-jipsa-11)

    @property
    def key(self) -> str:
        return f"{self.project}::{self.title}"

    @property
    def reject(self) -> str:
        """cycle로 받지 않는 이유. 받으면 빈 문자열이다. 수치 지표와 목표값이 있어야 jipsa가 Cycle마다 도달을 기계로 판정한다. 종료 시각은 보지 않는다.
        지시 한 줄만 적은 목표(목표 정하기 단계)는 261026-jipsa-07에서 뗐다.
        목표 미정 Cycle(pending)은 지표와 목표값이 비어도 받는다. 분석이 정한 뒤에 같은 규칙으로 본다(261026-jipsa-11)."""
        if re.search(r"대리|사람|주관", self.judge):
            return f"판정 '{self.judge}'는 대리 지표나 사람 확인이라 cycle로 받지 않는다. 수치 지표와 목표값을 적는다"
        if re.search(r"대리 지표|사람이|사람 확인|주관", self.metric):
            return f"지표 '{self.metric}'는 대리 지표나 사람 확인이라 cycle로 받지 않는다. 수치 지표와 목표값을 적는다"
        if not self.metric and "지표" not in self.pending:
            return "수치 지표가 없다. cycle은 수치 지표와 목표값이 있어야 받는다"
        if self.target is None and "목표값" not in self.pending:
            return "목표값이 없다. 수치 지표의 목표값과 방향(이상, 이하)을 적어야 받는다"
        return ""

    @property
    def missing(self) -> list[str]:
        """돌리는 데 꼭 필요한데 비어 있는 칸. 첫 플랜과 허용 폴더는 기본값이 있어 빼었다."""
        return [] if self.goal else ["목표"]


_DOWN = re.compile(r"이하|이내|아래|줄이|낮추|감소|미만")


def _target(c: Cycle, val: str) -> None:
    """`240 이상`, `0.05 이하`, `200점에서 240점` 꼴에서 목표값과 방향을 읽는다. 둘째 수가 있으면 첫 수가 시작 점수다."""
    pts = [float(x) for x in re.findall(r"(-?\d+(?:\.\d+)?)\s*점", val)] or [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", val)]
    if len(pts) >= 2:
        c.base, c.target = pts[0], pts[-1]
    elif pts:
        c.target = pts[0]
    if _DOWN.search(val):
        c.direction = "이하"
