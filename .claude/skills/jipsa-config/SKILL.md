---
name: jipsa-config
description: 일반 설정과 되돌리기. 사용자가 "/jipsa-config", "/jipsa-config show", "/jipsa-config undo", "동시 작업 수 바꿔 줘", "설정 되돌려 줘"라고 하면 동시 작업 수, 자동 작업 동시 수, Ollama 주소, 자료 폴더를 질문으로 받아 jipsa settings 명령으로 쓴다.
---

# jipsa-config

다른 스킬에 들지 않는 전역 값 4개를 묻는다. 인자는 없거나 `show`(`보기`) 또는 `undo`(`되돌리기`)다.

- `show`는 `uv run jipsa settings show --skill config` 출력만 보이고 묻지 않는다.
- `undo`는 설정 파일을 직전 판과 맞바꾼다. `uv run jipsa settings show`로 전 값을 읽고 `uv run jipsa settings undo`를 돌린 뒤 다시 읽어 바뀐 칸을 보인다. 한 번 더 하면 다시 돌아온다. 끝나면 아래 다시 띄우기를 묻는다. /jipsa-model, /jipsa-slack, /jipsa-cleanup이 저장한 값도 같은 설정 파일이라 같이 되돌아간다. Slack 연결 주소와 알림 켜짐은 다른 파일이라 되돌아가지 않는다.

## 같이 지키는 규칙

- 질문은 한 번에 하나다. 질문마다 지금 값(없으면 기본값)을 보이고, 빈 답(엔터)은 그 값을 그대로 둔다. "그만"이라고 답하면 저장하지 않고 끝낸다.
- 잘못 답하면 까닭과 고를 수 있는 값을 보이고 한 번 다시 묻는다. 두 번째도 틀리면 그 칸은 지금 값으로 두고 다음 질문으로 넘어가며 끝 요약에 "건너뜀"으로 적는다. 값 검사는 저장 명령의 검사 동작(`check`, `--check`)에 맡기고 거절 문구를 그대로 까닭으로 보인다.
- 뜻이 분명해도 사람이 적지 않은 값을 스스로 고르지 않는다. "실험"처럼 영어 이름과 다르게 답하면 그렇게 읽어도 되는지 되묻는다.
- 환경 변수가 덮은 칸(`show` 출력에 "환경 변수가 앞선다"가 붙은 칸)은 묻지 않고 "환경 변수가 앞선다. .env를 고쳐야 바뀐다"고 알린다.
- 묻지 않은 칸은 기본값으로 둔다. 끝에 바뀐 칸만 표로 보이고 "이대로 저장할까"를 묻는다. 예라고 답할 때만 저장한다.
- 이 폴더(jipsa)에서 명령을 돌리고 서브에이전트를 띄우지 않는다. 설정 파일과 등록 toml을 직접 고치지 않고 명령으로만 쓴다. 쓰는 명령은 메인 세션 전용이다.
- 명령은 값마다 작은따옴표로 감싼다. 값 안의 작은따옴표는 셸에 맞게 바꾼다. PowerShell은 `''`처럼 두 번 겹치고, bash는 `'\''`로 쓴다.

## 질문

`uv run jipsa settings show --skill config`로 지금 값을 읽어 "일반 설정이다. 지금 값: ..."으로 시작한다.

1. 스케줄러가 한 번에 돌리는 작업 수 상한은? 1~20이다. 키는 `JIPSA_CONCURRENCY`다.
2. 사람 없이 이어지는 자동 작업(Cycle) 단계를 동시에 몇 개까지 돌릴까? 1~20이다. 키는 `JIPSA_AUTO_CAP`이다.
3. Ollama 서버 주소는? http로 시작한다. 키는 `JIPSA_OLLAMA_URL`이다.
4. 서칭 단계가 웹보다 먼저 뒤지는 로컬 자료 폴더는? `이름=경로;이름=경로` 꼴이고 비우면 웹만 본다. 키는 `JIPSA_SEARCH_SOURCES`다.

답마다 `uv run jipsa settings check '<키>=<값>'`로 검사한다.

## 저장

바뀐 칸만 전후로 보이고 "이대로 저장할까?"를 묻는다. 예면 바뀐 칸을 쓴다.

```
uv run jipsa settings set '<키>=<값>' '<키>=<값>'
```

## 다시 띄우기

저장한 값은 스케줄러와 대시보드를 다시 띄워야 반영된다. 저장을 끝내면 `uv run jipsa settings show --skill config` 둘째 줄의 실행 중 작업 수를 보이고 "지금 다시 띄울까"를 묻는다. 기본값은 아니오다.

- 예이고 실행 중 작업이 0개면 `uv run jipsa settings restart`를 돌리고 출력을 보인다.
- 실행 중 작업이 있으면 "다시 띄우면 그 작업이 끊긴다"고 먼저 알린다. 그래도 예라고 답할 때만 `uv run jipsa settings restart --force`를 돌린다.
- 아니오면 "다음에 스케줄러가 다시 뜰 때 반영된다"고 알린다. 돌고 있는 작업은 전 값으로 끝난다고 덧붙인다.

## 사용 예

```
/jipsa-config
/jipsa-config show
/jipsa-config undo
```
