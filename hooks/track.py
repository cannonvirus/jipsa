"""Claude Code hook. 세션 자신의 도구 호출을 jipsa 이벤트로 흘려 대시보드에 올린다.

.claude/settings.json의 hooks가 SessionStart, UserPromptSubmit, PostToolUse, SubagentStart, SubagentStop, Stop, SessionEnd에서
이 파일을 부른다. 표준 입력의 JSON 하나를 읽고 runtime/state/events.jsonl에 줄을 붙이고 runs/session-<id>/meta.json을 갱신한다.
메인 세션이 채팅에 결론을 쓰지 않게 사람 입력이 묻는 말이면 결과지로 내라는 안내를 붙이고, 턴 끝에서 결론 문장 꼴을 한 번 막는다(261025-jipsa-31).
빨라야 하므로 표준 라이브러리만 쓰고 scheduler 패키지를 들이지 않는다. Stop의 답 대기 명령 검사만 psutil을 쓰는 scheduler.sessionproc을 그때 들인다.
어떤 오류도 세션을 막지 않는다(항상 종료 코드 0).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ["JIPSA_STATE_DIR"]) if os.environ.get("JIPSA_STATE_DIR") else ROOT / "runtime" / "state"  # 시험용으로 바꾼다(scheduler.config와 같다)
EVENTS = STATE / "events.jsonl"
INBOX = STATE / "session_inbox.jsonl"  # 세션이 하던 일에 들어온 답(record.answer가 쓴다)
RUNS = Path(os.environ["JIPSA_RUNS_DIR"]) if os.environ.get("JIPSA_RUNS_DIR") else ROOT / "runs"  # 시험용
CHAT_LIMIT = int(os.environ.get("JIPSA_CHAT_LIMIT", "").strip() or 300)  # 메인 세션 마지막 답의 글자 수 한도. 넘으면 턴 끝에서 한 번 막는다(261025-jipsa-13 나안)
# 결론 문장 표지(261025-jipsa-31). 300자 한도만으로는 짧은 판정과 원인 설명이 지나갔다. 길이와 무관하게 이 꼴이 마지막 답에 있으면 턴 끝을 한 번 막는다.
# JIPSA_CHAT_MARKERS=0(off, false, no)이면 표지 검사와 묻는 말 안내를 모두 끈다. 300자 한도는 그대로다.
CHAT_MARKERS = os.environ.get("JIPSA_CHAT_MARKERS", "").strip().lower() not in ("0", "off", "false", "no")
VERDICT_MARKERS = (  # 판정, 원인, 이유. 그 턴에 작업을 열었어도 막는다. 연 작업의 결과지가 낼 말이다
    r"원인(?:은|는|이다|입니다|이었|으로 보|이 아니|이 맞|을 확인했|을 찾았)",
    r"이유(?:는|가 |이다|입니다)",
    r"때문(?:이다|입니다|이었|이에요|이야)",
    r"(?:^|(?<=[\s.!?]))(?:아니다|아닙니다|맞다|맞습니다|그렇다|그렇습니다|아니요|네)[.,!]",
    r"(?:이|가) 아니(?:라|고)\s",
    r"분석(?:해 보니|한 결과|결과[는,])|확인해 보니",
    r"(?i)\b(?:root cause|the cause|because|the reason)\b",
)
# 원인 접속(because, 때문)이 이은 말이 도구나 명령의 실패 사실 한 마디뿐이면 원인 분석이 아니라 사실 보고다(261028-jipsa-06).
# "Sol 공격은 Codex 호출이 실패해 돌지 않았다"와 같은 말이다. 실패를 풀이하거나 추정하는 말이 섞이면 그대로 막는다.
CAUSE_WORD = re.compile(r"(?i)\bbecause\b|때문(?:이다|입니다|이었|이에요|이야)")
FAIL_FACT = re.compile(r"(?i)\b(?:failed|errored|crashed|timed out|exited with (?:code )?\d+|returned an error)\b"
                       r"|실패(?:했|하였|해서)?|오류가 났|오류를 냈|시간 초과|제한 시간을 넘|종료 코드")
GUESS_WORDS = re.compile(r"(?i)\b(?:probably|likely|seems?|appears?|might|may|because|due to|since|so|which|that)\b"
                         r"|것 같|보인다|보입니다|추정|아마|듯|원인|이유|때문에|(?:아서|어서|해서|여서|니까|므로|로 인해)\s")  # 앞선 원인을 잇는 말
TOOL_NOUN = re.compile(r"(?i)\b(?:codex|claude|sol|call|command|request|tool|process|server|api|script|hook|exec)\b"
                       r"|호출|명령|요청|도구|프로세스|서버|스크립트|실행")  # 실패한 것이 도구나 명령이어야 사실 보고다
FACT_CLAUSE_MAX = 40  # 이은 말이 이보다 길면 풀이로 본다
PROPOSAL_MARKERS = (  # 제안과 선택지. 그 턴에 작업을 열지 않았을 때만 막는다
    r"(?:해결안|해결 방안|방안|대안|개선안)(?:은|는|이다|입니다|으로는)",
    r"제안(?:합니다|한다|드립니다|드린다|을 정리|은 다음)",
    r"추천(?:합니다|한다|드립니다|드린다)",
    r"(?<![가-힣])(?:[1-9]|[가나다라])안\s*(?:추천|[:：])",
    r"(?i)\b(?:I (?:recommend|suggest|propose)|option [1-9A-C])\b",
)
ASK_WORDS = re.compile(r"원인|분석|제안|방안|해결안|이유|왜|맞는가|맞나|맞는지|맞아|인가|인지 확인|어떻게|뭐가|무엇|\?|\b(?:why|cause|analy[sz]|propos|suggest|recommend)", re.I)
ASK_STRONG = re.compile(r"원인|분석|제안|방안|해결안|이유|왜|맞는가|맞나|맞는지|\b(?:why|cause|analy[sz]|propos|suggest|recommend)", re.I)  # 단순 명령과 섞여도 묻는 말로 보는 말
SIMPLE_PROMPTS = re.compile(  # 묻는 말이 아닌 단순 명령. 상태 보기, 지난 결과, 답 넣기, 모드 전환이다. ASK_STRONG이 함께 있으면 묻는 말이 앞선다
    r"^/\S+|^(?:jipsa\s*/\s*)?(?:상태|지난 결과|결과지?|진행)\s*(?:보여|봐|알려|확인)|(?:확인 필요|판단 대기)\s*답|^\d{6}-[\w-]+-\d{2}\s*(?:답|:)|^답\s*[:：]|Auto\s*(?:모드로|켜|꺼|상태)")
BEGIN_CALL = re.compile(r"(?:jipsa(?:\.exe)?|scheduler\.cli)\s+(?:begin|cycle\s+(?:next|start))\b")  # 이 턴에 작업을 연 호출. 파이썬 모듈로 부른 꼴도 받는다
PROJECTS = ROOT / "projects"
SLACK_URL = re.compile(r"https://hooks\.slack\.com/\S+")
_TOOL_KEYS = ("command", "file_path", "pattern", "query", "url", "description", "prompt", "skill", "notebook_path")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(timespec="seconds")


def clean(value):
    """도구 출력에 섞인 깨진 글자(서로게이트)를 치환 문자로 바꾼다. 그대로 두면 파일에 쓰다가 죽는다."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def emit(row: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(clean({"ts": now_iso(), **row}), ensure_ascii=False) + "\n")


