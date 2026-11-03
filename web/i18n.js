/* jipsa 대시보드 화면 글자 사전(261103-misc-14). 한국어 원문이 키이고 ko 값은 키 그대로, en 값은 아래 표다.
   같은 한국어가 뜻이 갈리면 "멈춤||poll"처럼 || 뒤에 갈래를 붙이고 ko 화면은 || 앞만 보인다.
   상태 값(완료, 실패, 확인 필요 등)은 저장 데이터와 비교 코드와 CSS 선택자에서 그대로 쓰고, 화면에 보일 때만 이 사전을 지난다.
   결과지 본문은 사전에 넣지 않는다. 서버가 보내는 문구(경고, Cycle 위치, 표 머리, 오늘 보고 라벨)는 아래 SRV와 틀 표로 그릴 때만 바꾼다(261103-misc-17). 언어는 html lang 속성 하나로 정하고 index.html 머리가 첫 그리기 전에 넣는다 */
(() => {
  const EN = {
    "완료": "Done",
    "실패": "Failed",
    "확인 필요": "Needs attention",
    "판단 대기": "Needs attention",
    "진행 중": "Running",
    "대기": "Queued",
    "건너뜀": "Skipped",
    "멈춤": "Stalled",
    "확인함": "Acknowledged",
    "끝": "Ended",
    "거절": "Rejected",
    "확인 필요(실패)": "Needs attention (failed)",
    "답 대기": "Awaiting answer",
    "종합 보고": "Final report",
    "jipsa 대시보드": "jipsa dashboard",
    "지금 현황": "Current status",
    "동시 Cycle": "Concurrent Cycles",
    "GPU나 RAM이 모자라 기다리는 줄 수. 누르면 TODO 탭의 자원으로 간다": "Lines waiting for GPU or RAM. Click to open resources in the TODO tab",
    "GPU 대기": "GPU queue",
    "오늘 보고": "Daily report",
    "새로고침 주기, Slack 알림, GPU 대기": "Refresh interval, Slack notifications, GPU queue",
    "설정": "Settings",
    "새로고침": "Refresh",
    "새로고침 주기": "Refresh interval",
    "5초": "5 s",
    "15초": "15 s",
    "30초": "30 s",
    "60초": "60 s",
    "멈춤||poll": "Paused",
    "Slack 알림": "Slack notifications",
    "Slack 알림 켜짐/꺼짐": "Slack notifications on/off",
    "누르면 TODO 탭의 자원으로 간다": "Click to open resources in the TODO tab",
    "열기": "Open",
    "사용 창과 자원": "Usage windows and resources",
    "화면": "Views",
    "현황판": "Board",
    "타임라인": "Timeline",
    "쉬는 프로젝트": "Idle projects",
    "오늘 끝난 일": "Finished today",
    "오늘 보고 전체": "Full daily report",
    "오늘 끝난 일이 아직 없다.": "Nothing has finished today yet.",
    "지난 날짜 기록은 타임라인 탭에서 본다. 실시간을 누르면 돌아온다.": "Past dates are shown in the Timeline tab. Click Live to come back.",
    "재생": "Play",
    "재생 위치": "Playback position",
    "재생 속도": "Playback speed",
    "1분/초": "1 min/s",
    "5분/초": "5 min/s",
    "15분/초": "15 min/s",
    "보이는 시간 범위": "Visible time range",
    "최근 1시간": "Last 1 h",
    "최근 3시간": "Last 3 h",
    "최근 6시간": "Last 6 h",
    "최근 12시간": "Last 12 h",
    "최근 24시간": "Last 24 h",
    "상태 필터, 칩 색이 막대 색이다": "Status filter, chip color is the bar color",
    "진행 중 작업. 진행, 결과 분석, 서칭 단계 이름은 막대에 마우스를 올리면 보인다": "Running jobs. Hover a bar to see the stage name (run, analysis, search)",
    "끝났고 확인한 작업": "Finished and acknowledged jobs",
    "실패한 작업": "Failed jobs",
    "사람이 확인할 작업이다. 답을 넣을 작업(상태 값 확인 필요)과 끝났는데 아직 확인하지 않은 완료와 실패가 든다. 막대를 눌러 결과지 서랍에서 확인하거나 답을 넣으면 완료가 된다. 답을 넣을 작업은 막대 툴팁과 오른쪽 상태 칸의 물음표로 보인다. 확인하지 않은 실패는 빨간 막대에 주황 테두리다": "Jobs a person should check: jobs that need an answer (status Needs attention) and finished Done or Failed jobs not yet acknowledged. Click a bar and acknowledge or answer in the result drawer to make it Done. Jobs that need an answer show a question mark in the bar tooltip and the status column. An unacknowledged failure is a red bar with an orange border",
    "나머지 표식 설명": "Other markers",
    "타임라인 표식 설명": "Timeline markers",
    "대기: 자원이나 한도를 기다린 구간": "Queued: time spent waiting for resources or limits",
    "서브에이전트: 막대 아래 얇은 선, 진행 중이면 파랑": "Subagent: thin line under the bar, blue while running",
    "재시도: 같은 작업을 다시 시도한 시각": "Retry: when the same job was tried again",
    "Auto 마감: Auto 모드가 새 Cycle을 멈추는 시각": "Auto cutoff: when Auto mode stops starting new Cycles",
    "확인 필요(실패): 빨간 막대에 주황 테두리": "Needs attention (failed): red bar with an orange border",
    "진행 중 단계 이름은 막대에 마우스를 올리면 보인다": "Hover a running bar to see its stage name",
    "목표 줄: 목표 cycle마다 한 줄이고 머리에 지금 위치를 적는다. 아래에 Cycle N마다 이행과 분석이 놓이고 맨 끝에 종합 보고 줄이 붙는다. 다음 단계로 넘어간 단계는 자동 확인되어 초록이고, 확인 필요는 종합 보고 줄과 사람이 볼 예외 단계에만 남는다": "Goal row: one row per goal cycle with its current position at the head. Below it, each Cycle N holds its run and analysis steps, and a final report row comes last. A step that moved on is acknowledged automatically and turns green; Needs attention stays only on the final report row and on exception steps a person should see",
    "항목 줄: 프로젝트 줄 아래 항목마다 한 줄이고 검수와 반영은 원 실행 줄에 놓인다": "Item row: one row per item under the project row; review and apply steps sit on the original run row",
    "최근 24시간에 실행 기록이 없다. 날짜 선택에서 지난 날짜나 데모를 고른다.": "No runs in the last 24 hours. Pick a past date or the demo from the date picker.",
    "할 일과 도는 Cycle과 메모": "To-dos, running Cycles and memos",
    "대기열과 예약과 Cycle 요약": "Queue, scheduled and Cycle summary",
    "대기열과 예약": "Queue and scheduled",
    "할 일": "To-do",
    "할 일 고르기": "Filter to-dos",
    "전체": "All",
    "프로젝트": "Project",
    "할 일 한 줄": "One-line to-do",
    "할 일 한 줄 | 기준(선택)": "One-line to-do | criteria (optional)",
    "형식은 할 일 | 기준 | cycle 지표 목표값 이상 상한 N | 한도 VRAM 6GB, RAM 12GB이고 기준부터는 모두 선택이다. cycle 미정이면 첫 분석이 지표와 목표값을 정한다. 넣어도 돌지 않는다": "Format: to-do | criteria | cycle metric target 이상 상한 N | 한도 VRAM 6GB, RAM 12GB; everything from criteria on is optional. The Korean words are syntax: 이상 means at least (이하, at most), 상한 N stops after N Cycles without gain, 한도 sets resource limits, and with cycle 미정 (undecided) the first analysis sets the metric and target. Adding does not start it",
    "넣기": "Add",
    "새 프로젝트 이름": "New project name",
    "새 프로젝트 이름 (영문 소문자, 숫자, 밑줄)": "New project name (lowercase letters, digits, underscore)",
    "이름 하나로 jipsa 저장소와 나란한 폴더, git 첫 커밋, 등록까지 만든다": "One name creates a folder next to the jipsa repository, the first git commit and the registry entry",
    "프로젝트 만들기": "Create project",
    "닫기": "Close",
    "메모": "Memos",
    "메모 한 줄": "One-line memo",
    "떠오른 일 한 줄": "Something that came to mind",
    "메모는 돌지 않는다. 프로젝트와 기준은 할 일로 올릴 때 붙인다": "Memos do not run. Add the project and criteria when you move it to a to-do",
    "보고서": "Report",
    "초안 실행. 결과지가 아니라 초안 보기로 여는 HTML이 결과물이다": "Draft run. The deliverable is the HTML opened with Draft view, not the result sheet",
    "초안": "Draft",
    "전체 보기": "Show all",
    "초안 보기": "Draft view",
    "미리보기 꺼짐": "Preview off",
    "확인 필요, 답을 넣을 것. 선택지를 누르거나 직접 적는다.": "Needs attention, an answer is required. Click an option or type your own.",
    "답": "Answer",
    "답 넣기": "Submit answer",
    "Ctrl+Enter로 넣기, Enter는 줄바꿈, 그림은 Ctrl+V나 Alt+V로 붙인다": "Ctrl+Enter submits, Enter adds a line, paste images with Ctrl+V or Alt+V",
    "결과지 본문은 작업자가 한국어로 쓴 원문이라 번역하지 않는다.": "The result sheet body is the original Korean written by the worker and is not translated.",
    "원문 열기": "Open original",
    "진행": "Run",
    "Sol 공격": "Sol attack",
    "서칭": "Search",
    "공격 답과 보고서 수정": "Attack reply and report fix",
    "스케줄러 작업자": "Scheduler worker",
    "세션 서브에이전트": "Session subagent",
    "Main 세션": "Main session",
    "손으로 들여옴": "Imported by hand",
    "{n}분": "{n} min",
    "{n}분, 상한 {limit}분 넘김": "{n} min, over the {limit} min limit",
    "{n}분/{limit}분": "{n}/{limit} min",
    "{text}, 새 판 마감 {at}": "{text}, new rounds close at {at}",
    "기타": "Misc",
    "Main 세션 {t}": "Main session {t}",
    "답 들어감, 처리 대기": "Answer in, waiting to be processed",
    "확인함(답 없이 확인, 상태 값과 큐 보류는 그대로)": "Acknowledged (no answer; status and queue hold unchanged)",
    "확인 필요, 답을 넣을 것": "Needs attention, an answer is required",
    "목표 {t}": "Goal {t}",
    "Cycle 미상": "Cycle unknown",
    "서브에이전트": "Subagent",
    "필터에 맞는 항목이 없다.": "No items match the filter.",
    "프로젝트별 타임라인": "Timeline by project",
    "종료 {t}": "End {t}",
    "Auto 마감": "Auto cutoff",
    "Auto 모드가 새 Cycle을 멈추는 시각": "When Auto mode stops starting new Cycles",
    "끝난 일 접기": "Collapse finished",
    "끝난 일 펼치기": "Expand finished",
    "한도 대기": "Limit wait",
    "자원 대기": "Resource wait",
    "사유": "Reason",
    "상태": "Status",
    "{n}분 무활동. 띄운 세션에 깨우라고 알렸다": "Idle for {n} min. The session that started it was asked to wake up",
    "판 수 상한": "Round limit",
    "결과": "Result",
    "주체": "Owner",
    "{s} (시도 {n})": "{s} (attempt {n})",
    "하위 도구": "Child tools",
    "{n}개": "{n}",
    "재시도": "Retry",
    "시도 {n}": "attempt {n}",
    "원인": "Cause",
    "진행 중 {n}건": "Running {n}",
    "  멈춤 {n}건": "  Stalled {n}",
    "접기": "Collapse",
    "펼치기": "Expand",
    "위치": "Position",
    "Cycle 수": "Cycles",
    ". 답을 넣을 것 {n}건 포함": ", including {n} that need an answer",
    "{label} {n}건{tail}": "{label} {n}{tail}",
    "  멈춤 {n}분": "  Stalled {n} min",
    "Slack 켜짐": "Slack on",
    "Slack 꺼짐": "Slack off",
    "{p} {t}, {ago} 시작": "{p} {t}, started {ago}",
    "외 {n}": "+{n} more",
    "{p} {t}, {n}분 무활동": "{p} {t}, idle for {n} min",
    "{d}일 {h}시간": "{d} d {h} h",
    "{h}시간 {n}분": "{h} h {n} min",
    "측정 없음": "no data",
    ", {t} 뒤 초기화": ", resets in {t}",
    ", 초기화됨": ", reset",
    "5시간": "5 h",
    "주간": "Weekly",
    "측정 {t} 전, 오래된 값": "measured {t} ago, stale",
    "실측 없음, 호출 수 어림 {a}/{b}회": "no measurement, estimated {a}/{b} calls",
    "Claude가 이어받는 중": "Claude is taking over",
    "{title} {used}/{total}GB, {pct}% 사용": "{title} {used}/{total}GB, {pct}% used",
    "{title} 측정 불가": "{title} unavailable",
    "GPU 메모리 실측 {used}/{total}GB, {pct}% 사용(nvidia-smi)": "GPU memory measured {used}/{total}GB, {pct}% used (nvidia-smi)",
    "{p} {k} 실측 {gb}GB": "{p} {k} measured {gb}GB",
    "실측이 예약보다 커 새 GPU 작업을 {t}까지 멈춤({p})": "Measured use is above the reservation, so new GPU jobs are paused until {t} ({p})",
    "GPU 메모리": "GPU memory",
    "Ollama 켜짐, 적재 모델 {m}": "Ollama on, loaded models {m}",
    "취소: {t} 요청을 거둔다": "Cancel: withdraw the request {t}",
    "동시 Cycle {n}/{cap}": "Concurrent Cycles {n}/{cap}",
    "데모": "Demo",
    "지난 기록 {d}": "History {d}",
    "Cycle {n}개, 상한 {cap}개": "{n} Cycles, limit {cap}",
    "{n}줄": "{n} lines",
    "켜짐": "On",
    "꺼짐": "Off",
    "끝난 목표": "Finished goals",
    "끝: {r}": "Ended: {r}",
    "처음 {a} 최고 ": "first {a}, best ",
    " / 목표 {t} {d}": " / target {t} {d}",
    "이상": "or above",
    "이하": "or below",
    "주체 {o}": "Owner {o}",
    "작업자": "Worker",
    " (이동 {n})": " (moved {n})",
    "끝난 목표 {n}개 (보기 범위 밖)": "{n} finished goals (outside the view)",
    "Cycle별 지표 추이": "Metric trend by Cycle",
    "지표 없음": "No metric",
    "시작": "Start",
    " 채택": " adopted",
    "이 줄을 바로 시킨다. Cycle은 마감을 받는다": "Run this line now. A Cycle asks for a cutoff",
    "예약": "Schedule",
    "시각을 정해 그때 시킨다": "Pick a time and run it then",
    "할 일 파일에서 지운다": "Delete from the to-do file",
    "지우기, Cycle 고치기, 피드백": "Delete, edit Cycle, feedback",
    "할 일 파일에서 이 줄을 지운다.\n\n{t}": "Delete this line from the to-do file.\n\n{t}",
    "이 줄 하나를 지금 작업자로 돌린다. 시키면 할 일에서 빠지고 현황판에 보인다.\n\n{t}": "Run this one line with a worker now. It leaves the to-do list and shows on the Board.\n\n{t}",
    "지우기": "Delete",
    "시각": "Time",
    "마감": "Cutoff",
    "예약하기": "Schedule",
    "시키기": "Run",
    " 시작 <시각>": " 시작 <time>",
    " 마감 <시각>": " 마감 <time>",
    "Cycle 켜짐: {v}. 눌러 끈다 (jipsa todo cycle {no} off)": "Cycle on: {v}. Click to turn it off (jipsa todo cycle {no} off)",
    "눌러 Cycle을 켠다. 지표와 목표값은 첫 분석이 정한다 (jipsa todo cycle {no})": "Click to turn Cycle on. The first analysis sets the metric and target (jipsa todo cycle {no})",
    "Cycle을 끈다. 적힌 지표와 목표값이 지워진다.\n\n{v}": "Turn the Cycle off. The written metric and target are removed.\n\n{v}",
    "Cycle 값 고치기": "Edit Cycle values",
    "Cycle 값 넣기": "Set Cycle values",
    "지표, 목표값, 상한을 고친다 (jipsa todo cycle {no} <지표> <목표값> 상한 N)": "Edit the metric, target and limit (jipsa todo cycle {no} <metric> <target> 상한 N)",
    "지표": "Metric",
    "첫 화면 ms": "first paint ms",
    "목표값": "Target",
    "방향": "Direction",
    "방향 자동": "Direction auto",
    "상한": "Limit",
    " 도달하면 끝": " stop when reached",
    "저장": "Save",
    "취소": "Cancel",
    "고치기 칸을 닫는다": "Close the edit box",
    "피드백": "Feedback",
    "Cycle의 돌고 있는 단계와 다음 분석, 명령에 사람 피드백을 넣는다. 지표와 목표값은 바뀌지 않는다 (jipsa todo feedback {no} | 글)": "Add human feedback to the running Cycle step, the next analysis and its commands. The metric and target do not change (jipsa todo feedback {no} | text)",
    "이 Cycle의 다음 분석과 명령에 넣을 피드백을 적는다. 돌고 있는 단계에도 다음 구간부터 닿는다. 지표와 목표값은 바뀌지 않는다.\n\n{t}": "Write feedback for the next analysis and commands of this Cycle. The running step also gets it from its next segment. The metric and target do not change.\n\n{t}",
    "Cycle 켜짐: {v}": "Cycle on: {v}",
    ". 비운 칸은 Cycle 1 분석이 정해 이 줄에 채운다": ". The Cycle 1 analysis fills the empty fields on this line",
    ", 채택": ", adopted",
    "GPU 실측이 커 새 GPU 작업을 {t}까지 멈춘다({p})": "Measured GPU use is high, so new GPU jobs are paused until {t} ({p})",
    "대기열": "Queue",
    "빼기": "Remove",
    "대기열에서 빼고 요청을 거둔다": "Remove from the queue and withdraw the request",
    "없다": "None",
    "{a}에 시작, 마감 {b}": "Starts at {a}, cutoff {b}",
    "예약을 지우고 할 일로 둔다 (jipsa todo stop {no})": "Remove the schedule and keep it as a to-do (jipsa todo stop {no})",
    "갈래 ": "Branch ",
    " 열림 {a}, 닫힘 {b}": " open {a}, closed {b}",
    "지표 미정": "Metric not set",
    " 지금 ": " now ",
    "미정": "not set",
    "시작에서 마감까지 {n}% 지남": "{n}% of the time from start to cutoff has passed",
    "{n}회차": "round {n}",
    "큰 GPU 일 관찰 중{u}. 새 GPU 작업을 막는다": "Watching a large GPU job{u}. New GPU jobs are blocked",
    ", {t}까지": " until {t}",
    "회차별 값, 점선은 목표": "Value per round, dashed line is the target",
    "Ctrl+Enter로 넣기": "Ctrl+Enter to submit",
    "피드백 넣기": "Submit feedback",
    "HH:MM이나 +2h로 고치고 Enter. 돌던 단계는 끊지 않는다": "Change to HH:MM or +2h and press Enter. The running step is not cut off",
    "끝 예상 {t}": "Expected end {t}",
    "멈추기": "Stop",
    "돌던 단계를 마치고 마감 결과지를 쓴 뒤 할 일로 돌린다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계) (jipsa todo stop)": "Finish the running step, write the closing result sheet and move it back to to-dos. Running it again resumes where it stopped (the next round if the round was judged, otherwise the rest of that round) (jipsa todo stop)",
    "이 Cycle을 멈춘다. 돌던 단계는 끝까지 두고 할 일로 돌아온다.\n\n{t}": "Stop this Cycle. The running step finishes and it comes back to to-dos.\n\n{t}",
    "닫는 중": "Closing",
    "없음": "none",
    " 외 {n}": " +{n} more",
    "GPU 실측이 커 새 GPU 작업을 {t}까지 멈춘다": "Measured GPU use is high, so new GPU jobs are paused until {t}",
    "대기열 빼기, 예약 빼기, Cycle 마감과 피드백과 멈추기": "Remove from queue, remove schedule, Cycle cutoff, feedback and stop",
    "{n}회차 돎. {m} 지금 ": "{n} rounds done. {m} now ",
    "{n}건, Cycle {c}": "{n}, Cycle {c}",
    "{n}건": "{n}",
    "지난 Cycle {n}": "Past Cycles {n}",
    "한 번 돈 Cycle 줄. 결과지는 타임라인에 있고, Do로 멈춘 자리부터 잇는다": "Cycle lines that ran once. Result sheets are in the Timeline; Do resumes where it stopped",
    "할 일이 없다. 위 넣기 칸으로 넣는다": "No to-dos. Add one with the box above",
    ". 한 번 돈 Cycle {n}건은 지난 Cycle에 있다": ". {n} Cycles that ran once are under Past Cycles",
    "보일 줄이 없다": "No lines to show",
    "세션에 넣는 중": "Handing to the session",
    "스케줄러에 넣는 중": "Handing to the scheduler",
    "서버에 닿지 못했다": "Could not reach the server",
    "만들지 못했다: 서버에 닿지 못했다": "Not created: could not reach the server",
    "올릴 프로젝트": "Project to move to",
    "프로젝트 고르기": "Choose a project",
    "덧붙일 칸": "Extra fields",
    "기준(선택). cycle, 한도 칸은 | 뒤에": "Criteria (optional). cycle and 한도 fields go after |",
    "올리기": "Move",
    "jipsa todo up {l} <프로젝트> | <기준>": "jipsa todo up {l} <project> | <criteria>",
    "할 일로 줄을 닫는다": "Close the move-to-to-do line",
    "메모가 없다. 위 넣기 칸으로 넣는다": "No memos. Add one with the box above",
    "할 일로": "To to-do",
    "프로젝트와 기준을 붙여 할 일 칸으로 옮긴다 (jipsa todo up {l})": "Add a project and criteria and move it to to-dos (jipsa todo up {l})",
    "메모를 지운다 (jipsa todo memo-rm {l})": "Delete the memo (jipsa todo memo-rm {l})",
    "이 메모를 지운다.\n\n{t}": "Delete this memo.\n\n{t}",
    "file 주소를 복사했다. 브라우저 주소창에 붙여 넣는다": "Copied the file address. Paste it into the browser address bar",
    "초안 주소 없음": "No draft address",
    "초안 실행인데 결과 파일의 미리보기 주소가 비어 초안 보기 단추가 뜨지 않는다": "This is a draft run, but the result file has no preview address, so the Draft view button does not appear",
    "초안, 주소 없음": "Draft, no address",
    "불러오는 중": "Loading",
    "확인 필요 결과다. 확인이라고 넣거나 덧붙일 지시를 적으면 확인되어 완료가 된다. 지시는 세션에 넘어가고 다시 돌리지 않는다.": "This result needs attention. Enter 확인 (acknowledge) or add an instruction and it is acknowledged and becomes Done. The instruction goes to the session and the job is not run again.",
    "확인 필요 결과다. {c}직접 적어 넣으면 확인되어 완료가 된다. 답은 세션에 넘어가고 다시 돌리지 않는다.{a}": "This result needs attention. {c}Type an answer and it is acknowledged and becomes Done. The answer goes to the session and the job is not run again.{a}",
    "안을 누르거나 ": "Click an option or ",
    " 안은 보고서 정할 것에서 자동으로 뽑았다.": " The options were taken automatically from the report's decisions.",
    "고를 것이 남은 {s} 결과다. {c}직접 적는다. 답은 세션에 넘어가고 다시 돌리지 않는다.{a}": "A {s} result with choices left. {c}type your own. The answer goes to the session and the job is not run again.{a}",
    "{n} (추천)": "{n} (recommended)",
    "답 칸에 {n}을 넣는다": "Puts {n} in the answer box",
    "뒤에 쉼표와 추가 지시를 이어 써도 된다. 답 넣기를 누르면 확정된다": "You may add a comma and more instructions. Click Submit answer to confirm",
    "{k} {n}개": "{k} ({n})",
    "그 밖의 정할 것": "Other decisions",
    "정할 것": "Decisions",
    "{k} (답 칸에 직접 적는다)": "{k} (type in the answer box)",
    "그림을 올리는 중이다. 다 올라간 뒤 넣는다": "Images are uploading. Submit after they finish",
    "이 답으로 확정한다:\n{v}{i}": "Confirm with this answer:\n{v}{i}",
    "\n\n붙인 그림 {n}장은 답 끝에 저장 경로 줄로 붙는다": "\n\n{n} pasted images are added at the end of the answer as saved path lines",
    "결과지를 불러오지 못했다": "Could not load the result sheet",
    "{n}자": "{n} chars",
    "새 탭에서 크게 본다": "Open large in a new tab",
    "{n} 지우기": "Delete {n}",
    "{t}은 붙이지 않는다. PNG, JPEG, GIF, WebP만 받는다": "{t} cannot be pasted. Only PNG, JPEG, GIF and WebP are accepted",
    "알 수 없는 형식": "Unknown type",
    "그림이 {n}MB다. 10MB 이하만 붙인다": "The image is {n}MB. Only 10MB or less can be pasted",
    "그림으로 읽히지 않아 올리지 않았다": "Not uploaded because it could not be read as an image",
    "그림을 올리는 중": "Uploading image",
    "그림을 올리지 못했다: {w}": "Could not upload the image: {w}",
    "{n}를 붙였다. 답을 넣으면 저장 경로가 답 끝에 붙는다": "{n} pasted. When you submit, its saved path is added at the end of the answer",
    "그림을 올리지 못했다: 서버에 닿지 않는다": "Could not upload the image: server unreachable",
    "이 브라우저는 클립보드 읽기를 지원하지 않는다. Ctrl+V로 붙인다": "This browser cannot read the clipboard. Paste with Ctrl+V",
    "클립보드 읽기가 막혀 있다. 주소창 왼쪽의 사이트 설정에서 클립보드를 허용하거나 Ctrl+V로 붙인다": "Clipboard access is blocked. Allow it in the site settings left of the address bar, or paste with Ctrl+V",
    "클립보드에 그림이 없다": "No image in the clipboard",
    "보내는 중": "Sending",
    "답을 넣었다. 스케줄러가 다음 주기에 이어 돌린다": "Answer submitted. The scheduler resumes it on the next cycle",
    "답을 기록에 적었다. {d}": "Answer recorded. {d}",
    "넣지 못했다: {w}": "Not submitted: {w}",
    "서버에 닿지 않는다": "Server unreachable",
    "넣은 답{t}: ": "Submitted answer{t}: ",
    " 결과지 열기": " Open result sheet",
    "잘못 넣었으면 세션에서 jipsa answer {id} --undo로 물린다": "If this was a mistake, undo it in the session with jipsa answer {id} --undo",
    "{s}였으나 확인해 완료로 처리 ({t})": "Was {s}, acknowledged and marked Done ({t})",
    "답 없이 확인함. 상태 값과 큐 보류는 그대로라 다시 돌지 않는다. 되돌리면 답 칸이 다시 열린다": "Acknowledged without an answer. Status and queue hold stay as they are, so it does not run again. Undo to reopen the answer box",
    "확인 필요로 되돌리기": "Back to Needs attention",
    "답 없이 확인": "Acknowledge without answer",
    "확인": "Acknowledge",
    "확인하면 답 칸이 닫히고 확인 필요에서 빠진다. 상태와 큐 보류는 그대로라 다시 돌지 않는다": "Acknowledging closes the answer box and removes it from Needs attention. Status and queue hold stay as they are, so it does not run again",
    "적지 못했다: {w}": "Not recorded: {w}",
    "서버에 닿지 않는다. 대시보드 서버를 다시 켜야 할 수 있다": "Server unreachable. The dashboard server may need a restart",
    "보고 {d}": "Report {d}",
    "보고를 불러오지 못했다": "Could not load the report",
    "자세히": "Details",
    "지시: {t}": "Instruction: {t}",
    "공격 {n}, 반영 {a}, 사람 {h}": "{n} points, {a} applied, {h} for a person",
    "공격 없음": "No attack",
    "판정 {v}, {s}": "verdict {v}, {s}",
    ", 반박 {n}": ", {n} rebutted",
    ", 답 없음 {n}": ", {n} unanswered",
    "공격 없음({w})": "No attack ({w})",
    "사유 없음": "no reason",
    "원본 크기로 열기": "Open at full size",
    "{n}분 전": "{n} min ago",
    "{n}시간 전": "{n} h ago",
    "{n}일 전": "{n} d ago",
    "다시 보기": "Review",
    "결과지": "Result",
    "Cycle별 다시 잰 값과 목표선": "Re-measured value per Cycle and target line",
    " 버림": " dropped",
    ", 목표 {t} {d}": ", target {t} {d}",
    " (멈춤 {n}분)": " (stalled {n} min)",
    "{n}단계 {s}": "Step {n} {s}",
    "단계 기록 아직 없음": "No step records yet",
    "확인 필요 {n}": "Needs attention {n}",
    "목표 진행": "Goal running",
    "최근 실패": "Recently failed",
    "최근 완료": "Recently done",
    "쉬는 중": "Idle",
    "Cycle 목표": "Cycle goal",
    ", 목표 미정": ", target not set",
    "{t}. 목표 미정: {p}을 Cycle 1 분석이 정한다": "{t}. Target not set: the Cycle 1 analysis decides {p}",
    "갈래 열림 {o} 닫힘 {c}": "Branches open {o} closed {c}",
    " 사람 확인 {n}": " for a person {n}",
    ", 지금 [{b}]": ", now [{b}]",
    "확인 필요 {n}건 더": "{n} more needing attention",
    "최근 결과": "Recent results",
    "24시간 안에 끝난 실행 없음": "No runs finished in the last 24 hours",
    "\n답 들어감: {a}": "\nAnswer in: {a}",
    "\n위 실행에 넣은 답으로 시작했다": "\nStarted from the answer given to the run above",
    "최근 결과 {n}건 더": "{n} more recent results",
    "누르면 전부 펼친다": "Click to show all",
    "진행 중인 실행": "Running",
    "진행 중인 실행 없음": "Nothing running",
    "미병합 ": "Unmerged ",
    "저장소가 git이 아니거나 기본 브랜치가 없다": "Not a git repository or no default branch",
    "main에 병합되지 않은 orch/ 브랜치 수. 5분마다 다시 센다": "Number of orch/ branches not merged into main. Recounted every 5 minutes",
    "할 일 ": "To-do ",
    "확인 전 완료": "Done, not acknowledged",
    "확인 필요 {n}건": "Needs attention {n}",
    "{p} {t}, {n}분째 활동이 없다. 띄운 세션에 깨우라고 알렸다": "{p} {t}, no activity for {n} min. The session that started it was asked to wake up",
    "결과지 열기": "Open result sheet",
    "지금 볼 것": "Look now",
    "최근 기록 없음": "No recent records",
    "미병합 {n}": "Unmerged {n}",
    "{p}은 최근 기록이 없다": "{p}: no recent records",
    "모든 프로젝트가 돌고 있다": "Every project is running",
    "{n}건, 최근 {m}건": "{n}, latest {m}",
    "화면 모드 {now}. 누르면 {next}로 바뀐다": "Theme {now}. Click to switch to {next}",
    "작업 {n}개": "{n} jobs",
    "그 날짜의 기록이 없다": "No records for that date",
    "멈춤||play": "Pause",
    "화면 언어 {now}. 누르면 {next}로 바뀐다": "Language {now}. Click to switch to {next}",
    "요약": "Summary",
    "용어": "Terms",
    "핵심": "Key points"
  };
  const lang = () => (document.documentElement.getAttribute("lang") === "en" ? "en" : "ko");
  // 사전 한 벌에 두 언어가 있다. ko는 키의 || 앞이고 en은 표의 값이며, 표에 없으면 ko로 둔다
  const T = (key, vars) => {
    const s = String(key);
    let out = lang() === "en" && Object.prototype.hasOwnProperty.call(EN, s) ? EN[s] : s.split("||")[0];
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m));
    return out;
  };
  // 정적 HTML의 data-t(글자)와 data-t-attr(속성 이름 목록)을 지금 언어로 바른다. 처음 부를 때 한국어 원문을 요소에 기억해 두고 다시 부르면 그 원문으로 찾는다
  const applyStatic = () => {
    for (const n of document.querySelectorAll("[data-t]")) {
      if (n.__tKey == null) n.__tKey = n.getAttribute("data-t") || n.textContent;
      n.textContent = T(n.__tKey);
    }
    for (const n of document.querySelectorAll("[data-t-attr]")) {
      n.__tAttr = n.__tAttr || {};
      for (const a of n.getAttribute("data-t-attr").split(/\s+/).filter(Boolean)) {
        if (!(a in n.__tAttr)) n.__tAttr[a] = n.getAttribute(a) || "";
        if (n.__tAttr[a]) n.setAttribute(a, T(n.__tAttr[a]));
      }
    }
    if (document.__tTitle == null) document.__tTitle = document.title;
    document.title = T(document.__tTitle);
    document.documentElement.setAttribute("data-i18n", lang());
  };
  // ----- 서버 문구(261103-misc-17 1안). 서버는 한국어 원문을 그대로 보내고, 화면에 그리기 직전에만 아래 표로 바꾼다 -----
  // 값 비교, CSS 선택자, 답으로 보내는 값은 서버 원문 그대로 쓴다. 서버 문구가 바뀌면 이 표도 같이 고친다
  // SRV는 문장 전체가 같을 때만 바꾸는 표다. 없으면 위 EN 표를 본다
  const SRV = {
    // 머리 줄 경고와 툴팁(scheduler/web.py 경고 8종)
    "스케줄러 꺼짐": "Scheduler off",
    "Slack 연결 안 됨": "Slack not connected",
    "Slack이 연결되지 않았다. 보고는 파일에만 남는다": "Slack is not connected. Reports are kept in files only",
    "심장박동이 멈췄다. 프로세스는 있다": "The heartbeat stopped. The process still exists",
    "uv run jipsa web으로 켠다": "Start it with uv run jipsa web",
    // Cycle 단계, 위치, 상태 글자, 주체(scheduler/cycle.py)
    "명령 이행": "Run",
    "분석과 피드백": "Analysis and feedback",
    "목표 판정": "Goal judgment",
    "이행": "Run",
    "분석": "Analysis",
    "목표 정하기": "Goal setting",
    "정하는 중": "drafting",
    "다시 정하기 대기": "waiting to redo",
    "박음": "fixed",
    "진행": "Running",
    "창 멈춤": "Paused (usage window)",
    "Main": "Main",
    "종합 보고 대기": "final report pending",
    "종합 보고 중": "final report running",
    "종합 보고 확인 필요": "final report needs attention",
    "종합 보고 확인함": "final report acknowledged",
    "종합 보고 실패": "final report failed",
    "Auto 종합 보고 대기": "Auto final report pending",
    "통과": "Pass",
    "보완": "Needs work",
    "재작업": "Rework",
    "환경 실패 상한": "environment failure limit",
    "목표 도달": "target reached",
    "사람 멈춤": "stopped by a person",
    "다음 명령이 금지 사항": "next plan is forbidden",
    "다음 명령 1순위와 차순위가 모두 버린 가설": "both next plans are discarded hypotheses",
    "이행 확인 필요": "run needs attention",
    "Cycle 단계 대기": "waiting for a Cycle step",
    "시작 대기": "waiting to start",
    // 시킨 줄 상태 글(scheduler/auto.py run_note)
    "곧 작업자로 시작한다": "starts soon with a worker",
    "곧 시작한다": "starts soon",
    "상한이 차 기다린다": "waiting, the limit is full",
    "기다린다": "waiting",
    "기준 정하기 중. 끝나면 1안 기준으로 본 작업을 잇는다": "Setting criteria. When done, the main job continues with the criteria of option 1",
    "Cycle 목표를 돈다": "running the Cycle goal",
    "도는 중": "running",
    "마감, 돌던 단계가 끝나면 닫는다": "cutoff; closes when the running step ends",
    "세션에 보낸 줄. 세션이 받아 서브에이전트로 시작한다": "Sent to the session. The session starts it as a subagent",
    // 오늘 보고(종합 보고) 절 이름과 라벨(scheduler/report.py)
    "환경": "Environment",
    "단발 목표 분석과 반영 Cycle": "Single-run review and revise Cycle",
    "없음": "None",
    "완료(원래 실패)": "Done (originally failed)",
    "분석자 같은 공급자": "analyst from the same provider",
    "이동 없음": "no moves",
    "지표 없음": "no metric",
    "나아짐": "improved",
    "나아지지 않음": "no gain",
    "피드백 없음": "no feedback",
    "분석과 피드백 중": "Analysis and feedback in progress",
    "명령 이행 중": "Run in progress",
    "분석 재측정": "re-measured by analysis",
    "1순위": "first choice",
    "차순위": "second choice",
    "대기(cycle next나 스케줄러가 연다)": "pending (opened by cycle next or the scheduler)",
    "기준": "Criterion",
    "판정": "Verdict",
    "확인 항목": "Check item",
    // 결과지 규격(policies/report.md)의 절 이름과 대체 보고(scheduler/record.py)
    "남은 일과 정할 것": "Remaining work and decisions",
    "실패 사유": "Failure reason",
    "원본 파일과 커밋": "Source files and commit",
    "보고서가 없다. 작업자가 report.md를 쓰지 않았거나 작업이 아직 끝나지 않았다.": "There is no report. The worker did not write report.md, or the job has not finished yet.",
    "선택지는 아래와 같다. 추천이 앞에 있다.": "The options are below. The recommended one comes first.",
    "(없음)": "(none)",
    // Sol 공격 표 머리와 값(scheduler/attack.py)
    "번호": "No.",
    "심각도": "Severity",
    "종류": "Kind",
    "문제 주장": "Claim",
    "문제": "Problem",
    "근거 위치": "Evidence location",
    "확인 방법": "How to check",
    "답": "Answer",
    "답 내용": "Answer note",
    "반대 검토 0건": "Counter-review: 0",
    // 답 넣기와 그림 올리기 실패 안내(scheduler/record.py, web.py)
    "기록이 없는 실행ID": "No record for this run ID",
    "이미 답이 들어갔다. 바꾸려면 --undo로 물린 뒤 다시 넣는다": "An answer is already in. To change it, withdraw it with --undo and enter it again",
    "사람이 답 없이 확인해 닫은 실행이다. 결과지의 '확인 필요로 되돌리기'를 누른 뒤 넣는다": "A person acknowledged and closed this run without an answer. Press 'Back to Needs attention' on the result sheet first",
    "답 없이 확인한 실행이다(확인함). 결과지의 '확인 필요로 되돌리기'를 누른 뒤 넣는다": "This run was acknowledged without an answer. Press 'Back to Needs attention' on the result sheet first",
    "큐에 없는 실행ID": "This run ID is not in the queue",
    "PNG, JPEG, GIF, WebP가 아니다": "Not a PNG, JPEG, GIF, or WebP image",
    "세션 전용 프로젝트라 세션이 받을 때까지 기다린다.": "This is a session-only project, so it waits until a session takes it.",
    "스케줄러가 꺼져 있어 세션이 받거나 스케줄러가 켜질 때까지 기다린다.": "The scheduler is off, so it waits until a session takes it or the scheduler starts.",
    "2분 안에 세션이 받지 않으면 스케줄러 작업자로 넘긴다.": "If no session takes it within 2 minutes, it goes to a scheduler worker."
  };
  // 틀 문장. {n}으로 시작하는 칸은 숫자, {hm}은 시각, {x}는 작업 글이고 그대로 옮긴다. 나머지 칸은 다시 이 표로 바꾼다. 위에서부터 처음 맞는 틀을 쓴다
  const PAT_SRC = [
    ["스케줄러 {n}분 멈춤", "Scheduler stalled for {n} min"],
    ["{n}초 안에 감시가 띄운다", "The watcher starts it within {n} s"],
    ["{by}에서 껐다. 감시가 다시 띄우지 않는다. {on}에서 켠다", "Turned off from {by}. The watcher will not restart it. Turn it on from {on}"],
    ["{n}분 안에 {n2}번 꺼져 다시 띄우기를 멈췄다. 원인을 고친 뒤 대시보드를 다시 켜거나 uv run jipsa run으로 켠다",
      "It went down {n2} times within {n} min, so restarting stopped. Fix the cause, then restart the dashboard or start it with uv run jipsa run"],
    ["끝: {why}(최고 {n}), {tail}", "Ended: {why} (best {n}), {tail}"],
    ["끝: {why}({n}), {tail}", "Ended: {why} ({n}), {tail}"],
    ["끝: {why}, {tail}", "Ended: {why}, {tail}"],
    ["Auto 종합 보고 {s}", "Auto final report {s}"],
    ["종합 보고 {s}", "final report {s}"],
    ["목표 정하기 v{n} {s}({x})", "Goal setting v{n} {s} ({x})"],
    ["목표 정하기 v{n} {s}", "Goal setting v{n} {s}"],
    ["Cycle {n}, {s} 중", "Cycle {n}, {s} in progress"],
    ["Cycle {n} 뒤 새 Cycle 멈춤", "New Cycles paused after Cycle {n}"],
    ["Cycle {n}, 판정 {x}", "Cycle {n}, verdict {x}"],
    ["Cycle {n}, 다음 단계 대기", "Cycle {n}, waiting for the next step"],
    ["끝남({r})", "Ended ({r})"],
    ["목표 도달(Cycle {n} 지표 {n2}, 목표 {n3} {d}, 사람 확인 {n4}개 대기)", "target reached (Cycle {n} metric {n2}, target {n3} {d}, {n4} human checks pending)"],
    ["목표 도달(Cycle {n} 지표 {n2}, 목표 {n3} {d})", "target reached (Cycle {n} metric {n2}, target {n3} {d})"],
    ["{n} Cycle 연속 나아지지 않음", "no gain for {n} Cycles in a row"],
    ["다음 명령이 금지 사항({x})", "next plan is forbidden ({x})"],
    ["Auto 마감 {hm} 전에 Cycle({n}분)을 마칠 수 없음", "cannot finish a Cycle ({n} min) before the Auto cutoff {hm}"],
    ["Auto 마감 {hm}", "Auto cutoff {hm}"],
    ["{hm} Main에서 작업자로({x})", "{hm} Main to worker ({x})"],
    ["{hm} Main 이어 부르기 뒤 복귀", "{hm} back after Main resumed"],
    ["{hm}에 시작한다", "starts at {hm}"],
    ["시킨 줄. {s}({x})", "Assigned line. {s} ({x})"],
    ["시킨 줄. {s}", "Assigned line. {s}"],
    ["{x}. 다시 시키면 Cycle {n}부터 잇는다", "{x}. Run it again to continue from Cycle {n}"],
    ["{n}분, 상한 {n2}분 넘김", "{n} min, over the {n2} min limit"],
    ["{n}분/{n2}분", "{n}/{n2} min"],
    ["{n}분", "{n} min"],
    ["Cycle {n}번, 끝({r})", "Cycle {n}, ended ({r})"],
    ["Cycle {n}번, 진행 중", "Cycle {n}, running"],
    ["Cycle {n}번", "Cycle {n}"],
    ["처음 {x}", "first {x}"],
    ["최고 {x}", "best {x}"],
    ["목표 {n} {d}", "target {n} {d}"],
    ["주체 {o}, 이동 없음", "Owner {o}, no moves"],
    ["주체 {o}, 이동 {x}", "Owner {o}, moves {x}"],
    ["주체 {o}", "Owner {o}"],
    ["이동 {x}", "moves {x}"],
    ["사람 확인: {s}", "Human check: {s}"],
    ["지표 {n}(차 {n2})", "metric {n} (change {n2})"],
    ["지표 {n}", "metric {n}"],
    ["판정 {x}", "verdict {x}"],
    ["Cycle {n} {n2}({s})", "Cycle {n} {n2} ({s})"],
    ["다음 명령(Cycle {n} 피드백 {r})", "Next plan (Cycle {n} feedback, {r})"],
    ["Claude 5시간 창 사용 {n}%, {hm} 초기화, 주간 {n2}%", "Claude 5-hour window {n}% used, resets {hm}, weekly {n2}%"],
    ["고를 것이 있는 것 {n}건", "To choose ({n})"],
    ["확인만 하면 되는 것 {n}건", "Acknowledge only ({n})"],
    ["분석: 지적 {n}건", "analysis: {n} issues"],
    ["서칭: 출처 {n}건", "search: {n} sources"],
    ["걸린 규칙은 {x}이다.", "Rule hit: {x}."],
    ["반대 검토 {n}건: 모두 반영", "Counter-review {n}: all applied"],
    ["Sol 판정은 {v}이다. 같은 공급자 공격이다.", "Sol verdict: {v}. Same-provider attack."],
    ["Sol 판정은 {v}이다.", "Sol verdict: {v}."],
    ["Sol 공격 없음({x}).", "No Sol attack ({x})."],
    ["커밋: {x}", "Commit: {x}"],
    ["열어 볼 파일: {x}", "Files to open: {x}"],
    ["고를 것이 없다 (지금 {s}, 선택지와 정할 것 없음)", "Nothing to choose (now {s}, no options or decisions)"],
    ["확인 필요나 끝난 실행이 아니다 (지금 {s})", "Not a Needs attention or finished run (now {s})"],
    ["크기가 {n}바이트다. 0보다 크고 10MB 이하만 받는다", "The size is {n} bytes. Only more than 0 and up to 10 MB is accepted"],
    ["runs/{x}가 없다", "runs/{x} does not exist"],
    ["아직 처리되지 않았다. 열린 세션 {s}에 몇 초 안에 전달된다. {t}", "Not handled yet. It reaches the open session {s} within seconds. {t}"],
    ["아직 처리되지 않았다. 부모 세션 {s}이 일하는 중이라 그 세션의 턴 끝이나 다음 입력 때 전달된다. {t}",
      "Not handled yet. The parent session {s} is busy, so it is delivered at the end of its turn or at its next input. {t}"],
    ["아직 처리되지 않았다. 지금 열린 세션이 없다. {t}", "Not handled yet. No session is open now. {t}"],
    ["아직 처리되지 않았다. {t}", "Not handled yet. {t}"],
    ["{x}. 세션이 열리면 받는다.", "{x}. A session picks it up when one opens."],
    ["{hm}까지 세션이 받지 않으면 스케줄러 작업자로 넘긴다.", "If no session takes it by {hm}, it goes to a scheduler worker."],
    ["세션 {s}이 {hm}에 받아 처리한다.", "Session {s} took it at {hm} and is handling it."],
    ["세션이 받지 않아 {hm}에 스케줄러 작업자 {r}로 넘겼다. 그 실행의 지금 상태는 {st}이다.", "No session took it, so at {hm} it went to scheduler worker {r}. That run is now {st}."]
  ];
  const esc = (s) => s.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  const PAT = PAT_SRC.map(([ko, en]) => {
    const names = [];
    const body = ko.split(/(\{\w+\})/).map((part) => {
      const m = /^\{(\w+)\}$/.exec(part);
      if (!m) return esc(part);
      names.push(m[1]);
      return m[1] === "hm" ? "(\\d{1,2}:\\d{2})" : /^n\d*$/.test(m[1]) ? "(-?\\d[\\d,.]*)" : "(.+?)";
    }).join("");
    return { re: new RegExp(`^${body}$`), names, en };
  });
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  // 정확히 같은 문장만 바꾼다. 표 머리와 상태 글자처럼 한 낱말 칸에 쓴다
  const TX = (s) => {
    if (lang() !== "en" || s == null) return s;
    const k = String(s);
    return own(SRV, k) ? SRV[k] : own(EN, k) && !k.includes("{") ? EN[k] : k;
  };
  // 서버 문구 한 줄. 정확히 같은 문장, 다음으로 틀 문장 순서로 찾고 없으면 원문 그대로 둔다. 칸 안의 글은 같은 규칙으로 한 번 더 찾는다
  const TS = (s, depth) => {
    if (lang() !== "en" || s == null || s === "") return s;
    const k = String(s), hit = TX(k);
    if (hit !== k || (depth || 0) > 2) return hit;
    for (const p of PAT) {
      const m = p.re.exec(k);
      if (!m) continue;
      const vals = {};
      p.names.forEach((nm, i) => { vals[nm] = nm === "hm" || /^[nx]\d*$/.test(nm) ? m[i + 1] : TS(m[i + 1], (depth || 0) + 1); });
      return p.en.replace(/\{(\w+)\}/g, (x, nm) => (own(vals, nm) ? vals[nm] : x));
    }
    return k;
  };
  // 선택지 이름(1안, A안, 가안, 안 2). 단추 글자만 바꾸고 답으로 보내는 값은 원래 이름이다
  const GA = "가나다라마바사아자", GA_EN = ["Ga", "Na", "Da", "Ra", "Ma", "Ba", "Sa", "Ah", "Ja"];
  const optName = (n) => {
    if (lang() !== "en") return n;
    const s = String(n || ""); let m;
    if ((m = /^(\d+)\s?안$/.exec(s)) || (m = /^안\s?(\d+)$/.exec(s)) || (m = /^([A-Z])\s?안$/.exec(s))) return `Option ${m[1]}`;
    if ((m = /^([가-자])안$/.exec(s)) && GA.includes(m[1])) return `Option ${GA_EN[GA.indexOf(m[1])]}`;
    return s;
  };
  // 결과지 요약 상자 줄 머리(policies/report.md의 한 일, 결과, 사람이 할 일). 줄 맨 앞 굵은 이름만 바꾼다
  const SUM = { "한 일": "What was done", "결과": "Result", "사람이 할 일": "Action for you" };
  const sumLine = (l) => (lang() !== "en" ? l : l.replace(/^(\s*[-*]?\s*)\*\*([^*:]+?)(:?)\*\*/, (m, a, name, c) => (own(SUM, name.trim()) ? `${a}**${SUM[name.trim()]}${c}**` : m)));
  // Sol 공격 표의 값 칸(심각도, 종류, 답). 표 머리에 심각도와 답이 같이 있을 때만 쓴다
  const ATK = { "상": "High", "중": "Medium", "하": "Low", "사실과 수치": "Facts and numbers", "완료 기준": "Completion criteria", "범위 밖 변경": "Out-of-scope change",
    "측정 방법": "Measurement method", "읽기 쉬움": "Readability", "반영": "Applied", "반박": "Rebutted", "사람": "Human", "답 없음": "No answer" };
  const atkCell = (s) => (lang() === "en" && own(ATK, s) ? ATK[s] : s);
  // 결과지 반대 검토 접기 줄. '반대 검토 3건: 반영 1, 반박 2'
  const foldTitle = (s) => {
    if (lang() !== "en") return s;
    const m = /^반대 검토 (\d+)건: (.+)$/.exec(s);
    if (!m || m[2] === "모두 반영") return TS(s);
    return `Counter-review ${m[1]}: ` + m[2].replace(/(반영|반박|사람|답 없음) (\d+)/g, (x, k, n) => `${ATK[k].toLowerCase()} ${n}`);
  };
  // 오늘 보고 한 줄. 머리 줄 집계, 절 아래 '- 없음', 보조 줄의 라벨(선택지, 걸린 규칙, 확인, 주체와 토큰 등)만 바꾸고 뒤 글은 둔다
  const DAY_LABEL = { "선택지": "Options", "걸린 규칙": "Rule hit", "확인": "Acknowledge", "판 수 상한": "Match cap", "주체": "Owner",
    "추가 패키지": "Added packages", "한도 대기": "Limit wait", "자원 대기": "Resource wait" };
  // cycle 절 보조 줄의 라벨. 값도 정확히 맞는 문장이나 틀 문장이면 바꾼다
  const CYC_LABEL = { "실패 범주": "Failure classes", "버린 가설": "Discarded hypotheses", "판정 값": "Judged value", "종합 보고": "Final report" };
  // 표 칸 하나씩. 칸 전체가 맞지 않으면 쉼표로 나눈 조각마다 찾는다
  const cells = (parts) => parts.map((p) => { const t = TS(p); return t !== p ? t : p.split(", ").map((x) => TS(x)).join(", "); });
  const dayLine = (line) => {
    if (lang() !== "en") return line;
    let m = /^\[jipsa\] (\S+) (.+)$/.exec(line);
    if (m) return `[jipsa] ${m[1]} ` + m[2].split(", ").map((p) => p.replace(/^(.+?) (\d+)(?:\(실패 (\d+) 포함\))?$/, (x, s, n, f) => `${TX(s)} ${n}${f ? ` (incl. ${f} failed)` : ""}`)).join(", ");
    if (/^\s*- 없음\s*$/.test(line)) return line.replace("없음", "None");
    if (/^### (고를 것이 있는 것|확인만 하면 되는 것) \d+건$/.test(line)) return `### ${TS(line.slice(4))}`;
    // cycle 절의 목표 줄과 Cycle 줄. 첫 칸(목표 제목, Cycle 명령)은 작업 글이라 두고 뒤 칸만 바꾼다
    m = /^- 목표 (\S+) \| (.+)$/.exec(line);
    if (m) { const [title, ...rest] = m[2].split(" | "); return `- Goal ${m[1]} | ${[title, ...cells(rest)].join(" | ")}`; }
    m = /^(\s+- )(Cycle \d+번, .+)$/.exec(line);
    if (m) return m[1] + cells(m[2].split(" | ")).join(" | ");
    m = /^(\s+- )(Cycle \d+: .+)$/.exec(line);
    if (m) { const [head, ...rest] = m[2].split(" | "); return m[1] + [head, ...cells(rest)].join(" | "); }
    m = /^- (Claude 5시간 창 .+)$/.exec(line);
    if (m) return `- ${TS(m[1])}`;
    m = /^(\s*- )([^:|]+?): (.*)$/.exec(line);
    if (m && own(CYC_LABEL, m[2])) return `${m[1]}${CYC_LABEL[m[2]]}: ${TS(m[3])}`;
    if (m && !own(DAY_LABEL, m[2]) && TS(m[2]) !== m[2]) return `${m[1]}${TS(m[2])}: ${m[3]}`; // 다음 명령(Cycle 1 피드백 1순위): 명령 글
    if (!m || !own(DAY_LABEL, m[2])) {
      const bits = /^(\s+- )(분석: 지적 \d+건|서칭: 출처 \d+건|분석자 같은 공급자)((?:\. .+)?)$/.exec(line);
      return bits ? bits[1] + `${bits[2]}${bits[3]}`.split(". ").map((b) => TS(b)).join(". ") : line;
    }
    let rest = m[3];
    if (m[2] === "선택지") rest = rest.split(" / ").map((o) => o.replace(/^\(추천\) /, "(recommended) ")).join(" / ");
    if (m[2] === "확인") rest = rest.replace(/^결과지에서 확인하면 완료로 바뀐다 /, "acknowledging on the result sheet turns it Done ");
    if (m[2] === "주체") {
      const t = /^(.+?)\.(?: 토큰: 출력 ([\d,]+), 캐시 읽기 ([\d,]+))?$/.exec(rest);
      if (t) rest = `${TX(t[1])}.` + (t[2] ? ` Tokens: output ${t[2]}, cache read ${t[3]}` : "");
    }
    return `${m[1]}${DAY_LABEL[m[2]]}: ${rest}`;
  };
  // 오늘 보고 항목 줄의 결과 칸 머리('확인 필요(실패): ', '완료(원래 실패): ', '확인함: ')
  const resultHead = (s) => (lang() !== "en" ? s : String(s).replace(/^(확인 필요\(실패\)|완료\(원래 실패\)|확인함): /, (x, k) => `${TX(k)}: `));
  window.I18N = { en: EN, srv: SRV, pat: PAT_SRC, lang, T, applyStatic, KEY: "jipsa.lang" };
  Object.assign(window, { TS, TX, optName, sumLine, atkCell, foldTitle, dayLine, resultHead });
  window.T = T;
  window.applyStatic = applyStatic;
})();
