"""작업자, 판정, 분석자, 서칭 프롬프트. 규칙을 글로 옮긴다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scheduler.config import LOCAL_RULES_FILE, POLICIES, RECOMMEND_FILE, ROOT
from scheduler.registry import Project

REPORT_FILE = POLICIES / "report.md"  # 보고서 규격
# begin, cycle next, 작업자 프롬프트가 같이 쓰는 보고서 안내. 처음 읽는 사람이 1분 안에 이해하게 쓰고 억지 그림을 금한다(261024-jipsa-06)
REPORT_GUIDE = [
    "보고서 맨 위(제목 바로 아래)는 요약 상자 세 줄이다. 한 일, 결과(좋아졌다, 나빠졌다, 그대로다와 기준을 붙인 핵심 수치), 사람이 할 일(없으면 없다)이다. 결과가 앞이고 과정은 뒤다.",
    "내부 이름(체크 번호, 단계 이름, 설정 이름, 측정 용어)은 쓰지 않거나 처음 나올 때 쉬운 말로 푼다. 풀 때도 코드 식별자, 설정 이름, 모델 이름, seed나 LoRA나 epoch처럼 분야에서 영어 그대로 쓰는 고유 명칭은 번역하지 않고 원어로 쓴다(씨앗이 아니라 seed). 숫자는 기준, 판정(통과, 미달), 뜻을 같이 쓰고 표는 판단에 쓰는 것만 둔다.",
    "그림은 질문 하나에 답하는 것만 그리고 그림 위 한 문장에 그 답을 쓴다. 값이 0과 1뿐인 막대, 표를 옮긴 그림, 시험한 경우를 늘어놓은 그림은 그리지 않는다. 의미 있는 그래프가 없으면 결과물 화면이나 상태 도식 한 장으로 대신하고, 그것도 뜻이 없으면 그림 없이 도입에 이유를 한 문장으로 적는다.",
    "그림은 수치 그래프, 상태나 구조 도식, 결과물 화면, 사진만이다. 문서, 표, 코드, 로그를 찍은 그림은 금지이고 본문과 표에 파일 이름, 경로, 함수 이름을 쓰지 않는다.",
]
# 마감 전 Sol 공격 안내(261024-jipsa-11). begin, cycle next, 작업자 첫 지시문에 같은 한 줄이 들어간다
ATTACK_NOTE = "마감 전 Sol 공격을 받으면 지적마다 답하고 보고서를 고친다. 답은 반영, 반박, 사람 가운데 하나이고 시도 폴더의 attack_reply.json에 쓴다. 공방은 한 번이다."
# result.json 쓰는 법. 셸로 쓰면 Windows 경로의 역슬래시가 줄어 JSON이 깨지고 마감이 실패로 적는다
RESULT_WRITE = "result.json은 셸 heredoc이나 echo로 쓰지 말고 파이썬 json.dump로 쓴다. 안의 Windows 경로는 슬래시(<드라이브>:/work/...)로 적는다. 쓴 뒤 다시 읽어 status를 확인한다."
# 단계 기록 꼴(261029-jipsa-47). 현황판 카드가 계획의 번호 목록과 진행 메모의 단계 시각 줄로 끝난 단계, 지금 단계, 다음 단계를 보인다
STEP_NOTE = ("계획 파일 plan.md의 단계는 '1. 단계 이름(열다섯 자 안팎). 설명' 꼴 번호 목록으로 쓴다. "
             "progress.md에는 단계를 시작할 때와 끝낼 때마다 '- HH:MM N단계 시작', '- HH:MM N단계 끝' 줄을 더한다(N은 계획의 번호).")

WORDING_FILE = POLICIES / "wording.md"  # 낱말 고르기 규칙(261029-jipsa-05, 261029-jipsa-02 1안). 고유 명칭 번역 금지는 261031-jipsa-07


def local_rules() -> list[str]:
    """프로젝트 전용 규칙 절. 파일이 있으면 제목과 본문 두 줄이고, 없거나 비었거나 못 읽으면 빈 목록이다(공개판은 파일이 없다)."""
    try:
        body = LOCAL_RULES_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return []
    return ["## 프로젝트 전용 규칙", body] if body else []


def wording_note() -> str:
    """문체 줄에 붙이는 낱말 규칙 한 줄. 예시 대응은 정책 문서 표에서 읽는다."""
    from scheduler import wording

    pairs = wording.prompt_words(5)
    return (f"낱말은 {WORDING_FILE.as_posix()}(낱말 고르기 규칙)를 따른다. 코드 식별자, 설정 이름, 명령 옵션, 모델 이름, seed나 LoRA나 epoch처럼 분야에서 영어 그대로 쓰는 "
            "고유 명칭은 번역하지 않고 원어(또는 널리 쓰는 외래어 표기)로 쓰며, 영어를 낱말 단위로 옮긴 새 말을 만들지 않고 표의 바꿀 말을 쓴다"
            + (f"({pairs})" if pairs else "") + ". 보고서만이 아니라 제목, 완료 기준, 선택지(options) 문장도 같다. 마감 때 검사가 남은 낱말을 결과지 주의 줄로 남긴다.")


# 무거운 프로세스 동시 실행 상한(261028-jipsa-04). 작업 안에서 여러 개를 겹쳐 띄워 RAM이 찬 사고를 막는다(261028-jipsa-03 1안, RAM 여유 문턱은 4GB)
CONCURRENCY_NOTE = "무거운 프로세스(학습, 전처리, 합성, 모델 서버, 대형 압축)는 동시에 2개까지 띄우고 병렬 수(num_processes, workers 등)는 2 이하로 한다. 띄우기 전마다 RAM 여유를 재고 4GB 미만이면 앞 프로세스가 끝날 때까지 기다린다(2026-10-28 사용자 승인, 261028-jipsa-03 1안)."

# 큰 GPU 일 신호(261029-jipsa-07, 261029-jipsa-04 2안). 시작 뒤 관찰 시간이 지나면 GPU 예약을 실측 + 1GB로 세므로, 갑자기 커지는 일은 미리 알린다
GPU_SIGNAL_NOTE = (f"학습, 대량 추론, 모델 서버 띄우기처럼 GPU를 크게 쓰는 일은 시작 직전에 uv run --project {ROOT.as_posix()} jipsa gpu signal {{run_id}} --kind 학습 --wait 30 "
                   "(종류는 학습, 추론, 모델서버)을 돌리고, 그 일이 끝나면 jipsa gpu signal {run_id} --done 을 돌린다. 스케줄러가 GPU 예약을 지난 최댓값으로 올리고 "
                   "5분 동안 실제 사용량을 본 뒤 그 최댓값 + 1GB로 고치며, 남은 메모리가 모자라면 명령이 최대 --wait 분까지 기다린다. 명령이 종료 코드 2(자리 없음)로 끝나면 그 큰 일을 시작하지 않고, 배치를 줄여 --gb를 낮추거나 잠시 뒤 다시 신호를 보낸다.")

RESULT_SCHEMA = {
    "status": "완료 | 실패 | 확인 필요",
    "label": "결과를 한글 두세 단어로 (예: 초안 작성, 수집기 제작)",
    "summary": "80자 안의 한 문장. 경로, 파일 이름, 커밋 해시를 넣지 않는다(Slack 결과 줄로 그대로 나간다)",
    "changed_files": ["바뀐 파일 경로"],
    "evidence": ["세션 안에서 직접 실행해 확인한 증거 한 줄씩"],
    "commit": "커밋 해시 또는 빈 문자열",
    "reason": "실패면 사유",
    "rule": "확인 필요면 걸린 규칙",
    "options": ["서로 대체하는 고를 안(1안, 2안처럼)이 있으면 상태와 무관하게 '1안: 내용' 꼴로 적는다. 추천을 맨 앞에. 서로 다른 결정이나 할 일은 넣지 않고 보고서 정할 것에 글로 둔다"],
    "added_packages": ["추가한 패키지와 버전"],
    "preview_url": "미리보기 주소가 있는 결과물이면 적는다, 없으면 빈 문자열. 초안을 요청받은 실행은 실행 폴더 안 HTML 초안 경로를 꼭 적는다",
}

# 초안 실행 안내(261029-jipsa-35). begin --draft나 사람 입력의 '초안'으로 표시된 실행에 붙는다. 비면 finish가 막는다
DRAFT_NOTE = ("초안 요청 실행이다. 여기서 '초안'은 대시보드 결과지의 '초안 보기'로 여는 HTML이다. "
              "사람이 볼 HTML 초안을 {draft} 처럼 실행 폴더 안에 만들고 result.json preview_url에 그 경로를 슬래시로 적는다. "
              "preview_url이 비었거나 그 파일이 없으면 jipsa finish가 마감을 막는다.")


def _paths_block(project: Project) -> str:
    lines = []
    if project.no_read:
        lines.append("- 읽지 않음(열지도 출력하지도 않는다): " + ", ".join(project.no_read))
    if project.read_only:
        lines.append("- 읽기만(쓰지 않는다): " + ", ".join(project.read_only))
    if project.generated:
        gen = "; ".join(f"{k} (다시 만드는 명령: {v})" for k, v in project.generated.items())
        lines.append("- 생성물(직접 고치지 않고 명령으로 다시 만든다): " + gen)
    if project.allowed_dirs:
        lines.append("- 새 파일과 수정을 허용하는 폴더(이 밖에는 쓰지 않는다): " + ", ".join(project.allowed_dirs))
    if project.external_read:
        lines.append("- 허용된 외부 읽기 호출: " + ", ".join(project.external_read))
    if project.external_forbid:
        lines.append("- 금지: " + ", ".join(project.external_forbid))
    for n in project.scope_notes:
        lines.append(f"- {n}")
    return "\n".join(lines) if lines else "- 등록부에 적힌 경로 규칙 없음"


def limits_text(limits: dict | None) -> str:
    """지시문의 자원 한도 줄. 할 일 줄의 한도 칸이 있으면 그 값, 없으면 이 PC 전체다(261025-jipsa-16, 기획 3판 9절). 넘어도 끊지 않는다."""
    lim = limits or {}
    parts = []
    if "vram_gb" in lim:
        parts.append(f"VRAM {lim['vram_gb']:g}GB")
    if "ram_gb" in lim:
        parts.append(f"RAM {lim['ram_gb']:g}GB")
    if "cpu" in lim:
        parts.append(f"CPU {lim['cpu']}스레드")
    if parts:
        return ", ".join(parts) + ". 이 안에서 돌도록 배치 크기, 병렬 수, 모델 크기를 고른다. 적지 않은 자원은 이 PC 전체다"
    return f"이 PC 전체(VRAM {PC_LIMITS['vram_gb']:g}GB, RAM {PC_LIMITS['ram_gb']:g}GB, CPU {PC_LIMITS['cpu']}스레드)"


PC_LIMITS = {"vram_gb": 16, "ram_gb": 31, "cpu": 16}  # 이 PC 전체. 기획 3판 9절의 값이다


def worker_first(
    *,
    project: Project,
    title: str,
    criteria: str,
    run_id: str,
    attempt: int,
    workspace: Path,
    run_dir: Path,
    branch: str | None,
    total_deadline: datetime,
    segment_deadline: datetime,
    dry_run: bool,
    prior_analysis: str | None,
    answer: str | None,
    handover: bool = False,
    codex: bool = False,
    limits: dict | None = None,
    draft: bool = False,
) -> str:
    commit_rule = (
        f"- 작업이 끝나면 이 브랜치({branch})에 커밋 1개를 만든다. 메시지는 한국어 한 줄과 검증 증거다. 푸시, 병합은 하지 않는다."
        if project.commit and branch and not dry_run
        else "- 커밋하지 않는다. 파일만 바꾼다." if not project.commit or dry_run
        else ""
    )
    deps_rule = (
        f"- 패키지를 더해야 하면 먼저 dry-run으로 바뀌는 목록을 본다({'uv lock --dry-run' if project.deps_manager == 'uv-lock' else 'uv pip install --dry-run <패키지>'}). "
        "기존 패키지의 버전이 하나라도 바뀌면 설치하지 않고 확인 필요로 멈춘다. torch, torchvision, torchaudio, CUDA 빌드는 손대지 않는다. "
        "설치했으면 result.json의 added_packages에 적는다. "
        # 같은 가상환경을 여러 작업이 같이 쓰므로 설치는 잠금을 잡고 한다(261026-jipsa-26)
        f"설치 명령은 잠금을 잡고 돌린다: uv run --project {ROOT.as_posix()} jipsa install-lock {project.name} -- <설치 명령>."
    )
    recommend = RECOMMEND_FILE.read_text(encoding="utf-8") if RECOMMEND_FILE.exists() else ""
    parts = [
        f"# jipsa 작업 {run_id} (시도 {attempt})",
        "",
        f"프로젝트: {project.name} ({project.kind}). 작업 폴더: {workspace}",
        f"작업: {title}",
        f"완료 기준: {criteria}",
        f"자동 범위: {project.auto_scope or '등록부 기본'}",
        f"자원 한도: {limits_text(limits)}",
        "",
        "## 시간",
        f"- 이 구간의 상한 시각은 {segment_deadline:%H:%M}이고 총 상한 시각은 {total_deadline:%H:%M}이다. 넘기면 jipsa가 프로세스를 끊는다. 그 전에 progress.md를 쓰고 멈춘다.",
        "",
        "## 진행 방식",
        f"- 먼저 완료 기준을 읽고 3~6단계 계획을 `{run_dir / 'plan.md'}`에 쓴다. 단계마다 확인 방법 한 줄을 붙인다. 마지막 단계는 보고서 작성이다.",
        f"- 이 호출에서는 계획의 첫 단계 하나만 끝내고 `{run_dir / 'progress.md'}`에 적고 멈춘다. 다음 호출이 같은 세션을 이어받아 다음 단계를 한다.",
        "- progress.md는 세 절이다. `## 한 일`, `## 증거`(직접 실행한 명령과 결과), `## 막힌 것`(없으면 '없음'). 매 호출마다 덮어쓴다.",
        f"- 보고서: 끝내기 전에 `{REPORT_FILE}` 규격대로 `{run_dir / 'report.md'}`를 쓰고 그림은 `{run_dir / 'figures'}/`에 둔다. 한국어 평서체, A4 두 장 안이다. 코드 변경 설명이 아니라 무엇이 생겼고 어떻게 보이는지를 쓴다. " + " ".join(REPORT_GUIDE) + " " + ATTACK_NOTE,
        f"- 모든 단계가 끝났거나 더 할 수 없으면 `{run_dir / 'result.json'}`을 아래 틀로 쓰고 멈춘다. result.json이 있으면 jipsa는 작업을 끝낸 것으로 본다.",
        "```json",
        json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2),
        "```",
        f"- {RESULT_WRITE}",
        "- status는 작업자가 스스로 판정한다. 완료 기준을 채웠다고 확인했으면 완료, 못 끝냈으면 실패, 규칙에 막혀 사람이 정해야 하면 확인 필요다. 안을 제안하고 끝낸 작업은 완료로 두고 고를 안은 options에 적는다.",
        "",
        "## 규칙",
        "- 테스트 파일을 만들지 않고 pytest를 돌리지 않는다. 검증은 세션 안에서 직접 실행한 증거로 한다.",
        commit_rule,
        deps_rule,
        f"- {CONCURRENCY_NOTE}",
        f"- {GPU_SIGNAL_NOTE.format(run_id=run_id)}",
        "- 외부 호출은 읽기만 한다. 발행, 푸시, 전송, 주문은 하지 않는다.",
        "- .env, credentials, token 내용을 출력하거나 커밋하지 않는다.",
        "- 사람에게 묻지 않는다. 아래 범위 안이면 추천안으로 가고, 밖이면 result.json에 확인 필요와 선택지(추천을 맨 앞에)를 적고 멈춘다.",
        "- 주석, 커밋, 문서는 한국어 평서체다. 가운데점과 비유를 쓰지 않는다. " + wording_note(),
        "",
        "## 경로 규칙",
        _paths_block(project),
        "",
        "## 추천안으로 가도 되는 범위",
        recommend.strip(),
    ]
    if draft:
        parts += ["", "## 초안", "- " + DRAFT_NOTE.format(draft=(run_dir / "draft" / "index.html").as_posix()).replace("jipsa finish가 마감을 막는다", "jipsa가 한 번 돌려보내고, 그래도 비면 확인 필요로 마감한다")]
    local = local_rules()
    if local:
        parts += ["", *local]
    if codex:
        parts += ["", "## Codex 작업자", "- 위 경로 규칙의 읽지 않음, 읽기만, 생성물 경로에는 쓰지 않는다. Codex에는 deny 설정이 없어서 jipsa가 구간이 끝날 때마다 git 상태로 그 경로 쓰기를 찾고, 걸리면 확인 필요로 넘긴다."]
    if handover:
        parts += ["", "## 이어받기", f"- 이 시도의 앞 구간은 Codex 작업자가 했고 Codex 한도로 멈췄다. 계획을 새로 쓰지 않는다. `{run_dir / 'plan.md'}`와 `{run_dir / 'progress.md'}`를 먼저 읽고, 끝나지 않은 다음 단계 하나를 이어서 한다."]
    if prior_analysis:
        parts += ["", "## 앞 시도의 분석(원인을 고친 뒤 다시 한다)", prior_analysis.strip()[:6000]]
    if answer:
        parts += ["", "## 사람의 답", answer.strip()]
    return "\n".join(p for p in parts if p is not None)


def worker_next(*, segment: int, segment_deadline: datetime, total_deadline: datetime, run_dir: Path, note: str = "", answer: str | None = None) -> str:
    parts = [
        f"구간 {segment}. 이 구간의 상한 시각은 {segment_deadline:%H:%M}, 총 상한 시각은 {total_deadline:%H:%M}이다.",
        f"`{run_dir / 'plan.md'}`의 다음 단계 하나만 끝내고 `{run_dir / 'progress.md'}`를 덮어쓰고 멈춘다. 모든 단계가 끝났으면 `{run_dir / 'result.json'}`을 쓴다.",
    ]
    if note:
        parts.append(f"jipsa의 메모: {note}")
    if answer:
        parts.append(f"사람의 답: {answer}")
    return "\n".join(parts)


def judge_progress(*, criteria: str, prev: str | None, cur: str, segment: int) -> str:
    return (
        "작업자의 진행 메모 두 개를 비교해 이번 구간에 진전이 있었는지 판정한다.\n"
        "진전 없음의 조건: 같은 막힘이 반복된다, 증거 없이 같은 단계를 반복한다, 한 일이 완료 기준과 무관하다. "
        "그 밖에는 진전 있음이다.\n"
        'JSON 한 덩어리만 출력한다: {"progress": "있음" 또는 "없음", "reason": "한 문장"}\n\n'
        f"완료 기준: {criteria}\n구간 번호: {segment}\n\n"
        f"## 앞 구간 메모\n{(prev or '(첫 구간. 앞 메모 없음)').strip()[:4000]}\n\n## 이번 구간 메모\n{cur.strip()[:4000]}"
    )


def save_commit_message(files: list[str], diff_stat: str) -> str:
    return (
        "아래 변경을 한국어 평서체 한 줄(40자 이내)로 요약한다. 파일 이름 나열이 아니라 무엇을 하던 중인지 적는다. 한 줄만 출력한다.\n\n"
        f"파일:\n" + "\n".join(files[:40]) + f"\n\n변경 통계:\n{diff_stat[:2000]}"
    )


def analyze(*, project: Project, title: str, criteria: str, result: dict, diff: str) -> str:
    return (
        "작업자의 결과와 diff를 읽고 analysis.md를 쓴다. 실행하지 않고 읽기만 한다. 지적은 전부 남긴다. 사람이 거른다.\n"
        "첫 줄은 반드시 다음 셋 중 하나다: `원인: 작업자 변경 안`, `원인: 작업자 변경 밖`, `원인: 해당 없음`(완료일 때).\n"
        "그 다음 절은 `## 판정`(완료 기준을 채웠는지, 증거가 충분한지), `## 지적`(번호 목록. 파일과 줄을 적는다), `## 다음 시도에 고칠 것`(실패일 때만)이다.\n"
        "한국어 평서체로 쓰고 가운데점과 비유를 쓰지 않는다. 자료에 없는 사실은 적지 않는다.\n\n"
        f"프로젝트: {project.name} ({project.kind})\n작업: {title}\n완료 기준: {criteria}\n\n"
        f"## result.json\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## diff\n```diff\n{diff if diff.strip() else '(변경 없음)'}\n```"
    )


# 목표 cycle의 단계 결과지 result.json에 더하는 cycle 칸(261023-jipsa-21 1안). jipsa는 판정 앞에 이 칸이 채워졌는지만 본다
CYCLE_RUN_SCHEMA = {
    "score": "이번 Cycle 명령을 수행한 뒤 잰 지표 값(숫자). 예: 40판 평균 점수",
    "delta": "기준선 대비 차(숫자, 기준선이 없으면 null)",
    "low": "95% 구간 하한(숫자, 없으면 null)",
    "high": "95% 구간 상한(숫자, 없으면 null)",
    "fail_class": "명령을 끝내지 못했을 때만. 환경과 운영, 명령 오해, 측정 오류, 아이디어 무효, 외부 의존 가운데 하나",
    "fail_why": "끝내지 못한 이유 한 문장(끝냈으면 빈 문자열)",
}
FAIL_CLASS_TEXT = ("실패 범주는 다섯이다. 환경과 운영(다른 작업의 GPU 점유, 시간 초과, 한도, 연결), 명령 오해(명령을 잘못 읽음), "
                   "측정 오류(측정기나 측정 조건이 틀림), 아이디어 무효(명령대로 했지만 지표가 나아지지 않음), 외부 의존(외부 자료나 서비스가 막힘)")
CYCLE_SCHEMA = {
    "score": "분석이 산출물에서 측정 방법대로 다시 잰 지표 값(숫자). 이행이 적은 값은 쓰지 않는다",
    "delta": "지금 최고 기록 대비 차(숫자, 최고 기록이 없으면 null)",
    "low": "95% 구간 하한(숫자, 없으면 null)",
    "high": "95% 구간 상한(숫자, 없으면 null)",
    "measure": "다시 잴 때 실제로 돌린 명령",
    "feedback": {
        "good": "잘된 것 한두 문장",
        "lack": "모자란 것 한두 문장",
        "verdict": "이번 명령의 결과 판정. 긍정, 중립, 부정 가운데 하나",
        "fail_class": "중립이나 부정일 때 원인 범주 하나(긍정이면 빈 문자열)",
        "dropped": [{"key": "버린 가설의 짧은 key(영문 소문자와 하이픈)", "hypothesis": "버린 가설 한 문장", "why": "버린 이유 한 문장"}],
        "next": [
            {"rank": 1, "key": "이 명령이 시험하는 가설 key", "command": "다음 Cycle 명령 1순위 한두 문장", "deps": ["더할 패키지. 없으면 빈 목록"],
             "est_minutes": 60, "external_write": False},
            {"rank": 2, "key": "가설 key", "command": "1순위가 금지 사항이나 버린 가설에 걸리면 대신 돌릴 차순위 명령. 칸은 1순위와 같다"},
        ],
    },
}
# 분석이 더하는 explore 칸(261027-jipsa-03). jipsa는 칸 점검을 하지 않고 기록과 끝 결과지, 다음 분석의 후보 목록에 옮긴다
EXPLORE_FIELD = {
    "tried": ["지금까지 시도한 방법 한 줄씩(Cycle 번호와 결과)"],
    "candidates": [{"method": "더 좋은 방법 후보 한 문장", "source": "로컬 자료, 웹, 지난 Cycle, 다른 목표, 사람 피드백 가운데 하나",
                    "ref": "출처 파일 경로나 URL", "why": "이 지표를 낫게 할 근거 한 문장", "fit": "이 PC와 범위 칸에서 할 수 있는지 한 문장",
                    "tried": False}],
    "searched": ["찾아본 곳과 검색어 한 줄씩. 찾은 것이 없어도 적는다"],
    "repeat_why": "다음 명령 1순위가 이미 시도한 방법의 반복(수치나 대상만 바꿈)이면 그 이유, 아니면 빈 문자열",
}
# 아이디어 갈래 한 줄(261029-jipsa-10 1안). Cycle 1 이행이 만들고 Cycle 1 분석이 고친다
BRANCH_FIELD = {"name": "갈래 이름(짧은 한국어 명사구, 목록 안에서 겹치지 않게)", "hypothesis": "이 갈래가 지표를 낫게 한다고 보는 가설 한 문장. 갈래마다 다른 가설",
                "first": "이 갈래의 첫 명령 한두 문장", "done_when": "이 갈래를 끝낼 조건 한 문장(예: 연속 2바퀴 미개선, 목표값 도달)",
                "needs_approval": False}
# 탐색 자료 폴더의 형식 안내. 자료 이름의 일부를 키로 한 줄씩 더한다. 분석이 rg로 좁혀 읽는다
SOURCE_HINT: dict[str, str] = {}


def _explore(cycle, ex: dict | None, fresh: list[str] | None = None) -> list[str]:
    """분석의 탐색 절(261027-jipsa-03). 지난 Cycle 전체, 사람 답과 피드백, 후보 목록, 다른 목표, 수집 자료, 웹 검색 지시다.
    판정 기준은 바꾸지 않고, 다음 명령 고르기 전에 기존 방법 밖의 후보를 찾게 한다.
    fresh는 사람 피드백 절에 이미 실린 원문이다. 같은 글을 두 번 싣지 않고 앞 Cycle에서 읽힌 원문만 여기에 싣는다(261027-jipsa-04)."""
    if ex is None:
        return []
    new = set(fresh or [])
    read = [t for t in ex.get("feedback") or [] if t not in new]
    j = lambda xs, empty: " / ".join(xs) if xs else empty  # noqa: E731
    src = []
    for label, path in ex.get("sources") or []:
        hint = next((v for k, v in SOURCE_HINT.items() if k in label), "")
        src.append(f"{label} {path}" + (f"({hint})" if hint else ""))
    reached = ex.get("reached")
    lines = [
        "탐색: 이 분석은 지표를 다시 잰 뒤 다음 명령을 고르기 전에 지금 방법보다 더 좋은 방법을 찾는다. Auto가 켜져 있는 동안 Cycle은 마감까지 이어지므로 "
        "같은 방법의 수치만 바꾸는 반복보다 아직 시도하지 않은 후보를 먼저 본다.",
        "지난 Cycle 전체: " + j(ex.get("rounds"), "없음(첫 Cycle)") + ".",
        "지난 분석 결과지(읽어도 된다): " + j(ex.get("sheets"), "없음") + ".",
        "단계 결과지에 사람이 단 답: " + j(ex.get("answers"), "없음") + ".",
        "이 목표의 사람 피드백 가운데 앞 Cycle에서 이미 읽힌 원문" + ("(이번에 새로 읽는 원문은 위 사람 피드백 절에 있다)" if new else "") + ": "
        + j([f"[{i}] {t}" for i, t in enumerate(read, 1)], "없음") + ".",
        "지난 분석이 낸 후보 가운데 시도한 것: " + j(ex.get("tried"), "없음") + ".",
        "아직 시도하지 않은 후보: " + j(ex.get("untried"), "없음") + ". 이 후보를 버리려면 explore 칸에 이유를 적는다.",
        "같은 프로젝트의 다른 Cycle 목표(그 목표가 만든 모델 후보, 방법론, 산출물을 이 목표에 쓸 수 있는지 본다): " + j(ex.get("others"), "없음") + ".",
        "자료 탐색 순서: 1) 수집 자료 " + j(src, "없음") + ". 목표 문장과 지표의 핵심어로 rg를 걸어 폴더와 파일 종류를 좁혀 읽는다. "
        "2) 웹 검색(WebSearch, WebFetch)으로 이 지표를 낫게 할 최신 방법(최근 1년 안의 논문, 공개 모델, 저장소, 학습 방법)을 찾는다. "
        "모두 읽기만 한다. 그 저장소의 파일을 고치지 않고, 모델과 데이터를 내려받지 않으며, 로그인과 글쓰기를 하지 않는다.",
        "찾은 후보마다 방법, 출처(파일 경로나 URL), 근거, 이 PC와 범위 칸에서 할 수 있는지를 explore 칸에 적는다. 찾아본 곳과 검색어는 찾은 것이 없어도 searched에 적는다. "
        "다음 명령 1순위와 차순위는 시도한 것, 아직 시도하지 않은 후보, 새로 찾은 후보를 견주어 지표에 가장 효과가 클 것으로 고르고, "
        "1순위가 이미 시도한 방법의 반복이면 repeat_why에 이유를 적는다. 후보가 범위 칸 밖(새 모델 내려받기, torch 변경, 외부 쓰기)이면 명령의 needs_approval을 true로 적는다.",
        ("목표값에 이미 닿았다" + (f"(Cycle {reached.get('n')}, 지표 {reached.get('metric')})" if isinstance(reached, dict) else "") + ". " if reached else "")
        + "목표값에 닿아도 끝내지 않고 Auto 마감까지 같은 지표, 같은 방향으로 더 나아질 다음 명령을 쓴다(위임 cycle 범위). 지표를 바꾸거나 반대 방향으로 가는 명령은 쓰지 않는다.",
        "보고서 본문 첫 절은 '탐색과 다음 후보'이고 시도한 것, 다음 후보(어디서 찾았는지), 탐색 출처를 각각 한두 줄로 쓴다. 사람이 이 절을 보고 결과지에 피드백을 단다. "
        "경로와 URL은 본문에 쓰지 않고 마지막 '열어 볼 파일' 줄에 둔다.",
        "explore 칸 틀: " + json.dumps(EXPLORE_FIELD, ensure_ascii=False),
    ]
    return lines


# 목표 미정 Cycle에서 분석이 더하는 goal 칸(261026-jipsa-11). 사람이 비운 칸만 jipsa가 할 일 줄에 채운다
GOAL_FIELD = {
    "metric": "정한 지표 한 줄. 수치 지표(예: 고정 시드 40판 평균 점수)나 기계 O/X 체크(통과한 항목 수). 대리 지표와 사람 확인은 쓰지 않는다",
    "target": "목표값(숫자)", "unit": "목표값 단위(없으면 빈 문자열)", "dir": "이상 또는 이하",
    "how": "다시 잴 때 돌릴 명령이나 절차 한 줄",
    "why": "이 지표와 목표값을 고른 근거 두세 문장(할 일 문장, 등록부, 저장소 상태, 지금 값)",
}
CHECKS_FIELD = [{"id": "목표 카드의 항목 id", "ox": "O, X, 측정 불가 가운데 하나", "value": "잰 값 한 줄"}]
# 목표 정하기 단계의 카드 틀(261023-jipsa-40, 27번 기획). 판정은 수치 지표와 목표값, 또는 체크 항목 5~8개 가운데 하나다


def _cycle_head(cycle, record_file: Path | None, history: list[str]) -> list[str]:
    """목표, 범위 칸, cycle 기록, 지난 Cycle 줄. record_file이 None이면 앞 두 줄만 쓴다(분석 단계는 이행 보고서를 잇지 않는다)."""
    dirs = ", ".join(cycle.allowed_dirs) if cycle.allowed_dirs else "저장소 전체(등록부 금지 경로 제외)"
    scope = [f"허용 프로젝트 {', '.join(cycle.allowed_projects)}", f"허용 폴더 {dirs}",
             f"위험 {'과 '.join(cycle.risks)}", "의존성 " + ("추가 허용" if cycle.deps_allowed else "추가 금지")]
    if cycle.gpu_min is not None:
        scope.append(f"GPU Cycle당 {cycle.gpu_min}분까지")
    cap = cycle.round_cap or cycle.round_est
    if cap:
        scope.append(f"Cycle당 {cap}분")
    scope += [f"{k} 상한 {v}" for k, v in cycle.caps.items()]
    pending = getattr(cycle, "pending", None) or []
    head = [
        f"목표 cycle '{cycle.title}'의 한 단계다. 목표: {cycle.goal}. 수치 지표: {cycle.metric}. "
        f"목표값: {cycle.target:g} {cycle.direction}." if cycle.target is not None and not pending else
        f"목표 cycle '{cycle.title}'의 한 단계다. 목표: {cycle.goal}. 지표: {cycle.metric or '미정'}. "
        f"목표값: {f'{cycle.target:g} {cycle.direction}' if cycle.target is not None else '미정'}. "
        f"사람이 {', '.join(pending)}을 비워 둔 목표 미정 Cycle이고 Cycle 분석이 정한다." if pending else
        f"목표 cycle '{cycle.title}'의 한 단계다. 목표: {cycle.goal}. 지표: {cycle.metric}.",
        f"범위 칸: {'; '.join(scope)}. 푸시, 발행, torch 계열 변경, 외부 쓰기는 하지 않는다.",
    ]
    if record_file is None:
        return head
    return head + [
        f"cycle 기록 {record_file.as_posix()}를 먼저 읽는다. 앞 Cycle을 다른 주체가 했어도 이 기록과 앞 Cycle 보고서로 잇는다.",
        "지난 Cycle: " + (" / ".join(history) if history else "없음(첫 Cycle)") + ".",
    ]


def _human_feedback(feedback: list[str] | None, step: str) -> list[str]:
    """사람 피드백 절(261026-jipsa-19). 원문을 고치지 않고 번호만 붙인다. 판정 기준은 바꾸지 않는다고 못 박는다."""
    if not feedback:
        return []
    use = ("분석은 이 피드백을 반영해 다음 Cycle 명령 1순위와 차순위를 쓴다." if step == "분석"
           else "이번 명령을 수행할 때 이 피드백을 참고한다.")
    return ["사람 피드백(사람이 직접 적은 원문이다): " + " ".join(f"[{i}] {t}" for i, t in enumerate(feedback, 1)) + " 끝. "
            + use + " 피드백은 판정 기준(지표, 목표값, 방향)을 바꾸지 않는다. 판정 기준과 어긋나는 요청이면 따르지 않고 보고서에 이유를 적는다."]


def _prior_feedback(prior: list[str] | None, step: str) -> list[str]:
    """같은 프로젝트의 앞 목표에 사람이 적은 피드백 절(261027-jipsa-02). 새 할 일 줄로 바꿔 올려도 앞 줄의 요청을 잇는다."""
    if not prior:
        return []
    use = ("분석은 아직 유효한 요청을 다음 Cycle 명령 1순위나 차순위에 반영하고, 반영하지 않은 요청은 보고서에 이유를 적는다." if step == "분석"
           else "이번 명령을 수행할 때 아직 유효한 요청을 참고한다.")
    return ["같은 프로젝트의 앞 Cycle 목표에 사람이 적은 피드백(원문, 오래된 것이 앞): " + " ".join(f"[{i}] {t}" for i, t in enumerate(prior, 1))
            + " 끝. " + use + " 이 피드백도 판정 기준을 바꾸지 않는다."]


def _branch_lines(rows: list[dict]) -> str:
    return " / ".join(f"{b['name']}({b['status']}, {b['rounds']}바퀴, 연속 미개선 {b['streak']}"
                      + (f", 최고 {b['best']:g}" if isinstance(b.get("best"), (int, float)) else "") + f"): {b['hypothesis']}" for b in rows)


def _run_branches(br: dict | None) -> tuple[list[str], dict]:
    """이행의 갈래 절과 cycle 칸에 더할 틀. make면 Cycle 1 이행이 갈래 목록을 만든다(261029-jipsa-10 1안)."""
    if not br:
        return [], {}
    if not br.get("make"):
        return ["아이디어 갈래(jipsa가 센다): " + _branch_lines(br.get("list") or []) + ". 이번 명령은 붙은 갈래 안에서만 수행한다."], {}
    return [
        "아이디어 갈래 만들기: 실행 계획을 쓸 때 목표 문장과 사람 피드백에 맞춘 아이디어 갈래 3~6개를 함께 만든다. 갈래는 같은 방향의 아이디어 묶음이고 "
        "갈래마다 가설이 달라야 한다. 명령 하나마다 갈래를 따로 두지 않고(너무 좁음), 둘 이하로 묶지 않는다(너무 넓음). "
        "사람 지시의 중심 방향은 한 갈래로 꼭 넣는다. 범위 칸 밖(새 모델 내려받기, 설치, torch 변경, 외부 쓰기)이 필요한 갈래는 needs_approval을 true로 적는다.",
        "갈래마다 이름, 가설, 첫 명령, 끝낼 조건을 plan.md와 cycle 칸 branches에 적고, 이번 명령이 든 갈래 이름을 branch에 적는다. "
        "jipsa는 같은 갈래가 연속 2번 최고 기록을 넘지 못하면 그 갈래를 닫고 다른 갈래로 간다. Cycle 1 분석이 이 목록을 다시 보아 고친다.",
    ], {"branches": [BRANCH_FIELD], "branch": "이번 명령이 든 갈래 이름"}


def cycle_run(cycle, *, n: int, plan: dict, record_file: Path, history: list[str], retry: str | bool = "",
              feedback: list[str] | None = None, prior: list[str] | None = None, branches: dict | None = None) -> str:
    """1단계 명령 이행의 완료 기준. 명령을 범위 칸 안에서 수행하고 지표를 재서 cycle 칸에 쓴다. branches는 갈래 절이다(_run_branches)."""
    again = f" 다시(앞 이행이 막혔다: {retry}. 같은 명령을 한 번 더 한다)" if isinstance(retry, str) and retry else (" 다시" if retry else "")
    blines, bfield = _run_branches(branches)
    lines = _cycle_head(cycle, record_file, history) + [
        f"Cycle {n} 명령 이행{again}. 명령: {plan.get('plan', '')}",
        *_prior_feedback(prior, "명령 이행"),
        *_human_feedback(feedback, "명령 이행"),
        "명령을 범위 칸 안에서만 수행하고 지표를 같은 조건으로 잰다. 범위 칸 밖의 변경이 필요하면 하지 않고 확인 필요로 멈춘다.",
        *blines,
        *(["목표가 아직 미정이라 지표는 이번 Cycle 분석이 정한다. 보고서에 잴 수 있는 지표 후보(수치 지표나 기계 O/X 체크)와 재는 방법, 지금 값을 적고, "
           "가장 알맞은 후보로 잰 값을 score에 적는다. 잴 수단을 찾지 못했으면 score를 null로 둔다."] if getattr(cycle, "pending", None) else []),
        "보고서에 지표 값, 기준선 대비 차, 95% 구간, 증거를 적는다. 피드백과 다음 명령은 분석 단계가 쓰므로 쓰지 않는다.",
        f"명령을 끝내지 못하면 cycle 칸의 fail_class와 fail_why를 적는다. {FAIL_CLASS_TEXT}.",
        "result.json에 아래 틀의 cycle 칸을 더한다." + ("" if getattr(cycle, "pending", None) else " 지표 칸이 비면 jipsa가 이행을 다시 시킨다."),
        "cycle 칸 틀: " + json.dumps({**CYCLE_RUN_SCHEMA, **bfield}, ensure_ascii=False),
    ]
    return " ".join(lines)


def cycle_analysis(cycle, *, n: int, artifacts: dict, attempts: list[str], baseline: float | None, feedback: list[str] | None = None,
                   prior: list[str] | None = None, explore: dict | None = None, pivot: dict | None = None, branches: dict | None = None) -> str:
    """2단계 분석과 피드백의 완료 기준(261023-jipsa-32 독립 판정). 이행의 대화, 보고서, 완료 주장은 넘기지 않는다.
    branches가 있으면 아이디어 갈래 절을 넣는다(261029-jipsa-10 1안, _branches).
    pivot이 있으면 방향 전환 절을 넣는다(261029-jipsa-03 1안). now는 이번 Cycle이 전환 바퀴, ahead는 이번에도 나아지지 않으면 다음이 전환 바퀴다.
    산출물 위치, 측정 방법, 목표, 시도 기록만 넘기고, 분석이 산출물에서 지표를 다시 잰다. 판정은 jipsa가 다시 잰 값으로 한다."""
    files = ", ".join(artifacts.get("changed_files") or []) or "목록 없음(브랜치의 마지막 커밋 diff를 본다)"
    where = (f"브랜치 {artifacts.get('branch') or '없음'}, 커밋 {artifacts.get('commit') or '미상'}, 바뀐 파일 {files}"
             + (f", 작업 폴더 {artifacts['workspace']}" if artifacts.get("workspace") else ""))
    how = f"측정 명령 `{cycle.measure}`" if cycle.measure else f"지표 '{cycle.metric}'를 이행과 같은 고정 조건으로 잰다"
    pending = getattr(cycle, "pending", None) or []
    goal = []
    if pending:
        # 목표 미정 Cycle(261026-jipsa-11). 이 분석이 목표를 정하고 jipsa가 그 값으로 판정한다
        keep = [f"지표 '{cycle.metric}'" if cycle.metric else "", f"목표값 {cycle.target:g} {cycle.direction}" if cycle.target is not None else "",
                f"상한 {cycle.no_gain_limit}" if cycle.no_gain_limit else ""]
        how = "이번 분석이 정한 지표로, 다시 돌릴 수 있는 고정 조건에서 잰다"
        goal = [
            f"목표 정하기: 사람이 {', '.join(pending)}을 비워 두었다. 이 분석이 할 일 문장, 프로젝트 등록부, 저장소 상태를 보고 "
            "빈 칸을 정한다" + (f"(사람이 적은 {', '.join(k for k in keep if k)}은 그대로 쓴다)" if any(keep) else "") + ".",
            "지표는 수치 지표나 기계 O/X 체크(통과한 항목 수)이고 대리 지표와 사람 확인은 쓰지 않는다. 목표값은 지금 값보다 목표 방향으로 닿을 만한 수다. "
            "연속 정체 상한은 정하지 않는다. 사람이 비운 상한은 비운 채 두고 Cycle은 마감까지 돈다(261029-jipsa-03 1안).",
            "정한 값과 근거를 cycle 칸의 goal에 적고, 보고서에 '목표 정하기' 절을 두어 지표, 목표값, 방향, 재는 방법, 근거를 적는다. "
            "jipsa가 빈 칸만 할 일 줄에 채우고 이 분석이 그 지표로 다시 잰 score로 첫 판정을 한다.",
            "잴 수단이 없어 지표를 정할 수 없으면 goal을 비우고 result.json status를 확인 필요, rule을 'Cycle 목표 미정: 잴 수단 없음'으로 적는다. 그러면 목표를 끝내고 사람이 본다.",
            "goal 칸 틀: " + json.dumps(GOAL_FIELD, ensure_ascii=False),
        ]
    checks = []
    if getattr(cycle, "checks", None):
        # 체크 카드 목표(261023-jipsa-40). 항목마다 재는 방법대로 다시 재고, 통과 수를 지표로 쓴다
        checks = [f"판정 항목(목표 판 v{cycle.version}): " + " / ".join(
            f"{x.get('id')}: {x.get('item')}, 기준 {x.get('pass') or '-'}, 재는 방법 {x.get('how')}" for x in cycle.checks) + ".",
            "항목마다 재는 방법대로 다시 재고 checks 칸에 id, ox(O, X, 측정 불가), 잰 값을 적는다. score는 O인 항목 수다. "
            "잴 수 없었던 항목은 측정 불가로 적는다.",
            "다음 명령이 승인이 필요한 선행(설치, 모델 내려받기, 새 프로젝트, 외부 쓰기, torch)을 요구하면 그 명령의 needs_approval을 true로 적는다.",
            "checks 칸 틀: " + json.dumps(CHECKS_FIELD, ensure_ascii=False)]
        if cycle.human:
            checks.append("사람 확인 항목(" + ", ".join(str(h.get("item")) for h in cycle.human) + ")은 재지 않고 판정에서 뺀다.")
    lines = _cycle_head(cycle, None, []) + checks + goal + [
        f"Cycle {n} 분석과 피드백. 이번 단계는 이행과 독립으로 판정 근거를 만든다.",
        *_prior_feedback(prior, "분석"),
        *_human_feedback(feedback, "분석"),
        f"산출물: {where}. 이 작업 폴더는 그 브랜치에서 시작했다.",
        "이행 실행의 보고서, progress, result.json, 대화 기록은 읽지 않는다. 이행이 적은 지표 값과 완료 주장은 근거로 쓰지 않는다.",
        f"측정 방법: {how}. 산출물에서 직접 다시 재고 그 값을 score에, 돌린 명령을 measure에 적는다.",
        f"지금 최고 기록은 {baseline if baseline is not None else '없음(첫 측정)'}이다. 목표 판정(O, X)과 나아짐 여부는 jipsa가 다시 잰 값으로 정하므로 쓰지 않는다.",
        "시도 기록(최근 20줄): " + (" / ".join(attempts) if attempts else "없음(첫 Cycle)") + ".",
        "피드백에 잘된 것, 모자란 것, 결과 판정(긍정, 중립, 부정), 버린 가설과 이유, 다음 Cycle 명령 1순위와 차순위를 쓴다. "
        "다음 명령은 시도 기록의 버린 가설과 겹치지 않게 쓴다. 겹치면 jipsa가 차순위로 바꾼다. 두 명령 모두 범위 칸 안으로 쓴다.",
        f"결과 판정이 중립이나 부정이면 fail_class에 원인 범주를 적는다. {FAIL_CLASS_TEXT}. 환경과 운영, 측정 오류는 정체 횟수에서 빠진다.",
        *_explore(cycle, explore, feedback),
        *_pivot(pivot),
        *(bl := _branches(branches)),
        "result.json에 아래 틀의 cycle 칸을 더한다." + (" explore 칸도 cycle 칸 안에 둔다. explore의 searched가 비거나 후보가 없거나 후보에 출처와 근거가 없으면 탐색을 하지 않은 것으로 보고 분석을 한 번 다시 시킨다." if explore is not None else "") + " 지표 칸, 피드백 칸, 결과 판정이 비면 jipsa가 분석을 한 번 다시 시킨다. 숫자 칸은 숫자로 적는다.",
        "cycle 칸 틀: " + json.dumps(_branch_schema() if bl else CYCLE_SCHEMA, ensure_ascii=False),
    ]
    return " ".join(lines)


def _branch_schema() -> dict:
    """갈래 절이 있는 분석의 cycle 칸 틀. 다음 명령마다 branch, 이번 명령의 branch_this, Cycle 1의 branches, 새 갈래 branch_new를 더한다."""
    fb = dict(CYCLE_SCHEMA["feedback"])
    fb["next"] = [{**x, "branch": "이 명령이 든 갈래 이름"} for x in fb["next"]]
    return {**CYCLE_SCHEMA, "feedback": fb, "branch_this": "이번 Cycle 명령이 실제로 든 갈래 이름(다시 본 값)",
            "branches": "Cycle 1 분석만. 고친 갈래 목록 전체 [" + json.dumps(BRANCH_FIELD, ensure_ascii=False) + ", ...]",
            "branch_new": "새 갈래가 필요할 때만 하나. 칸은 갈래 한 줄과 같고 why(기존 갈래와 다른 점)를 더한다. 아니면 null"}


def _branches(br: dict | None) -> list[str]:
    """분석의 아이디어 갈래 절(261029-jipsa-10 1안). 목록 다시 보기, 이번 명령의 갈래 확인, 다음 명령마다 갈래, 새 갈래 하나다."""
    if not br:
        return []
    rows = br.get("list") or []
    out = []
    if br.get("first"):
        out.append("갈래 목록 다시 보기: 이번은 Cycle 1 분석이다. "
                   + ("이행이 만든 갈래 목록: " + _branch_lines(rows) + ". " if rows else "이행이 갈래 목록을 내지 못했다. 이 분석이 만든다. ")
                   + "목표 문장과 사람 피드백, 이번 측정 결과를 보고 갈래를 더하거나 고쳐 3~6개 목록 전체를 branches에 적는다. "
                   "갈래마다 가설이 달라야 하고, 사람 지시의 중심 방향이 빠지지 않게 한다. 명령 하나마다 갈래를 두지 않고 둘 이하로 묶지 않는다. "
                   "범위 칸 밖이 필요한 갈래는 needs_approval을 true로 적는다(jipsa가 사람 확인으로 넘기고 고르지 않는다).")
    else:
        out.append("아이디어 갈래(jipsa가 센 값): " + _branch_lines(rows) + ".")
    out.append(f"이번 Cycle 명령에 붙은 갈래는 '{br.get('this') or '없음'}'이다. 명령이 실제로 어느 갈래였는지 다시 보고 branch_this에 적는다. "
               "붙은 이름과 방향이 다르면 맞는 갈래로 고친다. 이름만 바꿔 닫힌 갈래를 빠져나가지 않는다.")
    out.append(f"다음 명령마다 branch에 목록의 갈래 이름을 적는다. 비우거나 목록에 없는 이름이면 jipsa가 분석을 다시 시키고 그 명령을 쓰지 않는다. 같은 갈래가 연속 {br.get('close', 2)}번 최고 기록을 넘지 못하면 jipsa가 그 갈래를 닫고, "
               "닫힌 갈래나 사람 확인 갈래의 명령은 버린 가설처럼 건너뛴다.")
    if br.get("avoid"):
        out.append(f"방향 전환 바퀴의 명령(rank 3)은 열린 갈래 가운데 지난 미개선 바퀴의 갈래({', '.join(br['avoid'])}) 밖으로 쓴다. 안 간 갈래가 먼저다.")
    if int(br.get("open") or 0) <= 1 and not br.get("first"):
        out.append("열린 갈래가 하나 이하다. 이번에 닫히면 갈 곳이 없으므로 기존 갈래와 다른 새 갈래 하나를 branch_new에 적고 why에 다른 점을 쓴다. "
                   "더할 것이 없으면 null로 두고, 그러면 열린 갈래가 다 닫혔을 때 jipsa가 확인 필요로 멈춘다.")
    else:
        out.append("새 갈래는 꼭 필요할 때만 branch_new에 하나 적고 why에 기존 갈래와 다른 점을 쓴다. why가 없거나 기존 갈래의 가설이나 첫 명령을 그대로 쓰면 받지 않는다.")
    return out


def _pivot(pv: dict | None) -> list[str]:
    """방향 전환 절(261029-jipsa-03 1안). 연속 나아지지 않음이 2의 배수에 닿으면 jipsa가 다음 Cycle을 최고 기록 브랜치에서 전환 바퀴로 연다."""
    if not pv:
        return []
    misses = " / ".join(pv.get("misses") or []) or "없음"
    best = f"Cycle {pv['best']}" if pv.get("best") else "기준선"
    turn = (f"최고 기록({best})에서 다시 출발해, 지난 바퀴들과 다른 쪽의 안 한 후보(탐색 칸)로 간다. "
            f"지난 {len(pv.get('misses') or []) or 2}바퀴의 방향을 되풀이하지 않는다. 지난 미개선 Cycle의 명령 요지: {misses}.")
    out = []
    if pv.get("now"):
        out.append(f"방향 전환: 이번 Cycle은 연속 {pv.get('streak')}바퀴 나아지지 않아 jipsa가 연 방향 전환 바퀴다. 다음 명령도 " + turn)
    if pv.get("ahead"):
        out.append(f"방향 전환 대비: 지난 Cycle까지 연속 {pv.get('streak')}바퀴 나아지지 않았다. 이번 Cycle도 최고 기록보다 나아지지 않으면 다음 Cycle은 방향 전환 바퀴다. "
                   "그 바퀴의 명령은 " + turn + " 이 명령을 next에 rank 3, pivot true로 더한다(칸은 1순위와 같다). "
                   "jipsa가 나아지지 않음으로 판정하면 rank 3을 먼저 쓰고, 나아짐이면 1순위와 차순위를 쓴다.")
    return out


def search(*, project: Project, title: str, criteria: str, analysis: str, sources: list[tuple[str, Path]]) -> str:
    src = "\n".join(f"- {label}: {path}" for label, path in sources)
    return (
        "analysis.md의 지적과 작업 주제에 도움이 되는 자료를 찾아 search.md 내용을 출력한다.\n"
        "찾는 순서는 아래 로컬 자료 순서이고, 웹은 로컬 자료로 모자랄 때만 쓴다. 출처 없는 문장은 쓰지 않는다. "
        "항목마다 `- 요지 한 줄 (출처: 파일 경로 또는 URL)` 모양이다. 많아야 8개다. 없으면 `찾은 자료 없음`이라고 쓴다.\n"
        "한국어 평서체로 쓰고 가운데점과 비유를 쓰지 않는다. 파일을 고치지 않는다.\n\n"
        f"로컬 자료:\n{src}\n\n프로젝트: {project.name}\n작업: {title}\n완료 기준: {criteria}\n\n## analysis.md\n{analysis.strip()[:6000]}"
    )