def say(obj: dict) -> None:
    """Claude Code에 돌려줄 JSON을 표준 출력에 쓴다. 한국어는 유니코드 이스케이프로 내보내고 UTF-8 바이트로 써서
    Windows 기본 출력 인코딩(cp949)과 무관하게 깨지지 않게 한다."""
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def read_json(path: Path) -> dict | None:
    """여러 hook이 동시에 돌므로 반쯤 쓰인 파일을 읽을 수 있다. 몇 번 다시 읽고, 그래도 안 되면 None이다."""
    for _ in range(6):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def write_json(path: Path, data: dict) -> None:
    """임시 파일에 쓰고 바꿔치기한다. 다른 hook이 읽는 중에도 반쯤 쓰인 파일이 보이지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(clean(data), ensure_ascii=False, indent=2), encoding="utf-8")
    for _ in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    try:
        tmp.unlink()
    except OSError:
        pass


def project_for(cwd: str) -> tuple[str, str]:
    """cwd가 등록부의 어느 프로젝트 경로 아래인지 찾는다. 없으면 jipsa."""
    cwd_n = os.path.normcase(os.path.normpath(cwd or ""))
    best = ("jipsa", "doc")
    best_len = -1
    for toml in PROJECTS.glob("*.toml"):
        try:
            text = toml.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^path\s*=\s*['\"](.+?)['\"]", text, re.M)
        k = re.search(r"^kind\s*=\s*['\"](.+?)['\"]", text, re.M)
        if not m:
            continue
        p = os.path.normcase(os.path.normpath(m.group(1)))
        if (cwd_n == p or cwd_n.startswith(p + os.sep)) and len(p) > best_len:
            best, best_len = (toml.stem, k.group(1) if k else "doc"), len(p)
    return best


def cwd_matches(cwd: str, project: str) -> bool:
    """project_for가 기본값으로 jipsa를 준 것인지, 실제로 그 경로 아래인지 가른다. 화면은 맞지 않는 세션을 기타로 보낸다."""
    try:
        text = (PROJECTS / f"{project}.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.search(r"^path\s*=\s*['\"](.+?)['\"]", text, re.M)
    if not m:
        return False
    p, c = os.path.normcase(os.path.normpath(m.group(1))), os.path.normcase(os.path.normpath(cwd or ""))
    return c == p or c.startswith(p + os.sep)


def tool_summary(name: str, inp: dict) -> str:
    val = ""
    for k in _TOOL_KEYS:
        if isinstance(inp, dict) and inp.get(k):
            val = str(inp[k])
            break
    if name in ("Read", "Edit", "Write", "NotebookEdit") and val:
        val = val.replace("\\", "/").rsplit("/", 1)[-1]
    val = SLACK_URL.sub("[가림]", " ".join(val.split()))  # /jipsa-slack이 Webhook 주소를 명령으로 넘겨도 이벤트 기록에 남기지 않는다(261102-jipsa-34)
    return f"{name} {val[:90]}".strip()


def last_assistant_text(transcript: str) -> str:
    """세션 기록(jsonl)의 끝에서 Claude가 마지막으로 말한 문장을 읽는다. 지금 무엇을 하는지 한 줄로 쓰기 위해서다."""
    try:
        path = Path(transcript)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - 1_500_000))
            chunk = f.read().decode("utf-8", errors="ignore")
    except (OSError, TypeError, ValueError):
        return ""
    for line in reversed(chunk.splitlines()):
        if '"assistant"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") or {}
        if rec.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        texts = [c.get("text", "") for c in msg["content"] if c.get("type") == "text" and c.get("text", "").strip()]
        if texts:
            return " ".join(texts[-1].split())[:300]
    return ""


def last_turn(transcript: str) -> tuple[str, str]:
    """세션 기록(jsonl)에서 (마지막 답 전체, 이 턴의 promptId)를 읽는다.

    마지막 답은 마지막 도구 결과나 사람 입력 뒤에 Claude가 쓴 글을 모두 이은 것이다. 글자 수를 재기 위해서다.
    promptId는 턴마다 하나다. 사람 입력과 백그라운드 명령 종료 알림은 새 값을 받고, Stop hook이 막아 이어진 기록은 같은 값을 쓴다.
    """
    try:
        path = Path(transcript)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - 1_500_000))
            chunk = f.read().decode("utf-8", errors="ignore")
    except (OSError, TypeError, ValueError):
        return "", ""
    texts: list[str] = []
    bounded = False
    for line in reversed(chunk.splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        if rec.get("type") == "user":
            bounded = True  # 마지막 답의 앞 경계다. 여기부터는 턴 값만 찾는다
            if rec.get("promptId"):
                return "\n".join(texts).strip(), str(rec["promptId"])
            continue
        msg = rec.get("message") or {}
        if bounded or rec.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        texts[:0] = [c.get("text", "") for c in msg["content"] if c.get("type") == "text" and c.get("text", "").strip()]
    return "\n".join(texts).strip(), ""


def turn_begun(transcript: str, prompt_id: str) -> bool:
    """이 턴(같은 promptId)에 메인 세션이 jipsa begin이나 cycle next, cycle start로 작업을 열었는지 본다. 턴 값이 없으면 열지 않은 것으로 친다."""
    if not prompt_id:
        return False
    try:
        path = Path(transcript)
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - 1_500_000))
            chunk = f.read().decode("utf-8", errors="ignore")
    except (OSError, TypeError, ValueError):
        return False
    for line in reversed(chunk.splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        if rec.get("type") == "user" and rec.get("promptId") and str(rec["promptId"]) != prompt_id:
            return False  # 앞 턴이다
        msg = rec.get("message") or {}
        if rec.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for c in msg["content"]:  # 셸 도구의 명령 칸만 본다. 검색어나 지시문에 적힌 명령 이름은 작업을 연 것이 아니다
            if not (isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in ("Bash", "PowerShell")):
                continue
            inp = c.get("input") or {}
            if isinstance(inp, dict) and BEGIN_CALL.search(str(inp.get("command") or "")):
                return True
    return False


def chat_marker(text: str, begun: bool) -> str:
    """마지막 답에서 결론 문장 표지를 찾아 걸린 조각을 돌려준다. 없으면 빈 글이다.

    괄호 속(작업 제목, 들어온 답), 따옴표 속, 코드 표기는 실행 알림이 옮겨 적는 말이므로 보지 않는다. "1안(추천)"의 추천 표시만 먼저 살린다.
    다만 60자 이상이거나 문장 끝(다., 요., 니다.)을 담은 조각은 지우지 않는다. 결론 전체를 괄호나 따옴표로 감싸 지나가지 않게 한다.
    제안 표지는 그 턴에 작업을 열지 않았을 때만 본다. 연 작업을 알리며 선택지 이름을 적는 일이 있어서다.
    """
    if not CHAT_MARKERS or not text:
        return ""

    def drop(m):  # 짧은 이름 조각만 지운다
        seg = m.group(0)
        return " " if len(seg) < 60 and not re.search(r"(?:다|요)\s*[.!?。]", seg) else seg

    t = re.sub(r"[(（]\s*추천\s*[)）]", " 추천 ", text)
    t = re.sub(r"`[^`]*`", drop, t)
    for _ in range(2):  # 괄호가 겹친 경우
        t = re.sub(r"\([^()]*\)|（[^（）]*）|\"[^\"]*\"|“[^”]*”|'[^'\n]*'|‘[^’]*’", drop, t)
    for pat in VERDICT_MARKERS + (() if begun else PROPOSAL_MARKERS):
        for m in re.finditer(pat, t, re.M):
            if not fact_cause(t, m):
                return m.group(0).strip()
    return ""


def fact_cause(t: str, m) -> bool:
    """걸린 표지가 원인 접속이고 이은 말이 실패 사실 한 마디뿐이면 참이다. because는 뒤의 말을, 때문은 앞의 말을 같은 문장 안에서 본다."""
    if not CAUSE_WORD.fullmatch(m.group(0)):
        return False
    if m.group(0).lower() == "because":
        end = re.search(r"[.!?。\n;]", t[m.end():])
        clause = t[m.end():m.end() + end.start()] if end else t[m.end():]
    else:
        starts = [t.rfind(c, 0, m.start()) for c in ".!?。\n,"]
        clause = t[max(starts) + 1:m.start()]
    clause = clause.strip()
    return (len(clause) <= FACT_CLAUSE_MAX and bool(FAIL_FACT.search(clause)) and bool(TOOL_NOUN.search(clause))
            and not GUESS_WORDS.search(clause))


def ask_note(prompt: str) -> str:
    """사람 입력이 원인, 분석, 제안, 맞는지 확인 같은 묻는 말이면 결과지로 내라는 안내를 돌려준다. 단순 명령이면 빈 글이다(261025-jipsa-31)."""
    if not CHAT_MARKERS or not prompt or not ASK_WORDS.search(prompt):
        return ""
    if SIMPLE_PROMPTS.search(prompt) and not ASK_STRONG.search(prompt):
        return ""  # 상태 보기나 답 넣기다. 원인, 분석, 제안을 함께 물으면 묻는 말이 앞선다
    return ("[jipsa] 묻는 말이다. 원인, 분석, 판정(맞다, 아니다), 제안도 작업이다. jipsa begin으로 열어 서브에이전트가 결과지로 낸다. "
            "채팅에는 실행ID와 시작 또는 마감 사실 한 줄만 적고 답의 내용(원인, 판정, 선택지)은 적지 않는다.")


def link_children(run_id: str, response) -> None:
    """`jipsa begin`과 `jipsa record`가 찍은 실행ID를 찾아 그 기록에 parent_run(이 세션)을 적는다. 트리가 누가 누구를 시작했는지 잇는 근거다."""
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False) if response is not None else ""
    for child in set(re.findall(r"(?:시작 기록|들여옴): (\d{6}-[\w-]+-\d{2})", text)):
        meta = read_json(RUNS / child / "meta.json")
        if meta and not meta.get("parent_run"):
            meta["parent_run"] = run_id
            write_json(RUNS / child / "meta.json", meta)
            emit({"kind": "child_run", "run": run_id, "child": child})


def take_topic_done(meta: dict, response, command: str = "") -> bool:
    """`jipsa topic --done`이 찍은 "세션 주제 닫힘: 시각" 줄을 찾아 마지막 주제에 ended를 적고 걸린 주제를 비운다. 출력을 버린 실행이면 명령 줄에서 읽는다. 닫았으면 참이다."""
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False) if response is not None else ""
    found = re.findall(r"세션 주제 닫힘: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
    if not found and "주제 닫기 실패" not in text:  # 출력을 버린 실행이면 명령 줄에서 읽는다. 실패를 찍은 명령은 받지 않는다
        m = re.search(r"jipsa topic\s+--done(?:\s+--at[ =]+[\"']?([^\"';|&]+?)[\"']?)?\s*(?:[;|&>]|$)", command or "")
        if m:
            at = (m.group(1) or "").strip()
            try:
                t = datetime.now().replace(microsecond=0)
                if at:
                    t = datetime.combine(t.date(), datetime.strptime(at, "%H:%M").time()) if len(at) <= 5 else datetime.fromisoformat(at).replace(tzinfo=None)
                found = [t.isoformat(timespec="seconds")] if t <= datetime.now() else []
            except ValueError:
                found = []
    topics = meta.get("topics") or []
    if not found or not meta.get("topic") or not topics or topics[-1].get("ended"):
        return False  # 걸린 주제가 없거나 이미 닫혔다
    ended = max(found[-1], topics[-1].get("ts", ""))  # 주제 시작보다 앞으로 닫지 않는다
    topics[-1]["ended"] = ended
    meta["topic"] = ""
    meta["topic_project"] = ""
    meta["title"] = "Main 세션"  # 닫힌 주제 이름을 세션 제목으로 남기지 않는다
    return True


def take_topic(meta: dict, response, command: str = "") -> str:
    """`jipsa topic`이 찍은 "세션 주제: ..." 줄을 찾아 세션 기록의 주제로 건다. 출력을 버린 실행이면 명령 줄에서 읽는다. 바뀌었으면 새 주제를 돌려준다."""
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False) if response is not None else ""
    found = re.findall(r"세션 주제: ([^\n\r\"\\|]+?) \| 프로젝트: ([^\s\"\\]+)", text)
    if not found:  # 출력을 버린 실행이면 명령 줄에서 읽는다
        m = re.search(r"jipsa topic\s+[\"']([^\"'\n]+)[\"']\s+--project[ =]+[\"']?([^\s\"';|&]+)", command or "")
        found = [m.groups()] if m and (m.group(2) == "기타" or (PROJECTS / f"{m.group(2)}.toml").exists()) else []  # 거절된 명령은 받지 않는다
    if not found:
        return ""
    topic, project = found[-1][0].strip()[:40], found[-1][1].strip()
    if "{" in topic or "{" in project:
        return ""  # 코드 안의 서식 문자열이 응답에 섞인 것이다. 실제 주제가 아니다
    if not topic or (topic == meta.get("topic") and project == meta.get("topic_project")):
        return ""
    meta["topic"] = topic
    meta["topic_project"] = project
    meta["title"] = topic
    meta.setdefault("topics", []).append({"ts": now_iso(), "segment": int(meta.get("turn", 0)) or 1, "title": topic, "project": project})
    return topic


def parent_open(session_run: str) -> bool:
    """답의 부모 세션 기록이 아직 열려 있는지. SessionEnd가 완료로 닫으므로 진행 중이면 열린 것이다. record.session_open과 같은 규칙이다."""
    meta = read_json(RUNS / session_run / "meta.json") if session_run else None
    return bool(meta) and meta.get("status") == "진행 중"


def draftask():
    """초안 판별 모듈(표준 라이브러리만 쓴다). '초안'이 든 글에서만 들인다."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scheduler import draftask as d

    return d


