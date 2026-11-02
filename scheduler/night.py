"""옛 Auto 종합 보고 가리키기(261023-jipsa-39에서 만들고 261025-jipsa-42에서 만들기를 뗐다).

새 Auto(scheduler/auto.py)는 Auto 종합 보고를 만들지 않는다. 지난 Auto 구간에 만든 보고는 상태 폴더 night.json에 날짜별 실행ID로 남아 있고,
그날 보고(report.build)와 끝난 옛 cycle 기록(cycle.final_view)이 그 실행 하나를 가리킬 때만 이 모듈을 읽는다.
보고를 만드는 코드(open_report, rows, table)와 옛 범위 문법 경고(old_syntax)는 주간 계획 파일과 범위 계약을 읽어 함께 뗐다.
"""

from __future__ import annotations

import json

from scheduler import record
from scheduler.config import STATE

NIGHT_FILE = STATE / "night.json"  # 날짜 -> Auto 종합 보고 실행ID
TITLE = "Auto 종합 보고"


def _load() -> dict:
    try:
        return json.loads(NIGHT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def report_run(date: str, since: str = "") -> str:
    """그 날짜의 Auto 종합 보고 실행ID. 없으면 빈 값이다.
    since(Auto를 켠 시각)를 주면 그 구간의 보고만 찾는다. 같은 날 Auto를 여러 번 켜면 구간마다 보고가 따로 있어 날짜만으로는 다른 구간의 보고를 가리킬 수 있다(261025-jipsa-03).
    since가 없으면 그 날짜의 마지막 것이다."""
    data = _load()
    keys = sorted(k for k in data if k == date or k.startswith(date + " "))
    if since:
        for k in reversed(keys):
            rid = str(data[k] or "")
            if rid and (record.meta_of(rid) or {}).get("auto_since") == since:
                return rid
        return ""
    return str(data[keys[-1]] or "") if keys else ""


def slack_line(date: str) -> str:
    rid = report_run(date)
    if not rid:
        return ""
    meta = record.meta_of(rid) or {}
    return f"Auto 종합 보고 {rid}: {meta.get('summary', '')[:80]} 확인 필요는 이 하나와 예외만 남긴다."