def draft_note(meta: dict, text: str, via: str) -> str:
    """사람 입력에 '초안'이 있으면 세션 기록에 초안 요청을 남기고, 결과지 초안이면 안내 줄을 돌려준다(261029-jipsa-35)."""
    if "초안" not in (text or ""):
        return ""
    d = draftask()
    return d.note(d.remember(meta, text, via))


def take_inbox(run_id: str, meta: dict | None = None) -> str:
    """이 세션에 넘길 답을 꺼내 전달 표시를 하고 안내문을 돌려준다. 부모 세션이 열려 있으면 그 세션이 우선이고 2분이 지나면 어느 세션이든 받는다.
    부모 세션이 끝났으면 붙들지 않고 바로 받는다(261031-jipsa-01).
    meta를 주면 답에 든 초안 요청을 그 세션 기록에 남기고 결과지 초안이면 안내 줄을 붙인다. 쓰기는 부른 쪽이 한다."""
    try:
        rows = [json.loads(l) for l in INBOX.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return ""
    mine, changed, parents = [], False, {}
    for r in rows:
        if r.get("delivered") or r.get("worker"):
            continue
        age = (datetime.now() - datetime.fromisoformat(r["ts"])).total_seconds()
        parent = r.get("parent_run") or ""
        if parent and parent != run_id and age < 120:
            if parent not in parents:
                parents[parent] = parent_open(parent)
            if parents[parent]:
                continue
        r["delivered"] = now_iso()
        r["delivered_to"] = run_id
        mine.append(r)
        changed = True
    if changed:
        tmp = INBOX.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        os.replace(tmp, INBOX)
    if not mine:
        return ""
    dos = [r for r in mine if r.get("kind") == "do"]  # 대시보드 Do와 jipsa todo run이 세션에 보낸 할 일 줄(261026-jipsa-26)
    mine = [r for r in mine if r.get("kind") != "do"]
    lines = []
    if dos:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scheduler import sessionproc  # 표준 라이브러리와 psutil만 쓰는 모듈이다

        lines += sessionproc.do_lines(dos)
    if mine:
        lines.append("[jipsa] 대시보드 결과지에 답이 들어왔다. 이 답대로 이어서 처리하고, 결과를 jipsa 기록에 남긴다(새 작업이면 jipsa begin으로 시작, 끝나면 finish).")
    for r in mine:
        lines.append(f"- {r['run_id']} ({r.get('project')} / {r.get('title')}): 답 \"{r['answer']}\"" + (f" (고른 안: {r['picked']})" if r.get("picked") else "")
                     + f". 보고서는 runs/{r['run_id']}/attempt-1/report.md다.")
    if meta is not None and any("초안" in str(r.get("answer") or "") for r in mine):
        _, text = draftask().from_answers(mine)
        line = draft_note(meta, text, "answer")
        if line:
            lines.append(line)
    lines.append("처리를 서브에이전트에 넘긴 뒤 답 대기 명령이 떠 있지 않으면 다시 백그라운드로 띄운다.")
    return "\n".join(lines)


def stop_warnings(data: dict, meta: dict, run_id: str) -> tuple[list[str], dict]:
    """메인 세션의 턴 끝에서 낼 경고. 답 대기 명령이 없음(1안)과 마지막 답이 한도를 넘음(나안)이다(261025-jipsa-13).
    한도 안이라도 마지막 답에 결론 문장 표지가 있으면 같은 방식으로 막는다(261025-jipsa-31).

    턴마다 한 번만 막는다. 턴은 세션 기록의 promptId로 가른다. 사람 입력이든 백그라운드 명령 종료 알림이든 새 턴은 새 값을 받고,
    막혀서 이어진 기록은 같은 값을 쓴다. 막은 턴의 값을 meta에 남겨 같은 턴의 두 번째 Stop은 통과시킨다. 값을 읽지 못하면 깨어남 수로 가른다.
    서브에이전트의 Stop, 앞 Stop hook이 막아서 이어진 Stop, `claude -p` 작업자 세션에는 내지 않는다.
    """
    if data.get("agent_id") or data.get("stop_hook_active"):
        return [], {}
    text, prompt_id = last_turn(data.get("transcript_path") or meta.get("transcript", ""))
    turn = prompt_id or f"wake-{int(meta.get('wake', 0))}"
    if meta.get("warned_turn") == turn:
        return [], {}
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from scheduler import sessionproc  # psutil을 쓰므로 여기서만 들인다
    except Exception:  # noqa: BLE001 - 들이지 못하면 대기 명령 검사만 건너뛴다
        sessionproc = None
    claude = sessionproc.claude_proc() if sessionproc else None
    if claude is not None and sessionproc.is_print_mode(claude):
        return [], {}
    out, info = [], {"turn": turn}
    text = str(data.get("last_assistant_message") or "").strip() or text
    n = len(text)
    if n > CHAT_LIMIT:
        out.append(f"[jipsa] 답이 {n}자다. 결론과 분석은 결과지로 낸다. 채팅에는 실행ID와 시작 또는 마감 사실 한 줄만 쓴다.")
        info["chars"] = n
    elif CHAT_MARKERS:  # 짧아도 결론 문장 꼴이면 막는다(261025-jipsa-31)
        begun = turn_begun(data.get("transcript_path") or meta.get("transcript", ""), prompt_id)
        mark = chat_marker(text, begun)
        if mark:
            out.append(f"[jipsa] 답에 결론 문장(\"{mark[:20]}\")이 있다. 원인, 판정, 제안은 채팅에 쓰지 않고 결과지로 낸다"
                       + ("(이 턴에 연 작업의 결과지가 낸다)" if begun else "(jipsa begin으로 열어 서브에이전트에 맡긴다)")
                       + ". 채팅에는 실행ID와 시작 또는 마감 사실 한 줄만 다시 쓴다.")
            info.update(marker=mark[:20], begun=begun)
    if claude is not None:
        line = sessionproc.missing_wait_line(run_id)
        if line:
            out.append(line)
            info["wait_missing"] = True
    return out, info


def is_dashboard_on(prompt: str) -> bool:
    """"jipsa 온"만 친 턴이다. 대시보드를 켜기만 하는 말이므로 세션 기록을 만들지 않는다. 앞뒤 공백과 따옴표는 무시한다."""
    return " ".join(prompt.strip().strip("\"'`“”‘’「」").split()) == "jipsa 온"


def main() -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")  # 깨진 바이트가 와도 죽지 않는다
    data = json.loads(raw) if raw.strip() else {}
    event = data.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "")
    sid = str(data.get("session_id") or "unknown")
    run_id = f"session-{sid[:8]}"
    run_dir = RUNS / run_id
    meta = read_json(run_dir / "meta.json")
    if event == "UserPromptSubmit" and is_dashboard_on(str(data.get("prompt") or "")):
        # 대시보드만 켜는 턴이다. 기록을 새로 열지 않고 진행 중으로 올리지 않는다. 쉬는 동안 답을 받을 대기 명령을 알려 준다.
        # 세션이 없는 동안 받은편지함에 쌓인 답은 이 턴에 같이 넘긴다. 대기 명령을 띄울 때까지 기다리지 않는다(261031-jipsa-01)
        note = take_inbox(run_id)
        if note:
            emit({"kind": "inbox_delivered", "run": run_id, "via": "prompt"})
        say({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
             f"[jipsa] 이 세션의 기록 id는 {run_id}다. 답 대기 명령: uv run jipsa wait-answer --session {run_id} --timeout 0" + (chr(10) + note if note else "")}})
        return
    cwd = data.get("cwd") or os.getcwd()
    if meta is None and (run_dir / "meta.json").exists():
        return  # 다른 hook이 쓰는 중이다. 이 이벤트 하나는 버린다. 세션을 새로 만들지 않는다
    if meta is None and event in ("SessionEnd", "Stop", "SubagentStop"):
        return  # hook을 켜기 전에 시작한 세션이 끝나는 것이다. 턴도 도구도 없는 빈 기록을 만들지 않는다

    if meta is None or event == "SessionStart":
        if meta is None:
            project, kind = project_for(cwd)
            meta = {
                "run_id": run_id, "project": project, "title": f"세션 {Path(cwd).name}", "criteria": "", "kind": kind,
                "executor": "session", "model": "", "started": now_iso(), "report_date": datetime.now().date().isoformat(),
                "status": "진행 중", "minutes_limit": 0, "minutes_used": 0, "attempts": [], "dry_run": False, "mode": "",
                "cwd": cwd, "cwd_project": project if cwd_matches(cwd, project) else "", "session_id": sid, "turn": 0, "tools": 0, "transcript": data.get("transcript_path", ""),
            }
            write_json(run_dir / "meta.json", meta)
            (run_dir / "attempt-1").mkdir(parents=True, exist_ok=True)
            emit({"kind": "run_start", "run": run_id, "project": project, "title": meta["title"], "project_kind": kind, "limit": 0, "executor": "session"})
            emit({"kind": "stage_start", "run": run_id, "attempt": 1, "stage": "run"})
        if event == "SessionStart":
            return

    base = {"run": run_id, "attempt": 1, "stage": "run"}
    if event == "UserPromptSubmit":
        prompt = " ".join(re.sub(r"\[Image #\d+\]", "", str(data.get("prompt") or "")).split())  # 붙인 그림 표시는 뺀다
        meta["wake"] = int(meta.get("wake", 0)) + 1  # 시스템 알림으로 깨어난 것도 센다. 세션 기록에서 턴 값을 읽지 못할 때 턴 끝 경고의 기준이다
        if prompt.startswith(("<task-notification>", "<system", "[SYSTEM", "<cross-session", "<teammate")):
            write_json(run_dir / "meta.json", meta)
            return  # 사람이 친 말이 아니라 시스템이 넣은 알림이다. 턴으로 세지 않는다
        meta["turn"] = int(meta.get("turn", 0)) + 1
        if meta["turn"] == 1 and prompt and not meta.get("topic"):
            meta["title"] = prompt[:60]
        meta["last_prompt"] = prompt[:200]
        meta["segment_open"] = True
        meta["now"] = ""
        before = meta.get("draft_ask")
        draft = draft_note(meta, prompt, "prompt")  # '초안'이면 요청을 남긴다(261029-jipsa-35)
        note = take_inbox(run_id, meta)
        write_json(run_dir / "meta.json", meta)
        emit({"kind": "segment_start", **base, "segment": meta["turn"], "prompt": prompt[:120]})
        if note:  # 다음 입력에 답을 덧붙인다
            emit({"kind": "inbox_delivered", "run": run_id, "via": "prompt"})
        if meta.get("draft_ask") is not before:
            emit({"kind": "draft_ask", "run": run_id, "draft": meta["draft_ask"]["kind"], "via": meta["draft_ask"]["via"]})
        ask = ask_note(prompt)  # 묻는 말이면 결과지로 내라는 안내를 덧붙인다
        if note or ask or draft:
            say({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(x for x in (draft, note, ask) if x)}})
    elif event == "PostToolUse":
        name = str(data.get("tool_name") or "?")
        if name == "Agent":
            return  # 서브에이전트는 SubagentStart와 SubagentStop이 적는다. 끝날 때 한 번 더 적지 않는다
        seg = int(meta.get("turn", 0)) or 1
        if not meta.get("segment_open"):
            meta["turn"] = seg
            meta["segment_open"] = True
            emit({"kind": "segment_start", **base, "segment": seg})
        meta["tools"] = int(meta.get("tools", 0)) + 1
        if not data.get("agent_id"):
            said = last_assistant_text(data.get("transcript_path") or meta.get("transcript", ""))
            if said:
                meta["now"] = said
        inp = data.get("tool_input") or {}
        cmd = str(inp.get("command") or "") if isinstance(inp, dict) else ""
        topic = take_topic(meta, data.get("tool_response"), cmd) if name in ("Bash", "PowerShell") else ""
        closed = take_topic_done(meta, data.get("tool_response"), cmd) if name in ("Bash", "PowerShell") and not topic else False
        write_json(run_dir / "meta.json", meta)
        if topic:
            emit({"kind": "topic", "run": run_id, "segment": seg, "title": topic})
        if closed:
            emit({"kind": "topic_done", "run": run_id, "segment": seg, "ended": meta["topics"][-1]["ended"]})
        row = {"kind": "tool", **base, "segment": seg, "tool": name, "summary": tool_summary(name, data.get("tool_input") or {}),
               "tool_id": str(data.get("tool_use_id") or f"t{meta['tools']}")}
        if data.get("agent_id"):
            row["parent"] = str(data["agent_id"])
        emit(row)
        if name in ("Bash", "PowerShell"):
            link_children(run_id, data.get("tool_response"))
    elif event == "SubagentStart":
        seg = int(meta.get("turn", 0)) or 1
        emit({"kind": "tool", **base, "segment": seg, "tool": "Agent", "summary": f"Agent {data.get('agent_type') or ''}".strip(),
              "tool_id": str(data.get("agent_id") or "")})
    elif event == "SubagentStop":
        emit({"kind": "agent_end", **base, "tool_id": str(data.get("agent_id") or "")})
    elif event == "Stop":
        note = take_inbox(run_id, meta)
        if note:  # 턴을 끝내려는 세션을 붙잡아 답을 처리하게 한다. 전달 표시를 했으므로 다음 Stop에서는 보내지 않는다
            write_json(run_dir / "meta.json", meta)  # 답에 든 초안 요청을 남긴다
            emit({"kind": "inbox_delivered", "run": run_id, "via": "stop"})
            say({"decision": "block", "reason": note})
            return
        warns, info = stop_warnings(data, meta, run_id)
        if warns:  # 같은 깨어남에서 다시 막지 않게 표시하고 한 번 막는다
            meta["warned_turn"] = info.pop("turn")
            write_json(run_dir / "meta.json", meta)
            emit({"kind": "stop_warn", "run": run_id, **info})
            say({"decision": "block", "reason": "\n".join(warns)})
            return
        if meta.get("segment_open"):
            meta["segment_open"] = False
            write_json(run_dir / "meta.json", meta)
            emit({"kind": "segment_end", **base, "segment": int(meta.get("turn", 0)) or 1, "verdict": "턴 끝", "turns": 1})
    elif event == "SessionEnd":
        seg = int(meta.get("turn", 0)) or 1
        if meta.get("segment_open"):
            emit({"kind": "segment_end", **base, "segment": seg, "verdict": "세션 종료", "turns": 1})
        started = datetime.fromisoformat(meta["started"])
        minutes = max(0, int((datetime.now() - started).total_seconds() // 60))
        emit({"kind": "stage_end", **base, "status": "완료", "minutes": minutes})
        meta.update(status="완료", finished=now_iso(), minutes_used=minutes, segment_open=False,
                    summary=f"세션 종료({data.get('reason') or '종료'}). 턴 {meta.get('turn', 0)}회, 도구 호출 {meta.get('tools', 0)}회",
                    evidence_ref=f"runs/{run_id}")
        write_json(run_dir / "meta.json", meta)
        emit({"kind": "run_end", "run": run_id, "status": "완료", "minutes": minutes, "evidence": meta["evidence_ref"]})
        # 이 세션의 줄을 runs/ 아래로 옮긴다(scheduler.events.move_run과 같은 규칙)
        try:
            rows = [json.loads(l) for l in EVENTS.read_text(encoding="utf-8").splitlines() if l.strip()]
            mine = [r for r in rows if r.get("run") == run_id]
            rest = [r for r in rows if r.get("run") != run_id]
            with (run_dir / "attempt-1" / "events.jsonl").open("a", encoding="utf-8") as f:
                for r in mine:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            EVENTS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rest), encoding="utf-8")
        except (OSError, ValueError):
            pass
        sheet = [f"# 결과지 | {meta['project']} | {meta['title']} | 완료", "", f"- 실행ID: {run_id}", "- 실행 주체: 세션",
                 f"- 시간: {meta['started'][:16].replace('T', ' ')} ~ {meta['finished'][11:16]} ({minutes}분)", f"- 결과: {meta['summary']}",
                 f"- 작업 폴더: {meta.get('cwd', '')}", f"- 기록: {meta.get('transcript', '')}", ""]
        (run_dir / "result.md").write_text("\n".join(sheet), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - hook 오류가 세션을 막지 않는다
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            with (STATE / "hook_errors.log").open("a", encoding="utf-8") as f:
                f.write(f"{now_iso()} {type(e).__name__}: {e}\n")
        except OSError:
            pass
    sys.exit(0)
