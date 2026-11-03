/* jipsa 대시보드. /api/state?tab=(실시간, 탭마다 그 탭 값만), /api/day(지난 날짜, 데모), /api/runs(기록), /api/run(결과지)를 읽는다. 데이터는 textContent로만 넣는다.
   트리는 카드와 연결선으로 그린다. 세션 카드 아래에 그 세션이 시작한 서브에이전트가, 스케줄러 카드 아래에 작업자가 붙는다. */
(() => {
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const STAGE_NAME = { run: "진행", analyze: "Sol 공격", search: "서칭", reply: "공격 답과 보고서 수정" };
  // 상태 값 확인 필요는 사람 답이 필요한 실행이다(261022-jipsa-50 전 이름은 판단 대기, 서버가 읽을 때 새 이름으로 맞춘다).
  // 화면의 확인 필요는 이 상태 값과 확인하지 않은 완료와 실패를 함께 부르는 이름이다(옛 이름 확인 전 완료도 여기에 합쳤다, 261023-jipsa-26). 답이 필요한 것은 물음표 표시와 툴팁으로 가른다
  const T = window.T; // 화면 글자 사전(web/i18n.js). 한국어 원문이 키다
  const stName = (s) => (s ? T(s) : s); // 상태 값은 저장과 비교에서 그대로 두고 화면에 보일 때만 이 변환을 지난다(261103-misc-14)
  const FINAL_STEP = "종합 보고"; // 끝난 cycle의 종합 보고 단계(261023-jipsa-33)
  const EXECUTOR = { worker: "스케줄러 작업자", subagent: "세션 서브에이전트", session: "Main 세션", manual: "손으로 들여옴" };
  const GROUP = { worker: "스케줄러 (jipsa run)", subagent: "세션 (Claude Code)", session: "세션 (Claude Code)", manual: "손으로 들여온 기록" };
  const LABEL_W = 210, ROW_H = 28, BAR_H = 14, TOP = 26, RIGHT = 220; // 오른쪽 상태 칸은 "진행 중  76분, 상한 60분 넘김"이 들어갈 폭이다(261029-jipsa-24)

  const state = { view: "live", data: null, vnow: null, playing: false, timer: null, pollTimer: null, pollSec: 15, tmin: null, tmax: null,
                  open: null, drawerTimer: null, tab: "board" };

  const parse = (s) => (s ? new Date(s) : null);
  const hhmm = (d) => d ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : "";
  const mdhm = (d) => d ? `${d.getMonth() + 1}/${d.getDate()} ${hhmm(d)}` : "";
  const mins = (a, b) => Math.max(0, Math.round((b - a) / 60000));
  const fmtN = (n) => (n == null ? "" : Number(n).toLocaleString("ko-KR"));
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const svgEl = (tag, attrs) => { const e = document.createElementNS(SVG, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  // 걸린 분만 보이다가 상한의 80% 이상이면 상한을 같이, 넘기면 넘김을 보인다(261029-jipsa-22 1안). scheduler/config.py의 time_text와 같다
  const dur = (used, limit) => { const u = used ?? 0; return !limit || u < limit * 0.8 ? T("{n}분", { n: u }) : u > limit ? T("{n}분, 상한 {limit}분 넘김", { n: u, limit }) : T("{n}분/{limit}분", { n: u, limit }); };
  const budgetText = (run) => { const b = run && run.match_budget; return b ? T("{text}, 새 판 마감 {at}", { text: b.text, at: String(b.stop_new_at || "").slice(11, 16) }) : ""; }; // 판 수로 계산한 상한의 근거
  const pill = (status) => el("span", `stpill ${(status || "").replace(" ", "")}`, stName(status) || ""); // 모양은 상태 표기 한 벌의 CSS가 그린다(8안)
  const pname = (p) => (p === "misc" ? T("기타") : p);
  const pkey = (p) => (p === "misc" ? "기타" : p); // 줄 묶기와 비교에 쓰는 이름. 화면 글자는 pname이다 // 등록부 misc는 등록부 프로젝트에 속하지 않는 일(PC 점검, 조사, 선정)이고 화면에서는 기타다
  // 세션 기록은 질문과 작업을 넣는 Main 세션이다. 시작 폴더의 프로젝트나 지난 주제 이름 대신 Main 세션과 시작 시각으로 부른다
  const runName = (r) => ((r.run_id || "").startsWith("session-") ? T("Main 세션 {t}", { t: mdhm(parse(r.started)) }).trim() : `${pname(r.project)} / ${r.title}`);
  const runNo = (id) => ((id || "").match(/-([^-]+)$/) || [])[1] || id || ""; // 실행ID의 마지막 토막. 261025-jipsa-31이면 31이다
  const recLabel = (o, i) => (i === 0 && !o.includes("추천") ? `(추천) ${o}` : o); // 문구에 이미 추천 표시가 있으면 더 붙이지 않는다

  // ----- 상단 확인 단추: 확인 필요(끝났는데 확인을 누르지 않은 작업과 상태 값이 확인 필요인 답을 넣을 작업) -----
  // 상태는 서버의 확인 기록에 있다(폰과 PC가 같은 것을 본다). 결과지를 여는 것만으로는 바뀌지 않고 결과지 아래 [확인]을 눌러야 빠진다.
  // 확인은 그때의 마감 시각과 같이 적힌다. 이어 돌려 마감 시각이 바뀐 실행은 새 결과라서 다시 확인 필요다
  const CUE_READ = "jipsa.cue.read", CUE_SINCE = "jipsa.cue.since", CUE_MOVED = "jipsa.cue.moved";
  const conf = () => state.data?.confirm || null;
  const finOf = (m) => m.run.finished || "";
  const acked = (m) => { const c = conf(); return !!c && Object.hasOwn(c.acked || {}, m.run.run_id) && c.acked[m.run.run_id] === finOf(m); };
  // 예전 브라우저 저장소의 읽음 기록은 서버로 한 번 옮긴다. 읽은 것은 확인된 것으로 보고, 서버 기준 시각이 없으면 이 브라우저의 기준 시각을 쓴다
  async function moveLocalRead(c) {
    let moved = false, read = [], since = null;
    try { moved = localStorage.getItem(CUE_MOVED) === "1"; read = JSON.parse(localStorage.getItem(CUE_READ) || "[]"); since = localStorage.getItem(CUE_SINCE); } catch (e) { /* 비공개 창 */ }
    if (moved && c.since) return;
    try {
      const r = await fetch("/api/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "migrate", read, since }) });
      const d = await r.json();
      if (d.ok) { try { localStorage.setItem(CUE_MOVED, "1"); } catch (e) { /* 저장 못 해도 서버 쪽은 같은 결과다 */ } if (state.data) { state.data.confirm = d.confirm; render(); } }
    } catch (e) { /* 다음 주기에 다시 한다 */ }
  }
  // 확인 여부 판정은 이 한 곳이다. 상단 확인 필요 개수, 타임라인 막대와 필터 칩, 서랍 머리 배지, 결과지 아래 확인 단추가 모두 이것을 쓴다.
  // 작업자 실행과 세션 서브에이전트 실행을 가르지 않는다. 결과지가 없는 세션 기록(세션 자신과 주제 조각)과 진행 중 작업만 뺀다.
  // 돌려주는 값: hold(상태 값 확인 필요, 답을 넣을 것), cue(기준 시각 뒤에 끝났고 확인 전인 완료와 실패), "" (확인됨 또는 해당 없음)
  // 상태 값 확인 필요는 답을 넣거나(큐에서 처리 대기) 답 없이 확인하면 빠진다(261022-jipsa-57)
  const ackState = (runId, status, finished) => {
    if (state.view !== "live" || !conf() || (runId || "").startsWith("session-")) return "";
    const m = { run: { run_id: runId, finished: finished || "" } };
    if (status === "확인 필요" || status === "판단 대기") return acked(m) || answeredOf(state.data).has(runId) ? "" : "hold";
    if (status !== "완료" && status !== "실패") return "";
    const since = parse(conf().since), end = parse(finished);
    return !acked(m) && since && end && end > since ? "cue" : "";
  };
  const ackOf = (m) => (m.piece ? "" : ackState(m.run.run_id, m.status, finOf(m)));
  const isCue = (m) => ["hold", "cue"].includes(ackOf(m));
  // 보이는 상태 하나. 서버의 confirm.shown과 같은 규칙이다(261025-jipsa-04). 상태 값 확인 필요는 답 없이 확인하면 확인함(답이 큐에 들어가 처리 대기면 확인 필요 그대로),
  // 확인하지 않은 완료와 실패는 확인 필요, 나머지와 지난 기록은 상태 값 그대로다
  const shownOf = (runId, status, finished) => {
    if (state.view !== "live" || !conf() || (runId || "").startsWith("session-")) return status;
    const a = ackState(runId, status, finished);
    if (status === "확인 필요" || status === "판단 대기") return a === "hold" || answeredOf(state.data).has(runId) ? "확인 필요" : "확인함";
    return a === "cue" ? "확인 필요" : status;
  };
  // 화면에 적는 상태 이름. 확인하지 않은 완료는 확인 필요다(옛 이름 확인 전 완료, 261023-jipsa-26). 실패는 실패로 두고 주황 테두리로 가른다
  const shownStatus = (m) => { const s = m.piece ? m.status : shownOf(m.run.run_id, m.status, finOf(m)); return s === "확인 필요" && m.status === "실패" ? "실패" : s; };
  // 작업자 실행은 답을 넣어도 스케줄러가 이어 돌릴 때까지 기록이 확인 필요다. 큐에서 답을 받아 대기 중인 실행ID와 답이다
  const answeredOf = (data) => new Map(state.view === "live" ? (data?.pending || []).filter((r) => r.answer && r.run_id).map((r) => [r.run_id, r.answer]) : []);
  const isAnswered = (m) => m.status === "확인 필요" && answeredOf(state.data).has(m.run.run_id);
  // 상태 값 확인 필요 막대 가운데 아직 사람 몫인 것(주황)과 답 없이 확인한 것(확인함, 완료처럼 초록)을 가른다. 지난 기록은 확인 기록이 없어 모두 주황이다
  const isHold = (m) => m.status === "확인 필요" && !m.piece && shownOf(m.run.run_id, m.status, finOf(m)) === "확인 필요";
  const isAckedHold = (m) => m.status === "확인 필요" && !m.piece && shownOf(m.run.run_id, m.status, finOf(m)) === "확인함";
  const holdText = (m) => (isAnswered(m) ? T("답 들어감, 처리 대기") : isAckedHold(m) ? T("확인함(답 없이 확인, 상태 값과 큐 보류는 그대로)") : m.status === "확인 필요" ? T("확인 필요, 답을 넣을 것") : ackOf(m) === "cue" ? (m.status === "실패" ? T("확인 필요(실패)") : T("확인 필요")) : stName(m.status));
  // 확인 필요 큐(261023-jipsa-37 3안). 머리 숫자, 확인 필요 탭 배지, 현황판 카드, 확인 필요 탭 목록이 모두 이 목록을 센다.
  // 서버가 24시간 창과 무관하게 모든 실행 기록에서 같은 규칙(ackState)으로 고른다. 확인이나 답을 넣은 뒤 다음 응답 전까지는 이 창의 확인 기록으로 먼저 뺀다
  const liveCue = () => {
    if (state.view !== "live" || !state.data) return [];
    return (state.data.cue || []).filter((c) => (c.todo ? !(conf()?.acked || {})[c.run_id] || conf().acked[c.run_id] !== c.finished : ["hold", "cue"].includes(ackState(c.run_id, c.status, c.finished))));
  };
  const cueIds = () => new Set(liveCue().map((c) => c.run_id));

  // ----- 모델: 이벤트에서 단계, 구간, 대기, 재시도, 도구 트리를 만든다 -----
  function model(run, vnow) {
    const evs = (run.events || []).filter((e) => parse(e.ts) <= vnow);
    const stages = [], segments = [], waits = [], retries = [], attempts = new Map(), ended = new Map();
    const openStage = new Map(), openSeg = new Map();
    const started = parse(run.started);
    for (const e of evs) {
      const ts = parse(e.ts);
      const a = e.attempt || 1;
      if (e.attempt) attempts.set(a, attempts.get(a) || { n: a, stages: new Map() });
      if (e.kind === "stage_start") openStage.set(`${a}:${e.stage}`, { attempt: a, stage: e.stage, start: ts, end: null, open: true });
      else if (e.kind === "stage_end") {
        const s = openStage.get(`${a}:${e.stage}`);
        if (s) { s.end = ts; s.open = false; s.info = e; stages.push(s); openStage.delete(`${a}:${e.stage}`); }
      } else if (e.kind === "segment_start") openSeg.set(`${a}:${e.segment}`, { attempt: a, n: e.segment, start: ts, end: null, tools: [], judge: null });
      else if (e.kind === "segment_end") {
        const s = openSeg.get(`${a}:${e.segment}`);
        if (s) { s.end = ts; s.info = e; segments.push(s); openSeg.delete(`${a}:${e.segment}`); }
      } else if (e.kind === "judge") {
        const s = openSeg.get(`${a}:${e.segment}`) || segments.find((x) => x.attempt === a && x.n === e.segment);
        if (s) s.judge = e;
      } else if (e.kind === "tool") {
        const s = openSeg.get(`${a}:${e.segment}`) || segments.find((x) => x.attempt === a && x.n === e.segment);
        const t = { ts, tool: e.tool, summary: e.summary, id: e.tool_id, parent: e.parent, stage: e.stage, attempt: a, children: [], kids: e.kids || 0, last_kid: e.last_kid || "" };
        if (s) s.tools.push(t);
        else {
          const st = openStage.get(`${a}:${e.stage}`) || stages.find((x) => x.attempt === a && x.stage === e.stage);
          if (st) (st.tools = st.tools || []).push(t);
        }
      } else if (e.kind === "wait_resource" || e.kind === "limit_wait") {
        const end = e.until ? parse(e.until) : new Date(ts.getTime() + 5 * 60000);
        waits.push({ start: ts, end: end > vnow ? vnow : end, kind: e.kind, why: e.why || "" });
      } else if (e.kind === "retry") retries.push({ ts, next: e.next, cause: e.cause });
      else if (e.kind === "agent_end" && e.tool_id) ended.set(e.tool_id, ts);
    }
    for (const s of openStage.values()) { s.end = vnow; stages.push(s); }
    for (const s of openSeg.values()) { s.end = vnow; s.open = true; segments.push(s); }
    for (const seg of segments) seg.tools = nest(seg.tools);
    for (const st of stages) if (st.tools) st.tools = nest(st.tools);
    stages.sort((a, b) => a.start - b.start);
    segments.sort((a, b) => a.start - b.start);
    const last = evs.length ? evs[evs.length - 1] : null;
    const lastTool = [...evs].reverse().find((e) => e.kind === "tool");
    const finished = parse(run.finished);
    const status = finished && finished <= vnow ? run.status : (started <= vnow ? "진행 중" : "대기");
    return { run, started, stages, segments, waits, retries, status, last, lastTool, ended, attempts: [...attempts.keys()].sort((a, b) => a - b),
             end: finished && finished <= vnow ? finished : vnow };
  }
  // 진행 중이거나 재생 중이면 지금 시각까지 쓴 분, 끝났으면 기록된 분
  const usedMin = (m) => (m.status === "진행 중" || m.run.minutes_used == null) ? mins(m.started, m.end) : m.run.minutes_used;
  // 서브에이전트의 하위 도구 수. 상태 응답은 하위 도구 줄을 빼고 수(kids)만 준다(261023-jipsa-37). 결과지 서랍의 전체 사건은 줄을 센다
  const kidsN = (t) => Math.max(t.children.length, t.kids || 0);
  function nest(tools) {
    const byId = new Map(tools.map((t) => [t.id, t]));
    const roots = [];
    for (const t of tools) { const p = t.parent && byId.get(t.parent); if (p) p.children.push(t); else roots.push(t); }
    return roots;
  }

  // ----- 타임라인: 프로젝트별 한 줄(수영 레인). 같은 프로젝트의 작업은 한 줄에 막대로 놓이고 서브에이전트는 막대 아래 얇은 표식이다 -----
  const WINDOW_H = () => +($("tlWindow")?.value || 6);
  const isSession = (m) => (m.run.run_id || "").startsWith("session-"); // hook이 기록한 세션 자신. 세션이 한 프로젝트 작업은 프로젝트 줄에 간다
  // 세션이 jipsa topic으로 건 주제마다 한 조각을 만든다. 주제가 없으면 세션 전체가 한 조각이다
  const ETC_KEY = "jipsa.tl.etcOpen";
  const etcOpen = () => { try { return localStorage.getItem(ETC_KEY) !== "0"; } catch { return true; } };
  const setEtcOpen = (v) => { try { localStorage.setItem(ETC_KEY, v ? "1" : "0"); } catch { /* 저장이 막혀도 화면은 돈다 */ } };
  // 끝난 일을 펼친 프로젝트 줄. 기본은 접힘이고 이 창에 기억한다(4안)
  const FOLD_KEY = "jipsa.tl.foldOpen";
  const foldOpen = () => { try { return new Set(JSON.parse(localStorage.getItem(FOLD_KEY) || "[]")); } catch { return new Set(); } };
  const toggleFold = (k) => { const s = foldOpen(); if (s.has(k)) s.delete(k); else s.add(k); try { localStorage.setItem(FOLD_KEY, JSON.stringify([...s])); } catch { /* 저장이 막혀도 화면은 돈다 */ } render(); };
  // 상태 표기 한 벌(8안). 모든 탭이 같은 이름, 색, 모양을 쓴다: 완료 초록 고리, 진행 중 파랑 원, 확인 필요 주황 마름모, 실패 빨강 네모, 대기 회색 고리, 멈춤 노랑 두 막대
  const ST_CLS = { "완료": "done", "확인함": "done", "진행 중": "run", "확인 필요": "cue", "판단 대기": "cue", "실패": "fail", "대기": "todo", "건너뜀": "todo", "멈춤": "stop" };
  function stShape(cls, cx, cy) {
    const g = svgEl("g", { class: `sh ${cls}` });
    if (cls === "run") g.appendChild(svgEl("circle", { cx, cy, r: 5 }));
    else if (cls === "done" || cls === "todo") g.appendChild(svgEl("circle", { cx, cy, r: 4.2 }));
    else if (cls === "cue") g.appendChild(svgEl("rect", { x: cx - 4, y: cy - 4, width: 8, height: 8, transform: `rotate(45 ${cx} ${cy})` }));
    else if (cls === "fail") g.appendChild(svgEl("rect", { x: cx - 4.5, y: cy - 4.5, width: 9, height: 9 }));
    else if (cls === "stop") { g.appendChild(svgEl("rect", { x: cx - 4.5, y: cy - 5, width: 3, height: 10 })); g.appendChild(svgEl("rect", { x: cx + 1.5, y: cy - 5, width: 3, height: 10 })); }
    return g;
  }
  // 첫 주제는 세션 시작부터 잡는다(주제를 걸기 전의 몇 분도 그 일이다). 주제의 프로젝트가 없으면 시작 폴더의 프로젝트, 그것도 없으면 기타다
  function sessionPieces(m) {
    const home = pkey(m.run.cwd_project || "기타");
    const ts = (m.run.topics || []).map((t) => ({ start: parse(t.ts), ended: t.ended ? parse(t.ended) : null, title: t.title, project: pkey(t.project || home), run_id: t.run_id || "" })).filter((t) => t.start < m.end && t.start >= m.started);
    if (!ts.length) return [];
    ts[0].start = m.started;
    // jipsa topic --done으로 닫힌 주제는 그 시각에 끝나고 완료다. 닫힌 뒤 다음 주제 전까지는 세션이 일하지 않으므로 어느 줄에도 그리지 않는다
    return ts.map((t, i) => {
      const next = i + 1 < ts.length ? ts[i + 1].start : m.end;
      const closed = t.ended && t.ended <= next;
      return { start: t.start, title: t.title, project: t.project, run_id: t.run_id, end: closed ? new Date(Math.max(t.ended, t.start)) : next, closed: !!closed };
    });
  }
  function pieceModel(m, pc) {
    const live = m.status === "진행 중" && pc.end === m.end && !pc.closed;
    return { ...m, piece: true, started: pc.start, end: pc.end, status: live ? "진행 중" : "완료", waits: [], retries: [], stages: [],
             run: { ...m.run, title: pc.title, minutes_limit: 0, minutes_used: mins(pc.start, pc.end) } };
  }
  const TL_EMPTY = $("tlEmpty").__tKey || $("tlEmpty").textContent, FILTER_KEY = "jipsa.tl.filter";
  const tlSel = () => [...document.querySelectorAll("#tlFilter input:checked")].map((i) => i.value);
  // 확인 필요 칩은 배지가 세는 기준(isCue)에 상태 값 확인 필요 막대 전부를 더한 것이다. 답을 넣고 처리를 기다리는 막대도 남긴다
  // 확인하지 않은 완료도 확인 필요 칩에 든다. 따로 있던 확인 전 완료 칩은 없앴다(261023-jipsa-26)
  // 답 없이 확인한 상태 값 확인 필요(확인함)는 완료 칩에 든다(261025-jipsa-04)
  const TL_TEST = { run: (m) => m.status === "진행 중", done: (m) => (m.status === "완료" || isAckedHold(m)) && !isCue(m), fail: (m) => m.status === "실패", cue: (m) => isHold(m) || isCue(m) };
  const tlKeep = () => { const sel = tlSel(); return sel.length ? (m) => sel.some((k) => TL_TEST[k](m)) : null; };
  try { const f = JSON.parse(localStorage.getItem(FILTER_KEY) || "[]"); for (const i of document.querySelectorAll("#tlFilter input")) i.checked = f.includes(i.value); } catch (e) { /* 비공개 창 */ }
  $("tlFilter").addEventListener("change", () => { try { localStorage.setItem(FILTER_KEY, JSON.stringify(tlSel())); } catch (e) { /* 저장 못 해도 된다 */ } render(); });
  // 물음표 단추: 칩에 없는 표식(대기, 서브에이전트, 재시도, Auto 마감) 설명 상자. 바깥을 누르거나 Esc로 닫는다
  const helpBtn = $("tlHelpBtn"), helpBox = $("tlHelp");
  const setHelp = (open) => { helpBox.hidden = !open; helpBtn.setAttribute("aria-expanded", String(open)); };
  helpBtn.addEventListener("click", (ev) => { ev.preventDefault(); setHelp(helpBox.hidden); });
  document.addEventListener("click", (ev) => { if (!helpBox.hidden && !ev.target.closest(".tlhelp")) setHelp(false); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !helpBox.hidden) setHelp(false); });
  let tlCycles = new Set(); // 막대 그림의 보기 범위 안에 실행이 있는 목표
  function drawTimeline(runs, vnow, cutoff, nightStart) {
    const host = $("tl");
    host.textContent = ""; tlCycles = new Set();
    const winStart = new Date(vnow.getTime() - WINDOW_H() * 3600000);
    const all = runs.map((r) => model(r, vnow)).filter((m) => m.started <= vnow);
    // 사람 몫인 확인 필요는 보이는 범위보다 먼저 끝났어도 그린다. 상단 확인 필요 단추가 세는 것과 같은 기준이다. 범위 밖이면 막대가 왼쪽 끝에 짧게 붙는다. 답 없이 확인한 것은 범위 안일 때만 그린다
    const models = all.filter((m) => m.status === "진행 중" || isHold(m) || isCue(m) || m.end >= winStart);
    tlCycles = new Set(models.map((m) => m.run.cycle).filter(Boolean)); // 위쪽 목표 줄 묶음이 끝난 목표를 펼칠지 정할 때 쓴다
    $("tlEmpty").hidden = models.length > 0;
    if (!models.length) return [];
    // 줄 묶기: 프로젝트 줄은 첫 작업 순이다. 세션이 그 프로젝트에 건 주제는 프로젝트 줄 바로 아래 한 줄씩 붙는다(작업 막대와 겹치지 않게).
    // 프로젝트 작업이 창 안에 없으면 주제 막대가 프로젝트 줄에 바로 놓인다. 어느 프로젝트에도 속하지 않는 일은 맨 아래 접을 수 있는 "기타" 묶음이다.
    // 등록부 misc의 실행 기록은 기타 묶음 안에 항목마다 한 줄이다. 같은 일을 가리키는 세션 주제(run_id가 적힌 주제)는 그리지 않는다
    const lanes = new Map(), subsOf = new Map(), etc = new Map(), goals = new Map(), laneOf = new Map();
    // 목표 cycle의 실행은 목표 줄 아래 Cycle N 줄로 묶는다(261023-jipsa-11). Cycle 번호는 실행 기록, cycle 기록, 제목 순으로 찾는다.
    // 종합 보고 실행은 목표 줄 아래 맨 끝 한 줄이다. 넘어간 단계는 자동 확인되어 초록이고, 확인 필요는 종합 보고 줄과 예외 단계에만 남는다(261023-jipsa-33).
    // 목표 묶음은 cycle 프로젝트(줄 머리의 프로젝트) 묶음 안, 항목 줄과 같은 층에 둔다. 도는 중이든 끝났든 같은 자리다
    const cycInfo = new Map(((state.data && state.data.scope && state.data.scope.cycles) || []).map((c) => [c.key, c]));
    const roundOf = new Map();
    for (const c of cycInfo.values()) for (const r of c.rounds || []) for (const id of Object.values(r.runs || {})) roundOf.set(id, r.n);
    const sorted = [...models].sort((a, b) => a.started - b.started);
    for (const m of sorted) {
      if (isSession(m)) continue;
      if (m.run.cycle) {
        const ck = m.run.cycle, c = cycInfo.get(ck);
        const gp = (c && c.project) || ck.split("::")[0] || m.run.project, pk = `project:${gp}`;
        if (!goals.has(ck)) goals.set(ck, { key: `goal:${ck}`, name: T("목표 {t}", { t: c ? c.title : ck.split("::").pop() }), runs: [], split: new Set(), goal: c || null, rounds: new Map(), final: null, sub: true, goalHead: true, pk });
        const g = goals.get(ck); g.runs.push(m); g.split.add(m);
        if (!lanes.has(pk)) lanes.set(pk, { key: pk, name: gp, runs: [], split: new Set() });
        lanes.get(pk).runs.push(m); lanes.get(pk).split.add(m); // 프로젝트 머리 줄은 상태만 모으고 막대는 목표 묶음 줄에 그린다
        if (m.run.cycle_step === FINAL_STEP || (c && c.final && c.final.run_id === m.run.run_id)) {
          if (!g.final) g.final = { key: `${g.key}:final`, name: T("종합 보고"), runs: [], sub: true, deep: true, final: true };
          g.final.runs.push(m); continue;
        }
        const n = m.run.cycle_round ?? roundOf.get(m.run.run_id) ?? +((m.run.title.match(/Cycle (\d+)|(\d+)바퀴/) || []).slice(1).find(Boolean) || 0);
        if (!g.rounds.has(n)) g.rounds.set(n, { key: `${g.key}:r${n}`, name: n ? `Cycle ${n}` : T("Cycle 미상"), runs: [], sub: true, deep: true, n });
        g.rounds.get(n).runs.push(m); continue;
      }
      if (m.run.project === "misc") { // 같은 이름의 기타 주제와 한 줄을 쓴다
        if (!etc.has(m.run.title)) etc.set(m.run.title, { key: `etc:${m.run.title}`, name: m.run.title, runs: [], sub: true });
        etc.get(m.run.title).runs.push(m); continue;
      }
      const k = `project:${m.run.project}`;
      if (!lanes.has(k)) lanes.set(k, { key: k, name: m.run.project, runs: [], split: new Set() });
      lanes.get(k).runs.push(m); lanes.get(k).split.add(m);
      // 원 실행에서 나온 실행(검수, 반영, 답 반영)은 원 실행 줄에 그린다. 원 실행이 창 밖이면 제 항목 줄을 쓴다
      const from = m.run.from_run && laneOf.get(m.run.from_run);
      if (from) { from.runs.push(m); laneOf.set(m.run.run_id, from); continue; }
      // 작업자 실행도 서브에이전트 실행처럼 프로젝트 줄 아래 항목마다 한 줄이다. 머리 줄은 상태만 모은다(261023-jipsa-01 버그 4)
      // 세션 서브에이전트 실행은 실행 번호마다 한 줄이고 이름 앞에 번호를 붙인다. 툴팁에 서브에이전트 이름을 적는다(261025-jipsa-34)
      if (!subsOf.has(k)) subsOf.set(k, new Map());
      const sa = m.run.executor === "subagent";
      const ik = sa ? `run:${m.run.run_id}` : `item:${m.run.title}`, subs = subsOf.get(k);
      if (!subs.has(ik)) subs.set(ik, { key: `${k}:${ik}`, name: sa ? `${runNo(m.run.run_id)} ${m.run.title}` : m.run.title, runs: [], sub: true,
                                        tip: sa ? `${m.run.run_id} ${m.run.title}${m.run.agent ? `
${T("서브에이전트")} ${m.run.agent}` : ""}` : "" });
      subs.get(ik).runs.push(m); laneOf.set(m.run.run_id, subs.get(ik));
    }
    for (const m of sorted.filter(isSession)) {
      for (const pc of sessionPieces(m)) {
        if (pc.end < winStart || pc.run_id) continue;
        const pm = pieceModel(m, pc);
        if (pc.project === "기타") {
          if (!etc.has(pc.title)) etc.set(pc.title, { key: `etc:${pc.title}`, name: pc.title, runs: [], sub: true });
          etc.get(pc.title).runs.push(pm); etc.get(pc.title).runs.sort((x, y) => x.started - y.started);
          continue;
        }
        const k = `project:${pc.project}`;
        if (!lanes.has(k)) lanes.set(k, { key: k, name: pc.project, runs: [], topicOnly: true });
        const lane = lanes.get(k);
        if (lane.topicOnly) { lane.runs.push(pm); continue; }
        if (!subsOf.has(k)) subsOf.set(k, new Map());
        const subs = subsOf.get(k);
        if (!subs.has(pc.title)) subs.set(pc.title, { key: `${k}:${pc.title}`, name: pc.title, runs: [], sub: true });
        subs.get(pc.title).runs.push(pm);
      }
    }
    // 상태 필터: 체크한 것 중 하나라도 맞으면 보인다(아무것도 안 체크하면 전부). 줄이 다 비면 그 줄과 묶음을 뺀다
    const keep = tlKeep();
    if (keep) {
      for (const [k, lane] of [...lanes]) {
        const subs = subsOf.get(k);
        if (subs) for (const [sk, sub] of [...subs]) { sub.runs = sub.runs.filter(keep); if (!sub.runs.length) subs.delete(sk); }
        lane.runs = lane.runs.filter(keep);
        if (!lane.runs.length && subs?.size) { lane.runs = [...subs.values()].flatMap((l) => l.runs); lane.split = new Set(lane.runs); } // 머리 줄은 상태만 모은다
        if (!lane.runs.length) lanes.delete(k);
      }
      for (const [k, l] of [...etc]) { l.runs = l.runs.filter(keep); if (!l.runs.length) etc.delete(k); }
      for (const [k, g] of [...goals]) {
        for (const [n, r] of [...g.rounds]) { r.runs = r.runs.filter(keep); if (!r.runs.length) g.rounds.delete(n); }
        if (g.final) { g.final.runs = g.final.runs.filter(keep); if (!g.final.runs.length) g.final = null; }
        g.runs = g.runs.filter(keep); if (!g.runs.length) goals.delete(k);
      }
      if (!lanes.size && !etc.size && !goals.size) { $("tlEmpty").textContent = T("필터에 맞는 항목이 없다."); $("tlEmpty").hidden = false; return models; }
    }
    $("tlEmpty").textContent = T(TL_EMPTY);
    // 끝난 일 접기(261023-jipsa-38 4안). 끝나고 확인한 완료만 있는 항목 줄은 프로젝트 머리 줄에 막대로 모으고 오른쪽 칸에 "완료 N"을 적는다.
    // 진행 중, 확인 필요, 실패가 든 줄은 펼친 채다. 머리 줄의 화살표나 "완료 N"을 누르면 그 프로젝트만 펼친다. 상태 필터를 걸면 접지 않는다
    const settled = (m) => (m.status === "완료" || isAckedHold(m)) && !isCue(m); // 답 없이 확인한 확인 필요도 끝나고 확인한 것이다
    // 끝난 목표 묶음도 모든 실행이 확인된 완료이면 같이 접는다
    if (!keep) for (const [k, lane] of lanes) {
      if (lane.topicOnly) continue;
      const subs = subsOf.get(k) || new Map();
      const done = [...subs].filter(([, s]) => s.runs.every(settled));
      const doneGoals = [...goals.values()].filter((g) => g.pk === k && g.goal?.status === "끝" && g.runs.every(settled));
      if (!done.length && !doneGoals.length) continue;
      const open = foldOpen().has(k);
      lane.fold = { n: done.reduce((a, [, s]) => a + s.runs.length, 0) + doneGoals.reduce((a, g) => a + g.runs.length, 0), open };
      if (!open) {
        for (const [sk, s] of done) { subs.delete(sk); lane.foldRuns = (lane.foldRuns || []).concat(s.runs); }
        for (const g of doneGoals) { g.folded = true; lane.foldRuns = (lane.foldRuns || []).concat(g.runs); }
      }
    }
    const rows = [];
    for (const lane of [...lanes.values()].sort((a, b) => a.runs[0].started - b.runs[0].started)) {
      rows.push(lane);
      // 항목 줄과 목표 묶음을 시작 순으로 섞는다. 목표 묶음은 목표 줄, Cycle N 줄, 끝나면 종합 보고 줄이다
      const kids = [...(subsOf.get(lane.key)?.values() || []), ...[...goals.values()].filter((g) => g.pk === lane.key && !g.folded)];
      for (const kid of kids.sort((a, b) => a.runs[0].started - b.runs[0].started)) {
        rows.push(kid);
        if (!kid.goalHead) continue;
        rows.push(...[...kid.rounds.values()].sort((a, b) => a.n - b.n));
        if (kid.final) rows.push(kid.final); // 종합 보고 줄은 목표 묶음의 맨 끝이다
      }
    }
    if (etc.size) {
      const open = etcOpen();
      const subs = [...etc.values()].sort((a, b) => a.runs[0].started - b.runs[0].started);
      rows.push({ key: "etc", name: `${T("기타")} (${subs.length})`, header: true, runs: subs.flatMap((l) => l.runs).sort((a, b) => a.started - b.started) });
      if (open) rows.push(...subs);
    }
    // 자식 실행(jipsa begin으로 띄운 서브에이전트)이 있는 Agent 표식은 그리지 않는다
    const childStarts = models.filter((m) => m.run.parent_run).map((m) => ({ parent: m.run.parent_run, ts: m.started.getTime() }));
    const isLinked = (m, t) => childStarts.some((c) => c.parent === m.run.run_id && Math.abs(c.ts - t.ts.getTime()) < 120000);

    let tmin = Math.max(winStart.getTime(), Math.min(...models.map((m) => m.started.getTime())));
    let tmax = Math.max(...models.map((m) => m.end.getTime()), vnow.getTime());
    if (cutoff) { tmax = Math.max(tmax, cutoff.getTime() + 20 * 60000); }
    // 짧은 창은 왼쪽을 10분 단위로 내리고 여백도 줄여 빈 공간이 창보다 커지지 않게 한다
    const short = WINDOW_H() <= 1;
    tmin = short ? Math.floor(tmin / 600000) * 600000 - 300000 : Math.floor(tmin / 1800000) * 1800000 - 600000;
    tmax = tmax + (short ? 5 : 15) * 60000;
    // 좁은 화면(5안)은 그림을 줄이지 않고 760px로 그려 타임라인 칸 안에서만 가로로 민다. 이름 칸은 왼쪽에 붙어 따라온다
    const narrow = host.clientWidth < 700;
    const width = narrow ? 760 : Math.max(host.clientWidth, 960);
    const plotW = width - LABEL_W - RIGHT;
    const x = (t) => LABEL_W + Math.max(0, Math.min(plotW, ((t - tmin) / (tmax - tmin)) * plotW));
    const height = TOP + rows.length * ROW_H + 10;
    const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
    if (narrow) { svg.style.width = `${width}px`; svg.style.maxWidth = "none"; }
    else { svg.style.width = "100%"; svg.style.maxWidth = "100%"; svg.style.height = "auto"; } // 넓은 창에서 세로 막대가 늦게 생겨 폭이 줄어도 가로 스크롤 없이 비율로 줄인다
    svg.appendChild(svgEl("title", {})).textContent = T("프로젝트별 타임라인");
    // 막대는 그림 영역(이름 칸 오른쪽)에서만 보인다. 가로로 스크롤하면 이름 칸이 왼쪽에 붙어 따라오고 막대는 그 아래로 들어간다
    const clip = svgEl("clipPath", { id: "tlPlotClip" }), clipRect = svgEl("rect", { x: LABEL_W, y: 0, width: plotW + RIGHT, height });
    clip.appendChild(clipRect); svg.appendChild(clip);
    const stuck = [];

    if (nightStart && cutoff) {
      svg.appendChild(svgEl("rect", { class: "night", x: x(Math.max(nightStart.getTime(), tmin)), y: TOP - 6, width: Math.max(0, x(Math.min(cutoff.getTime(), tmax)) - x(Math.max(nightStart.getTime(), tmin))), height: height - TOP }));
    }
    const grid = svgEl("g", { class: "grid" }), axis = svgEl("g", { class: "axis" });
    const span = tmax - tmin, stepMs = span > 14 * 3600000 ? 2 * 3600000 : span > 5 * 3600000 ? 3600000 : span > 2 * 3600000 ? 1800000 : span > 50 * 60000 ? 600000 : 300000;
    const cutX = cutoff && cutoff.getTime() >= tmin && cutoff.getTime() <= tmax ? x(cutoff.getTime()) : null;
    for (let t = Math.ceil(tmin / stepMs) * stepMs; t <= tmax; t += stepMs) {
      grid.appendChild(svgEl("line", { x1: x(t), x2: x(t), y1: TOP - 6, y2: height - 6 }));
      if (cutX !== null && Math.abs(x(t) - cutX) < 46) continue;
      const tx = svgEl("text", { x: x(t), y: 12, "text-anchor": "middle" }); tx.textContent = hhmm(new Date(t)); axis.appendChild(tx);
    }
    svg.appendChild(grid); svg.appendChild(axis);
    if (cutX !== null) {
      const dl = svgEl("line", { class: "dawn", x1: cutX, x2: cutX, y1: TOP - 6, y2: height - 6 }); svg.appendChild(dl);
      const t = svgEl("text", { class: "dawn-label", x: cutX, y: 12, "text-anchor": "middle" }); t.textContent = T("종료 {t}", { t: hhmm(cutoff) }); svg.appendChild(t);
      for (const n of [dl, t]) tip(n, () => [[T("Auto 마감"), hhmm(cutoff)], [T("Auto 모드가 새 Cycle을 멈추는 시각"), ""]]);
    }
    if (vnow.getTime() >= tmin && vnow.getTime() <= tmax) {
      svg.appendChild(svgEl("line", { class: "nowline", x1: x(vnow.getTime()), x2: x(vnow.getTime()), y1: TOP - 6, y2: height - 6 }));
    }
    const counts = [], barLabels = [];
    rows.forEach((lane, i) => {
      const y = TOP + i * ROW_H + ROW_H / 2;
      const live = lane.runs.filter((m) => m.status === "진행 중");
      const latest = lane.runs[lane.runs.length - 1];
      const g = svgEl("g", { class: `row lane${live.length ? " st-진행 중" : ` st-${latest.status}`}` });
      // 줄마다 옅은 띠를 깔아 이름과 막대가 같은 줄임이 보이게 한다. 짝수 줄만 칠하고, 올리면 밝아진다
      g.appendChild(svgEl("rect", { class: `band${i % 2 ? " even" : ""}`, x: 0, y: y - ROW_H / 2, width, height: ROW_H }));
      const lg = svgEl("g", { class: "lab-g" }); // 이름 칸: 스크롤하면 왼쪽에 붙는다. 불투명 바탕이 막대를 가린다
      lg.appendChild(svgEl("rect", { class: `lab-bg${i % 2 ? " even" : ""}`, x: 0, y: y - ROW_H / 2, width: LABEL_W - 4, height: ROW_H }));
      stuck.push(lg);
      const goalHead = !!lane.goalHead;
      const lab = svgEl("text", { class: `row-label${lane.sub ? " sub" : ""}${lane.header ? " etc-head" : ""}${goalHead ? " goal-head" : ""}${lane.final ? " final" : ""}`, x: lane.deep ? 48 : lane.sub ? 34 : 20, y: y + 4, tabindex: 0, role: "button" });
      lab.textContent = lane.name === "기타" ? T("기타") : lane.name; lab.dataset.full = lane.name; lg.appendChild(lab); // 자르는 일은 그린 뒤 실제 글 폭으로 한다
      lg.appendChild(svgEl("title", {})).textContent = lane.tip || lane.name; // 이름 칸은 줄임표로 줄어드므로 전체 이름은 툴팁이다
      if (lane.header) { // 기타는 최상위 줄이다. 접고 펴는 화살표는 이름 왼쪽 여백에 두어 프로젝트 이름과 글자 위치를 맞춘다
        lab.setAttribute("aria-expanded", String(etcOpen()));
        const arrow = svgEl("text", { class: "etc-arrow", x: 6, y: y + 4 }); arrow.textContent = etcOpen() ? "▾" : "▸";
        arrow.addEventListener("click", () => { setEtcOpen(!etcOpen()); render(); }); lg.appendChild(arrow);
      }
      if (lane.fold) { // 끝난 일 접기 화살표. 기타 묶음과 같은 자리다
        const arrow = svgEl("text", { class: "etc-arrow fold-arrow", x: 6, y: y + 4, role: "button", tabindex: 0, "aria-expanded": String(lane.fold.open) });
        arrow.textContent = lane.fold.open ? "▾" : "▸"; arrow.appendChild(svgEl("title", {})).textContent = lane.fold.open ? T("끝난 일 접기") : T("끝난 일 펼치기");
        arrow.addEventListener("click", () => toggleFold(lane.key));
        arrow.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleFold(lane.key); } });
        lg.appendChild(arrow);
      }
      // 태스크 줄로 내린 작업은 머리 줄에 다시 그리거나 세지 않는다. 접은 완료 줄의 막대는 머리 줄에 그린다
      const own = (lane.split ? lane.runs.filter((m) => !lane.split.has(m)) : lane.runs).concat(lane.foldRuns || []);
      const mine = own.filter(isCue);
      if (mine.length) counts.push({ lab, g: lg, n: mine.length, hold: mine.filter((m) => m.status === "확인 필요").length });
      const act = () => { if (lane.header) { setEtcOpen(!etcOpen()); render(); } else openResult((live[0] || latest).run.run_id); };
      lab.addEventListener("click", act);
      lab.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); act(); } });
      for (const m of (lane.header && etcOpen() ? [] : own)) { // 펼친 기타 머리 줄은 아래 주제 줄과 겹치므로 막대를 그리지 않는다
        const mg = svgEl("g", { "clip-path": "url(#tlPlotClip)", class: `run st-${isAckedHold(m) ? "완료" : m.status}${isHold(m) ? " hold" : ""}${isAnswered(m) ? " answered" : ""}${m.status !== "확인 필요" && isCue(m) ? " cue-unread" : ""}` }); // 상태 값 확인 필요와 확인하지 않은 완료 모두 같은 주황 막대, 답 없이 확인한 확인 필요는 완료처럼 초록
        for (const w of m.waits) {
          const wr = svgEl("rect", { class: "wait", x: x(w.start.getTime()), y: y - BAR_H / 2, width: Math.max(2, x(w.end.getTime()) - x(w.start.getTime())), height: BAR_H, rx: 3 });
          tip(wr, () => [[w.kind === "limit_wait" ? T("한도 대기") : T("자원 대기"), `${hhmm(w.start)} ~ ${hhmm(w.end)}`], ...(w.why ? [[T("사유"), w.why]] : [])]); mg.appendChild(wr);
        }
        const x0 = x(m.started.getTime()), x1 = Math.max(x0 + (isHold(m) ? 12 : 4), x(m.end.getTime()));
        const cutL = m.started.getTime() < tmin, cutR = m.end.getTime() > tmax; // 범위 밖에서 시작했거나 범위 뒤로 이어지는 막대: 끝을 잘라 그리고 작은 삼각형을 남긴다
        const rowsTip = () => [[m.run.title, ""], [`${m.end < winStart ? `${mdhm(m.started)}` : hhmm(m.started)} ~ ${m.status === "진행 중" ? T("진행 중") : hhmm(m.end)}`, dur(usedMin(m), m.run.minutes_limit)], [T("상태"), holdText(m)], ...(stallText(m) ? [[T("멈춤"), T("{n}분 무활동. 띄운 세션에 깨우라고 알렸다", { n: m.run.stall_min })]] : []), ...(budgetText(m.run) ? [[T("판 수 상한"), budgetText(m.run)]] : []), ...(m.run.label ? [[T("결과"), m.run.label]] : []), ...(atkText(m.run) ? [[T("Sol 공격"), atkText(m.run)]] : []), ...(m.run.executor ? [[T("주체"), T(EXECUTOR[m.run.executor] || m.run.executor)]] : []), ...(m.run.agent ? [[T("서브에이전트"), m.run.agent]] : [])];
        if (m.status === "진행 중" && m.stages.length && m.run.executor !== "session") {
          for (const st of m.stages) { // 진행 중인 작업자는 단계 색으로
            const sx0 = x(st.start.getTime()), sx1 = Math.max(sx0 + 3, x(st.end.getTime()));
            const r = svgEl("rect", { class: `bar ${st.stage}${st.open ? " pulse" : ""}`, x: sx0, y: y - BAR_H / 2, width: sx1 - sx0, height: BAR_H, rx: 3, tabindex: 0 });
            tip(r, () => [[T("{s} (시도 {n})", { s: T(STAGE_NAME[st.stage] || st.stage), n: st.attempt }), ""], ...rowsTip()]);
            r.addEventListener("click", () => openResult(m.run.run_id)); mg.appendChild(r);
          }
        } else {
          const r = svgEl("rect", { class: `bar run${m.status === "진행 중" ? " pulse" : ""}`, x: x0, y: y - BAR_H / 2, width: x1 - x0, height: BAR_H, rx: 3, tabindex: 0 });
          tip(r, rowsTip); r.addEventListener("click", () => openResult(m.run.run_id)); mg.appendChild(r);
        }
        if (m.piece && (lane.header || lane.topicOnly)) mg.appendChild(svgEl("line", { class: "topic-sep", x1: x0, x2: x0, y1: y - BAR_H / 2, y2: y + BAR_H / 2 })); // 접힌 기타 줄에서 주제 경계
        const bl = { t: null, atk: null, right: x1 - (cutR ? 12 : 4) }; // 막대 안 글. 폭은 그린 뒤 재서 자른다
        if (x1 - x0 > 60) { // 막대가 넓으면 이름을 안에 쓴다. 전체 제목은 막대 툴팁 첫 줄이다
          const pad = cutL ? 14 : 6;
          bl.t = svgEl("text", { class: "bar-label", x: x0 + pad, y: y + 4 }); bl.t.textContent = m.run.title; mg.appendChild(bl.t);
        }
        if (atkShort(m.run) && x1 - x0 > 220) { // 넓은 막대 오른쪽 끝에 작은 공격 표시. 좁으면 툴팁에만 둔다
          bl.atk = svgEl("text", { class: "atk-label", x: x1 - 6, y: y + 4, "text-anchor": "end" }); bl.atk.textContent = atkShort(m.run); mg.appendChild(bl.atk);
        }
        if (bl.t) barLabels.push(bl);
        if (cutL) mg.appendChild(svgEl("path", { class: "cut-mark", d: `M${x0 + 8},${y - 4} L${x0 + 3},${y} L${x0 + 8},${y + 4} Z` }));
        if (cutR) mg.appendChild(svgEl("path", { class: "cut-mark", d: `M${x1 - 8},${y - 4} L${x1 - 3},${y} L${x1 - 8},${y + 4} Z` }));
        for (const t of flatTools(m)) { // 서브에이전트 표식: 막대 아래 얇은 선
          if (!kidsN(t) || isLinked(m, t)) continue;
          if (m.piece && (t.ts < m.started || t.ts >= m.end)) continue; // 주제 조각에는 그 구간의 서브에이전트만
          const endTs = m.ended.get(t.id) || (m.status === "진행 중" ? vnow : m.end);
          const open = !m.ended.has(t.id) && m.status === "진행 중";
          const ax0 = x(t.ts.getTime()), ax1 = Math.max(ax0 + 3, x(endTs.getTime()));
          const a = svgEl("rect", { class: `agent-mark${open ? " pulse" : ""}`, x: ax0, y: y + BAR_H / 2 + 2, width: ax1 - ax0, height: 4, rx: 2 });
          tip(a, () => [[t.summary, ""], [`${hhmm(t.ts)} ~ ${open ? T("진행 중") : hhmm(endTs)}`, T("{n}분", { n: mins(t.ts, endTs) })], [T("하위 도구"), T("{n}개", { n: kidsN(t) })]]);
          a.addEventListener("click", () => openResult(m.run.run_id)); mg.appendChild(a);
        }
        for (const rt of m.retries) {
          const rg = svgEl("g", { class: "retry" });
          rg.appendChild(svgEl("circle", { cx: x(rt.ts.getTime()), cy: y, r: 7 }));
          const t = svgEl("text", { x: x(rt.ts.getTime()), y: y + 3.5 }); t.textContent = "R"; rg.appendChild(t);
          tip(rg, () => [[T("재시도"), T("시도 {n}", { n: rt.next })], [T("원인"), rt.cause || ""]]); mg.appendChild(rg);
        }
        g.appendChild(mg);
      }
      const show = live[0] || latest;
      // 오른쪽 상태 칸: 상태 모양(8안 한 벌)과 이름, 쓴 분. 멈춘 진행 중은 멈춤 모양이다
      const st = svgEl("text", { class: "status", x: width - RIGHT + 24, y: y + 4 });
      let shape = ST_CLS[shownStatus(show)] || "todo";
      if (show.status === "진행 중" && stallText(show)) shape = "stop";
      const rest = svgEl("tspan", {}); rest.textContent = `${stName(shownStatus(show))}  ${dur(usedMin(show), show.run.minutes_limit)}${stallText(show)}`;
      // 진행 중 실행이 이 줄이 아닌 하위 줄에 그려져 있으면 머리 줄은 하위 줄의 분 수를 되풀이하지 않고 진행 중 건수만 적는다. 멈춘 실행이 있으면 멈춤 모양과 멈춘 건수를 붙인다
      const drawn = lane.header && etcOpen() ? [] : own;
      if (!goalHead && live.some((m) => !drawn.includes(m))) {
        const stalled = live.filter((m) => stallText(m)).length;
        shape = stalled ? "stop" : "run";
        rest.textContent = T("진행 중 {n}건", { n: live.length }) + (stalled ? T("  멈춤 {n}건", { n: stalled }) : "");
        tip(st, () => live.map((m) => [m.run.title, `${dur(usedMin(m), m.run.minutes_limit)}${stallText(m)}`]));
      }
      if (lane.fold && !goalHead) { // 끝난 일을 모은 머리 줄은 "완료 N"이다. 누르면 펼치거나 접는다
        shape = "done"; rest.textContent = `${T("완료")} ${lane.fold.n}  ${lane.fold.open ? T("접기") : T("펼치기")}`;
        st.classList.add("fold-sum"); st.setAttribute("role", "button"); st.setAttribute("tabindex", 0);
        st.addEventListener("click", () => toggleFold(lane.key));
        st.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleFold(lane.key); } });
      }
      if (goalHead && lane.goal) { // 목표 줄의 상태 칸은 지금 위치 한 마디다. 예: Cycle 3, 분석과 피드백 중 / 끝: 목표 도달, 종합 보고 대기
        shape = lane.goal.status === "끝" ? "done" : lane.goal.state_text === "창 멈춤" ? "stop" : "run";
        // 오른쪽 칸이 좁아 줄여 쓴다. 끝난 목표는 ■ 뒤에 종합 보고 상태만, 도는 목표는 단계 이름을 줄인다. 전체 글은 툴팁과 위 목표 줄에 있다
        const w = lane.goal.where || `Cycle ${lane.goal.rounds.length}`;
        rest.textContent = lane.goal.status === "끝" ? w.split(", ").pop() : w.replace("명령 이행", "이행").replace("분석과 피드백", "분석");
        tip(st, () => [[lane.goal.title, ""], [T("위치"), lane.goal.where || ""], [T("상태"), lane.goal.state_text], [T("Cycle 수"), `${lane.goal.rounds.length}`], [T("주체"), lane.goal.owner_text]]);
      }
      const sh = stShape(shape, width - RIGHT + 14, y); if (shape === "run") sh.classList.add("pulse");
      g.appendChild(sh); st.appendChild(rest); g.appendChild(st);
      svg.appendChild(g);
    });
    for (const lg of stuck) svg.appendChild(lg); // 이름 칸을 막대 위에 올린다
    host.appendChild(svg);
    // 이름이 칸보다 길면 줄임표로 줄인다(배지 자리를 남긴다)
    const badgeW = new Map(counts.map((c) => [c.lab, (c.n ? 22 + (String(c.n).length - 1) * 7 : 0)]));
    for (const lab of svg.querySelectorAll(".row-label")) {
      if (!fitText(lab, lab.dataset.full, LABEL_W - 10 - (badgeW.get(lab) || 0))) lab.textContent = `${lab.dataset.full.slice(0, 1)}…`;
    }
    // 막대 안 제목은 막대 오른쪽 끝, 공격 표시가 있으면 그 왼쪽에서 자른다. 글자 수 어림(7px)은 한글 폭보다 작아 제목이 막대 밖과 공격 표시 위로 넘쳤다.
    // 공격 표시 왼쪽 제목 자리가 40px보다 좁으면 공격 표시를 남기고 제목을 뺀다(제목은 막대 툴팁 첫 줄에 있다). 한 글자도 안 들어가도 제목을 뺀다
    for (const bl of barLabels) {
      let limit = bl.right;
      if (bl.atk) {
        const ax = bl.atk.getBBox().x - 6;
        if (ax - bl.t.getBBox().x < 40) { bl.t.remove(); continue; }
        limit = Math.min(limit, ax);
      }
      if (!fitText(bl.t, bl.t.textContent, limit)) bl.t.remove();
    }
    const sync = () => { const sl = host.scrollLeft; clipRect.setAttribute("x", LABEL_W + sl); for (const lg of stuck) lg.setAttribute("transform", `translate(${sl},0)`); };
    host.onscroll = sync; sync();
    // 확인 필요 수 주황 배지(답을 넣을 것이 있으면 툴팁에 적는다)
    for (const c of counts) {
      const bb = c.lab.getBBox(), cy = bb.y + bb.height / 2;
      let x0 = bb.x + bb.width + 6;
      for (const [n, cls, label, tail] of [[c.n, "cue-count", T("확인 필요"), c.hold ? T(". 답을 넣을 것 {n}건 포함", { n: c.hold }) : ""]]) {
        if (!n) continue;
        const w = 18 + (String(n).length - 1) * 7, cg = svgEl("g", { class: cls });
        cg.appendChild(svgEl("rect", { x: x0, y: cy - 8, width: w, height: 16, rx: 8 }));
        const t = svgEl("text", { x: x0 + w / 2, y: cy + 4, "text-anchor": "middle" }); t.textContent = `${n}`; cg.appendChild(t);
        cg.appendChild(svgEl("title", {})).textContent = T("{label} {n}건{tail}", { label, n, tail });
        c.g.appendChild(cg); x0 += w + 4;
      }
    }
    return all;
  }

  // SVG 글의 오른쪽 끝이 limit(SVG 좌표)을 넘으면 실제 글 폭을 재며 줄이고 끝에 줄임표를 붙인다. 한 글자도 안 들어가면 비우고 false다
  function fitText(node, full, limit) {
    node.textContent = full;
    const right = () => { const b = node.getBBox(); return b.x + b.width; };
    if (right() <= limit) return true;
    let lo = 0, hi = full.length - 1; // lo: 줄임표를 붙여도 들어가는 가장 긴 앞부분 길이
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      node.textContent = `${full.slice(0, mid).trimEnd()}…`;
      if (right() <= limit) lo = mid; else hi = mid - 1;
    }
    node.textContent = lo ? `${full.slice(0, lo).trimEnd()}…` : "";
    return lo > 0;
  }

  // ----- 툴팁 -----
  const tipEl = $("tip");
  function tip(target, rows) {
    const show = (ev) => {
      tipEl.textContent = "";
      for (const [k, v] of rows()) {
        const line = el("div"); const b = el("b", null, k); line.appendChild(b);
        if (v) { line.appendChild(document.createTextNode("  ")); line.appendChild(el("span", "l", v)); }
        tipEl.appendChild(line);
      }
      tipEl.hidden = false; move(ev);
    };
    const move = (ev) => {
      const px = ev.clientX ?? (target.getBoundingClientRect().left + 10), py = ev.clientY ?? target.getBoundingClientRect().top;
      tipEl.style.left = Math.min(px + 14, window.innerWidth - 330) + "px"; tipEl.style.top = Math.max(8, py - 10 - tipEl.offsetHeight) + "px";
    };
    target.addEventListener("pointerenter", show); target.addEventListener("pointermove", move);
    target.addEventListener("pointerleave", () => (tipEl.hidden = true));
    target.addEventListener("focus", show); target.addEventListener("blur", () => (tipEl.hidden = true));
  }

  // 세션 서브에이전트가 활동 없이 멈춘 분. 스케줄러가 15분부터 적고 띄운 세션에 알린다
  function stallText(m) { return m.status === "진행 중" && m.run.stall_min > 0 ? T("  멈춤 {n}분", { n: m.run.stall_min }) : ""; }
  function flatTools(m) {
    const out = [];
    for (const seg of m.segments) for (const t of seg.tools) out.push(t);
    for (const st of m.stages) for (const t of st.tools || []) out.push(t);
    out.sort((a, b) => a.ts - b.ts);
    return out;
  }
  // ----- 상단 -----
  $("slackSw").addEventListener("click", async () => {
    const want = $("slackSw").getAttribute("aria-pressed") !== "true";
    try {
      const r = await fetch("/api/slack", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: want }) });
      const j = await r.json();
      if (state.data) state.data.slack_on = j.slack_on;
      $("slackSw").className = "slacksw " + (j.slack_on ? "on" : "off"); $("slackSw").setAttribute("aria-pressed", String(j.slack_on));
      $("slackTxt").textContent = j.slack_on ? T("Slack 켜짐") : T("Slack 꺼짐");
    } catch (e) { /* 다음 갱신에서 서버 값으로 맞춘다 */ }
  });
  // 상태창(261023-jipsa-38, 37 결과지 답): 탭보다 앞에 늘 보이는 지금 현황. 확인 필요, 진행 중(무엇을 하는지), 멈춤, 실패만 둔다. 사용 창은 머리 줄 한 줄 현황이다(261023-jipsa-41).
  // 누적이나 오늘 완료 같은 숫자는 두지 않는다. 멈춤과 실패는 있을 때만 보인다
  function drawStatusBar(box, data, cue, vnow) {
    const item = (cls, n, label, onClick) => {
      const s = el(onClick ? "button" : "span", `sb ${cls}${n ? "" : " zero"}`); if (onClick) { s.type = "button"; s.addEventListener("click", onClick); }
      s.appendChild(el("i", "sh-i")); s.appendChild(el("b", null, String(n))); s.appendChild(el("span", null, label)); box.appendChild(s); return s;
    };
    const live = data.live || [], stalled = live.filter((r) => r.stall_min > 0), fails = cue.filter((x) => x.kind === "실패").length;
    item("cue", cue.length, T("확인 필요"), goCue);
    const run = item("run", live.length, T("진행 중"), () => setTab("timeline"));
    run.title = live.map((r) => T("{p} {t}, {ago} 시작", { p: pname(r.project), t: r.title, ago: ago(r.started) })).join("\n");
    if (live.length) { // 무엇을 하는지 한 줄. 누르면 결과지가 열린다
      const r = live.find((x) => !x.stall_min) || live[0];
      const w = el("button", "sb-now", `${pname(r.project)} ${r.title}`); w.type = "button"; w.title = run.title;
      w.addEventListener("click", () => openResult(r.run_id)); box.appendChild(w);
      if (live.length > 1) box.appendChild(el("span", "sb-more muted", T("외 {n}", { n: live.length - 1 })));
    }
    if (stalled.length) { const s = item("stop", stalled.length, T("멈춤"), () => openResult(stalled[0].run_id)); s.title = stalled.map((r) => T("{p} {t}, {n}분 무활동", { p: pname(r.project), t: r.title, n: r.stall_min })).join("\n"); }
    if (fails) item("fail", fails, T("실패"), goCue);
  }
  // 확인 필요 탭은 없앴다(261029-jipsa-43 1안). 확인 필요 숫자를 누르면 현황판의 확인 필요 띠로 간다
  const goCue = () => { setTab("board"); setTimeout(() => { const w = $("attnWrap"); if (w && !w.hidden) w.scrollIntoView({ block: "start" }); }, 50); };
  // 머리 줄 한 줄 현황(261023-jipsa-41): 환경 탭 대신 장식 띠 자리에 둔다. ccstatusline처럼 구분자로 나눈 짧은 글자이고 막대가 없다.
  // 사용률은 쓴 %이고 앞이 5시간, 뒤가 주간이다. 값마다 색 구간을 따로 입힌다. 색은 표시일 뿐 새 시작을 막지 않는다.
  // 오래된 측정은 회색 값 뒤에 ?, 없는 값은 --다. 스케줄러와 Slack 웹훅은 이상할 때만 맨 앞에 빨강 글자로 나온다. 풀이와 초기화 시각은 툴팁이다
  const band = (v) => (v >= 90 ? "crit" : v >= 70 ? "warn" : "ok");
  function drawHeadLine(data, vnow) {
    const box = $("headLine"); box.textContent = "";
    const h = data.head; if (state.view !== "live" || !h) return;
    const span = (iso, sign) => { // 기준 시각에서 앞뒤로 얼마인지
      const t = parse(iso); if (!t || isNaN(t)) return "";
      const m = Math.max(0, Math.round(sign * (t - vnow) / 60000)), d = Math.floor(m / 1440), hr = Math.floor((m % 1440) / 60);
      return d ? T("{d}일 {h}시간", { d, h: hr }) : hr ? T("{h}시간 {n}분", { h: hr, n: m % 60 }) : T("{n}분", { n: m % 60 });
    };
    let n = 0;
    const group = (cls, label, title) => {
      if (n++) box.appendChild(el("span", "hl-sep", "|"));
      const g = el("span", `hl-g ${cls}`); if (label) g.appendChild(el("span", "hl-n", label)); g.title = title; box.appendChild(g); return g;
    };
    for (const a of h.alerts || []) group("alert", null, a.title).appendChild(el("b", "hl-v crit", a.text));
    const usage = (name, u, note) => {
      if (!u) return;
      const cut = (v, c, reset) => (v == null ? null : c || (reset && parse(reset) <= vnow) ? 0 : Math.round(v)); // 초기화 시각이 지난 창은 0%
      const five = cut(u.five, u.cleared, u.five_reset), week = cut(u.week, u.week_cleared, u.week_reset);
      const stale = !u.fresh && (five != null || week != null);
      const line = (k, v, reset) => `${k} ${v == null ? T("측정 없음") : `${v}%`}${v != null && reset && parse(reset) > vnow ? T(", {t} 뒤 초기화", { t: span(reset, 1) }) : v === 0 && reset ? T(", 초기화됨") : ""}`;
      const g = group(name.toLowerCase(), name, [line(T("5시간"), five, u.five_reset), line(T("주간"), week, u.week_reset), ...(stale && u.seen ? [T("측정 {t} 전, 오래된 값", { t: span(u.seen, -1) })] : []), ...note].join("\n"));
      const val = (v) => g.appendChild(el("b", `hl-v ${v == null ? "none" : stale ? "stale" : band(v)}`, v == null ? "--" : `${v}%`));
      val(five); g.appendChild(el("span", "hl-sl", "/")); val(week);
      if (stale) g.appendChild(el("span", "hl-q", "?"));
    };
    usage("Claude", h.claude, []);
    const cx = h.codex || {};
    if (!cx.hidden) usage("Codex", h.codex, [...(!cx.measured && cx.cap ? [T("실측 없음, 호출 수 어림 {a}/{b}회", { a: cx.calls, b: cx.cap })] : []), ...(cx.handover ? [T("Claude가 이어받는 중")] : [])]);
    const res = (name, used, total, title) => {
      const ok = used != null && total;
      const g = group(name.toLowerCase(), name, ok ? T("{title} {used}/{total}GB, {pct}% 사용", { title, used, total, pct: Math.round((used / total) * 100) }) : T("{title} 측정 불가", { title }));
      const gb = (v) => (v < 10 ? (+v).toFixed(1) : String(Math.round(v)));
      g.appendChild(el("b", `hl-v ${ok ? band((used / total) * 100) : "none"}`, ok ? `${gb(used)}/${Math.round(total)}G` : "--"));
    };
    // GPU 막대(261029-jipsa-17 다안 3차): 머리 줄은 지금 쓰는 양(nvidia-smi 실측)만 보인다. 막대 칸 하나가 실측/전체이고 글자도 같은 값이다.
    // 작업별 실측은 TODO 탭 자원 상자에도 둔다. 툴팁에 작업별 실측과 실측 초과 멈춤만 적는다
    const L = h.ledger || {};
    if (h.gpu && h.gpu.ok && h.gpu.total) {
      const used = +h.gpu.used || 0, total = +h.gpu.total, pct = (used / total) * 100;
      const tips = [T("GPU 메모리 실측 {used}/{total}GB, {pct}% 사용(nvidia-smi)", { used, total, pct: Math.round(pct) }),
        ...(L.rows || []).filter((r) => r.measured != null).map((r) => T("{p} {k} 실측 {gb}GB", { p: pname(r.project), k: r.kind, gb: r.measured })),
        ...(L.over ? [T("실측이 예약보다 커 새 GPU 작업을 {t}까지 멈춤({p})", { t: hhmm(parse(L.over.until)), p: pname(L.over.project) })] : [])];
      const g = group("gpu", "GPU", tips.join("\n"));
      const bar = el("span", "gbar"), fill = el("i", `gseg use ${L.over ? "crit" : band(pct)}`);
      fill.style.width = `${Math.min(100, pct).toFixed(1)}%`; bar.appendChild(fill); g.appendChild(bar);
      const gbt = (v) => (v < 10 ? (+v).toFixed(1) : String(Math.round(v)));
      g.appendChild(el("b", `hl-v ${L.over ? "crit" : band(pct)}`, `${gbt(used)}/${Math.round(total)}G`));
    } else res("GPU", h.gpu && h.gpu.ok ? h.gpu.used : null, h.gpu && h.gpu.ok ? h.gpu.total : null, T("GPU 메모리"));
    res("RAM", h.ram && h.ram.used, h.ram && h.ram.total, "RAM");
    // Ollama는 모델을 올렸을 때만 보인다. GPU 값이 왜 큰지 읽히게 한다. 서버만 켜져 있고 적재가 없으면 숨긴다
    if ((h.ollama || []).length) group("ollama", "Ollama", T("Ollama 켜짐, 적재 모델 {m}", { m: h.ollama.join(", ") })).appendChild(el("b", "hl-v", h.ollama.join(", ")));
  }
  const goQueue = () => { setTab("todo"); setTimeout(() => { const r = $("tfRes"); if (r) r.scrollIntoView({ block: "start" }); }, 50); };
  async function gpuAct(key, action, title) {
    if (action === "cancel" && !window.confirm(T("취소: {t} 요청을 거둔다", { t: title }))) return;
    try {
      await fetch("/api/gpuqueue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, action }) });
    } catch (e) { /* 다음 갱신에서 서버 값으로 맞춘다 */ }
    pollLive();
  }
  // 동시 Cycle 칸(261029-jipsa-17). 옛 Manual, Auto 표시 자리다. 상한이 0이면 빨강, 지난 기록 보기는 회색이다
  function paintCap(cap, past) {
    const cls = past ? " past" : cap && cap.cap === 0 ? " stop" : " manual";
    $("modeDot").className = "dot" + cls;
    $("modePill").className = "modepill" + cls;
  }
  function drawTop(data, vnow) {
    drawHeadLine(data, vnow);
    // 동시 Cycle n/상한(261029-jipsa-17). GPU와 RAM 대기 수를 옆에 두고, 누르면 TODO 탭의 자원 상자로 간다
    const cap = data.cap || null, live = state.view === "live";
    $("mode").textContent = live ? (cap ? T("동시 Cycle {n}/{cap}", { n: cap.n, cap: cap.cap }) : T("동시 Cycle")) : (data.demo ? T("데모") : T("지난 기록 {d}", { d: data.date }));
    $("modePill").title = live && cap ? [T("Cycle {n}개, 상한 {cap}개", { n: cap.n, cap: cap.cap }), cap.stop || "", T("누르면 TODO 탭의 자원으로 간다")].filter(Boolean).join("\n") : "";
    paintCap(cap, !live);
    // GPU 대기 n(261029-jipsa-17). GPU나 RAM이 모자라 대기열에 선 줄 수다. 누르면 TODO 탭의 자원 상자로 간다
    // 대기가 0이면 머리 줄에서 숨기고 설정 메뉴에만 둔다(42 초안 우선순위 9)
    const gq = $("gqPill"), nq = live && cap ? cap.queue || 0 : 0;
    gq.hidden = !live || !nq; gq.querySelector("b").textContent = String(nq); gq.classList.toggle("on", nq > 0);
    $("gqMenu").textContent = T("{n}줄", { n: nq }); $("modeMenu").textContent = $("mode").textContent.replace(/^동시 Cycle\s*/, "").replace(/^Concurrent Cycles\s*/, "") || "-";
    if (state.view === "live" && typeof data.slack_on === "boolean") { // 설정 메뉴 안의 스위치. 이름과 상태를 같이 적는다(우선순위 17)
      const b = $("slackSw"); b.disabled = false; b.className = "slacksw " + (data.slack_on ? "on" : "off"); b.setAttribute("aria-pressed", String(data.slack_on));
      $("slackTxt").textContent = data.slack_on ? T("켜짐") : T("꺼짐");
    }
    $("cutoffNote").textContent = "";
    const counts = $("counts"); counts.textContent = "";
    // 머리 숫자는 확인 필요 큐에서 센다. 확인 필요 탭 배지, 현황판 카드와 같은 목록이다. 누적 완료 대신 오늘 완료를 작게 둔다(261023-jipsa-37 3안).
    // 지난 기록이면 그날 실행의 상태 값으로 센다
    const cue = liveCue();
    if (state.view !== "live") { // 지난 기록이면 그날 실행의 상태 값으로 센다
      for (const [k, s, cls] of [["확인 필요", "확인 필요", "hold"], ["진행 중", "진행 중", "run"], ["실패", "실패", "fail"], ["완료", "완료", "done small"]]) {
        const v = (data.runs || []).filter((r) => r.status === s).length;
        const c = el("span", `chip ${cls}${v ? "" : " zero"}`); c.appendChild(el("b", null, String(v))); c.appendChild(el("span", null, stName(k))); counts.appendChild(c);
      }
    } else drawStatusBar(counts, data, cue, vnow);
    const td = $("tabTodoN"); td.hidden = state.view !== "live" || !data.todo_file_n; td.textContent = String(data.todo_file_n ?? ""); // 할 일 파일 줄 수. 0이면 뱃지를 두지 않는다(우선순위 10)
  }
  // 설정 ⋯ 메뉴(42 초안 구역 20): 새로고침 주기, Slack 알림, GPU 대기. 폰에서는 동시 Cycle과 오늘 보고도 든다. 바깥을 누르거나 Esc로 닫힌다
  const setMenu = (open) => { $("menu").hidden = !open; $("menuBtn").setAttribute("aria-expanded", String(open)); };
  $("menuBtn").addEventListener("click", (ev) => { ev.stopPropagation(); setMenu($("menu").hidden); });
  document.addEventListener("click", (ev) => { if (!$("menu").hidden && !$("menu").contains(ev.target)) setMenu(false); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("menu").hidden) setMenu(false); });
  $("gqMenu").addEventListener("click", () => { setMenu(false); goQueue(); });

  // POST 도우미. TODO 탭의 명령 요청이 쓴다. 타임라인 목표 줄의 멈춤 단추(옛 /api/goal_stop)는 261025-jipsa-42에서 뗐다. 목표를 내리려면 jipsa auto rm이나 할 일로 내리기를 쓴다
  const postJson = async (url, body) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return r.ok ? r.json() : { ok: false, error: await r.text() };
  };

  // ----- 목표 줄: 목표 cycle마다 한 줄. 목표, Cycle 수, 처음과 최고 기록, Cycle별 지표 추이 선, 지금 주체, 지금 위치(261023-jipsa-11, 33) -----
  // 끝난 목표 접힘 줄을 펼쳤는지. 기본은 접힘이고 이 창에 기억한다(261024-jipsa-03)
  const GOALS_DONE_KEY = "jipsa.tl.goalsDoneOpen";
  const goalsDoneOpen = () => { try { return localStorage.getItem(GOALS_DONE_KEY) === "1"; } catch { return false; } };
  const toggleGoalsDone = () => { try { localStorage.setItem(GOALS_DONE_KEY, goalsDoneOpen() ? "0" : "1"); } catch { /* 저장이 막혀도 화면은 돈다 */ } render(); };
  function drawGoals(list) {
    const host = $("goals"); host.textContent = "";
    // 끝난 목표는 도는 목표 아래에 끝난 모양(흐린 줄, 끝 사유와 종합 보고 상태)으로 둔다. 막대 그림의 보기 범위 안에 실행이 있거나
    // 종합 보고가 확인 필요인 것만 펼치고, 나머지는 맨 아래 "끝난 목표 N개" 한 줄로 접는다(261024-jipsa-03 1안)
    const cyc = list.filter((c) => c.status !== "거절").sort((a, b) => (a.status === "끝") - (b.status === "끝"));
    host.hidden = !cyc.length; if (!cyc.length) return;
    const near = (c) => c.status !== "끝" || tlCycles.has(c.key) || (c.final && c.final.shown === "확인 필요");
    const shown = cyc.filter(near), hid = cyc.filter((c) => !near(c)), open = goalsDoneOpen();
    const f = (v) => (v == null ? "-" : `${+Number(v).toFixed(2)}`);
    const rows = shown.concat(hid.length && open ? hid : []);
    let divided = 0;
    for (const c of rows) {
      const ended = c.status === "끝", paused = c.state_text === "창 멈춤";
      if (ended && !divided && rows.some((x) => x.status !== "끝")) { host.appendChild(el("div", "goal-sep", T("끝난 목표"))); divided = 1; } // 진행 중 줄과 펼친 끝난 줄 사이 구분선(261024-jipsa-21)
      const row = el("div", `goal-row${ended ? " ended" : paused ? " paused" : ""}`);
      const nm = el("div", "g-name");
      if (ended) nm.appendChild(el("em", "g-end", T("끝: {r}", { r: c.end_reason || T("끝") }))); // 끝난 줄은 이름 칸 맨 앞에 끝 사유 표지
      nm.appendChild(el("span", null, pname(c.project))); nm.appendChild(el("b", null, c.title));
      nm.tabIndex = 0; tip(nm, () => [[c.title, ""], [T("프로젝트"), pname(c.project)]]); row.appendChild(nm); // 제목은 한 줄로 줄이고 전체는 툴팁으로 본다
      row.appendChild(el("div", "g-n", `Cycle ${c.rounds.length}`));
      const rec = el("div", "g-rec"); rec.appendChild(document.createTextNode(T("처음 {a} 최고 ", { a: f(c.first) }))); rec.appendChild(el("b", null, f(c.best)));
      if (c.target != null) rec.appendChild(document.createTextNode(T(" / 목표 {t} {d}", { t: f(c.target), d: T(c.direction || "이상") })));
      row.appendChild(rec);
      row.appendChild(goalSpark(c));
      const who = el("div", "g-who", T("주체 {o}", { o: c.owner_text || T("작업자") }));
      if ((c.moves || []).length) { who.textContent += T(" (이동 {n})", { n: c.moves.length }); who.title = c.moves.join("\n"); }
      row.appendChild(who);
      const gs = el("div", `g-state ${ended ? "ended" : paused ? "paused" : "live"}${c.final && c.final.shown === "확인 필요" ? " cue" : ""}`, c.where || c.state_text || c.phase);
      gs.title = c.state_text || ""; if (c.final) { gs.style.cursor = "pointer"; gs.addEventListener("click", () => openResult(c.final.run_id)); }
      row.appendChild(gs);
      host.appendChild(row);
    }
    if (!hid.length) return;
    const fold = el("button", "goal-fold", `${open ? "▾" : "▸"} ${T("끝난 목표 {n}개 (보기 범위 밖)", { n: hid.length })} ${open ? T("접기") : T("펼치기")}`);
    fold.type = "button"; fold.setAttribute("aria-expanded", String(open)); fold.addEventListener("click", toggleGoalsDone);
    host.insertBefore(fold, open ? host.children[shown.length + divided] : null); // 펼치면 접힘 줄 아래에 끝난 목표가 온다
  }
  function goalSpark(c) {
    const W = 130, H = 30, P = 4;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "goal-spark", role: "img", "aria-label": T("Cycle별 지표 추이") });
    const sp = scorePts(c); // 시작값과 Cycle별 다시 잰 값(6안과 같은 자료)
    const pts = (sp.start != null ? [{ n: 0, s: sp.start, adopt: true }] : []).concat(sp.pts);
    const vals = pts.map((p) => p.s).concat(c.target != null ? [c.target] : []);
    if (!pts.length) { const t = svgEl("text", { x: 2, y: H / 2 + 4, class: "lb" }); t.textContent = T("지표 없음"); svg.appendChild(t); return svg; }
    const lo = Math.min(...vals), hi = Math.max(...vals), maxN = Math.max(1, ...pts.map((p) => p.n)), minN = Math.min(...pts.map((p) => p.n));
    const x = (n) => P + ((W - 2 * P) * (n - minN)) / Math.max(1, maxN - minN), y = (v) => H - P - ((H - 2 * P) * (v - lo)) / Math.max(1e-9, hi - lo);
    if (c.target != null) svg.appendChild(svgEl("line", { x1: P, x2: W - P, y1: y(c.target), y2: y(c.target), class: "tg" }));
    svg.appendChild(svgEl("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${x(p.n)},${y(p.s)}`).join(" "), class: "ln" }));
    for (const p of pts) svg.appendChild(svgEl("circle", { cx: x(p.n), cy: y(p.s), r: 2.6, class: `pt${p.adopt ? " adopt" : ""}` }));
    svg.appendChild(svgEl("title", {})).textContent = pts.map((p) => `${p.n ? `Cycle ${p.n}` : T("시작")} ${p.s}${p.adopt ? T(" 채택") : ""}`).join(", ");
    return svg;
  }

  // 점수 추이 자료(261023-jipsa-38 6안). 시작값은 기준선(base), 없으면 처음 잰 값(first)이다. Cycle마다 다시 잰 값(score, 없으면 채택 기준값 + 차),
  // 95% 구간(low, high), 채택 여부, 목표 판정(O, X)을 둔다. 전에는 Cycle 1의 차가 비면 반복이 멈춰 시작점 하나만 그렸다
  function scorePts(c) {
    const start = c.base ?? c.first ?? null;
    const pts = []; let cur = start;
    for (const r of c.rounds || []) {
      const s = r.score ?? (r.delta != null && cur != null ? +(cur + r.delta).toFixed(2) : null);
      if (s == null) continue;
      pts.push({ n: r.n, s, low: r.low ?? null, high: r.high ?? null, adopt: !!r.adopt, judge: r.judge || "" });
      if (r.adopt) cur = s;
    }
    return { start, pts };
  }

  // ----- TODO: 위 띠(자원과 대기열, 도는 Cycle)와 할 일과 메모(261025-jipsa-29, 33, 36, 46, 261029-jipsa-17 다안 3차) -----
  // 줄 글과 차례는 서버가 jipsa todo와 같은 함수로 만든 그대로다. 서버가 번호 줄을 칸으로 나눠 주고 화면은 격자 줄로 그린다.
  // 칸 글은 명령 줄을 자른 그대로라 " | "로 이으면 명령 줄과 같다. 기준 칸 앞 "기준" 글자는 CSS가 붙이는 표시라 줄 글에 들지 않는다.
  // 단추는 /api/command 하나로 같은 명령을 돌린다. 번호 대신 줄 key(프로젝트::문장, 메모는 글)를 보내고 서버가 그때의 번호로 바꾼다.
  // Auto 칸은 뗐다(261029-jipsa-17). 할 일 줄은 Do, 예약, Rm이다(261029-jipsa-20). Do는 바로 시킨다. Cycle 줄의 Do는 마감 칸(기본 07:00)을 펼친다.
  // 예약은 줄 아래에 시각 칸(Cycle은 마감 칸도)을 펼치고, 시키면 줄이 위 띠의 예약으로 옮겨 가 그 시각에 스케줄러가 시작한다
  const TF_BTNS = {
    "할 일": [["Do", "todo run", "이 줄을 바로 시킨다. Cycle은 마감을 받는다"], ["예약", "todo run", "시각을 정해 그때 시킨다"], ["Rm", "todo rm", "할 일 파일에서 지운다"]],
  };
  const TF_META = ["criteria", "limits"]; // cycle 칸은 번호 왼쪽 C의 툴팁으로 보인다
  let tfBusy = false, memoSig = "", memoUp = null; // memoUp: 열린 할 일로 줄 {key, project, text}
  let tfTodoSig = "", tfBandSig = "";
  const tfFbDraft = {}; // Cycle 줄마다 적던 피드백. 띠를 다시 그려도 글이 남는다
  let tfBandPress = false; // 위 띠에서 누르는 중(pointerdown부터 click까지)
  document.addEventListener("pointerdown", (ev) => { const band = $("tfBand"); tfBandPress = !!(band && band.contains(ev.target)); }, true);
  document.addEventListener("pointerup", () => { setTimeout(() => { tfBandPress = false; }, 0); }, true);
  let tfFilt = "all"; // 할 일 칸 고르기: all, cycle
  let tfDo = null; // 펼친 Do나 예약 칸 {key, rsv, start, until}. rsv가 참이면 예약이다
  let tfCyc = null; // 펼친 Cycle 값 칸 {key, metric, target, dir, cap, stop}
  function tfButton(label, title, onClick, danger) {
    const b = el("button", `tf-btn${danger ? " danger" : ""}`, label); b.type = "button"; b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }
  // 줄 끝 ⋯ 메뉴(42 초안 구역 13, 우선순위 18): 덜 쓰는 단추(지우기, Cycle 고치기, 피드백)를 묶는다. 하나만 열리고 바깥을 누르면 닫힌다
  let tfMenuOpen = null; // 열린 메뉴의 줄 key
  function tfMore(key, items) {
    const b = tfButton("⋯", T("지우기, Cycle 고치기, 피드백"), (ev) => { ev.stopPropagation(); const open = tfMenuOpen === key; closeTfMenu(); if (!open) openTfMenu(b, key, items); });
    b.classList.add("more"); b.setAttribute("aria-haspopup", "true"); b.setAttribute("aria-expanded", "false");
    if (tfMenuOpen === key) setTimeout(() => openTfMenu(b, key, items), 0); // 다시 그려도 열린 메뉴는 유지한다
    return b;
  }
  function openTfMenu(btn, key, items) {
    const m = el("div", "tf-menu"); m.setAttribute("role", "menu");
    for (const it of items) m.appendChild(it);
    btn.setAttribute("aria-expanded", "true"); btn.parentNode.appendChild(m); tfMenuOpen = key;
  }
  function closeTfMenu() { for (const m of document.querySelectorAll(".tf-menu")) { const b = m.parentNode.querySelector(".tf-btn.more"); if (b) b.setAttribute("aria-expanded", "false"); m.remove(); } tfMenuOpen = null; }
  document.addEventListener("click", (ev) => { if (tfMenuOpen && !ev.target.closest(".tf-menu")) closeTfMenu(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && tfMenuOpen) closeTfMenu(); });
  function tfBtns(r) {
    const bs = el("div", "btns"), more = [];
    for (const [label, name, what] of TF_BTNS[r.item.section] || []) {
      const b = tfButton(T(label), `${T(what)} (jipsa ${name} ${r.item.no})`, () => {
        closeTfMenu();
        if (name === "todo rm" && !window.confirm(T("할 일 파일에서 이 줄을 지운다.\n\n{t}", { t: r.text.trim() }))) return;
        const rsv = label === "예약";
        if (name === "todo run" && (rsv || (r.cells && r.cells.cycle))) { // 예약과 Cycle Do는 줄 아래 칸을 펼치고 닫는다
          const same = tfDo && tfDo.key === r.item.key && tfDo.rsv === rsv;
          tfDo = same ? null : { key: r.item.key, rsv, start: rsv ? "" : "지금", until: "07:00" };
          tfCyc = null;
          tfTodoSig = ""; drawTodoFile(state.data && state.data.todofile); return;
        }
        if (name === "todo run" && !window.confirm(T("이 줄 하나를 지금 작업자로 돌린다. 시키면 할 일에서 빠지고 현황판에 보인다.\n\n{t}", { t: r.text.trim() }))) return;
        tfRun({ name, key: r.item.key }, "tfTodoSec");
      }, name === "todo rm");
      if (name === "todo run") {
        b.classList.add(label === "예약" ? "rsv" : "do");
        if (tfDo && tfDo.key === r.item.key && tfDo.rsv === (label === "예약")) b.classList.add("on");
        bs.appendChild(b);
      } else { b.textContent = T("지우기"); more.push(b); } // Rm은 ⋯ 메뉴 안이다
    }
    if (r.cells) more.push(tfCycEditBtn(r));
    if (r.cells && r.cells.cycle) more.push(tfFbBtn(r)); // 사람 피드백(261026-jipsa-19). 입력 줄 없이 프롬프트 창 하나
    if (r.cells) more.push(tfCycBtn(r));
    if (more.length) bs.appendChild(tfMore(r.item.key, more));
    return bs;
  }
  // Do와 예약 칸. Cycle Do는 마감만, 예약은 시각(HH:MM이나 +30m)과 Cycle이면 마감(HH:MM이나 +4h)을 받는다
  function tfDoForm(r) {
    const f = el("form", "tf-do"), cyc = !!(r.cells && r.cells.cycle); f.autocomplete = "off";
    const inp = (k, label, ph) => {
      const i = el("input", null); i.type = "text"; i.value = tfDo[k]; i.placeholder = ph; i.setAttribute("aria-label", label);
      i.addEventListener("input", () => { tfDo[k] = i.value; });
      f.appendChild(el("span", "k", label)); f.appendChild(i); return i;
    };
    const first = tfDo.rsv ? inp("start", T("시각"), "22:00, +30m") : null;
    if (cyc) inp("until", T("마감"), "07:00, +4h");
    const ok = el("button", "tf-btn do", tfDo.rsv ? T("예약하기") : T("시키기")); ok.type = "submit";
    ok.title = `jipsa todo run ${r.item.no}${tfDo.rsv ? T(" 시작 <시각>") : ""}${cyc ? T(" 마감 <시각>") : ""}`;
    f.appendChild(ok);
    f.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const start = tfDo.rsv ? tfDo.start.trim() : "";
      if (tfDo.rsv && !start) { if (first) first.focus(); return; }
      tfRun({ name: "todo run", key: r.item.key, start, until: cyc ? tfDo.until.trim() : "" }, "tfTodoSec");
    });
    if (first) setTimeout(() => first.focus(), 0);
    return f;
  }
  // Cycle 단추(261026-jipsa-16). 누르면 입력 줄 없이 바로 목표 미정 Cycle로 켜고(jipsa todo cycle N과 같다), 켜진 줄에서 다시 누르면 끈다(jipsa todo cycle N off).
  // 켜진 줄은 번호 왼쪽에 C가 보이고, 지표와 목표값은 C에 올린 툴팁에 있다. 값을 넣거나 고치는 것은 명령(/todo cycle)이 한다
  function tfCycParse(t) { // cycle 칸 글을 입력 줄 값으로. 'cycle 미정', 'cycle 지표 미정 50 이상', 'cycle 점수 목표 미정'도 읽는다
    const m = /^cycle (.+?)(?: (이상|이하))?(?: 상한 (\d+))?(?: 도달하면 끝)?$/.exec(t || "");
    if (!m) return null;
    let metric = "", target = "";
    if (m[1] !== "미정") {
      const h = /^(.*?) ?(목표 미정|-?\d+(?:\.\d+)?\S*)$/.exec(m[1]);
      if (h) { metric = h[1] === "지표 미정" ? "" : h[1]; target = h[2] === "목표 미정" ? "" : h[2]; } else metric = m[1];
    }
    return { metric, target, dir: m[2] || "", cap: m[3] || "", pending: !metric || !target };
  }
  function tfCycBtn(r) {
    const no = r.item.no, v = r.cells.cycle, on = !!v;
    const b = tfButton("Cycle", on ? T("Cycle 켜짐: {v}. 눌러 끈다 (jipsa todo cycle {no} off)", { v, no }) : T("눌러 Cycle을 켠다. 지표와 목표값은 첫 분석이 정한다 (jipsa todo cycle {no})", { no }), () => {
      if (on && !(tfCycParse(v) || {}).pending && !window.confirm(T("Cycle을 끈다. 적힌 지표와 목표값이 지워진다.\n\n{v}", { v }))) return;
      tfRun(on ? { name: "todo cycle", key: r.item.key, off: true } : { name: "todo cycle", key: r.item.key, metric: "", target: "", dir: "", cap: "" }, "tfTodoSec");
    });
    if (on) { b.classList.add("on"); b.setAttribute("aria-pressed", "true"); } else b.setAttribute("aria-pressed", "false");
    return b;
  }
  // Cycle 값 고치기(261103-jipsa-07). 지표, 목표값, 방향, 상한, 끝 조건을 줄 아래 칸에서 고친다. 비운 칸은 첫 분석이 정한다. 도는 줄은 서버가 거절한다
  function tfCycEditBtn(r) {
    const v = r.cells.cycle;
    return tfButton(v ? T("Cycle 값 고치기") : T("Cycle 값 넣기"), T("지표, 목표값, 상한을 고친다 (jipsa todo cycle {no} <지표> <목표값> 상한 N)", { no: r.item.no }), () => {
      closeTfMenu();
      const p = tfCycParse(v) || {}, same = tfCyc && tfCyc.key === r.item.key;
      tfCyc = same ? null : { key: r.item.key, metric: p.metric || "", target: p.target || "", dir: p.dir || "", cap: p.cap || "", stop: /도달하면 끝$/.test(v || "") };
      tfDo = null; tfTodoSig = ""; drawTodoFile(state.data && state.data.todofile);
    });
  }
  function tfCycForm(r) {
    const f = el("form", "tf-do tf-cyc"); f.autocomplete = "off";
    const inp = (k, label, ph) => {
      const i = el("input", null); i.type = "text"; i.value = tfCyc[k]; i.placeholder = ph; i.setAttribute("aria-label", label);
      i.addEventListener("input", () => { tfCyc[k] = i.value; });
      f.appendChild(el("span", "k", label)); f.appendChild(i); return i;
    };
    const first = inp("metric", T("지표"), T("첫 화면 ms"));
    inp("target", T("목표값"), "800");
    const d = el("select", null); d.setAttribute("aria-label", T("방향"));
    for (const [v, t] of [["", "방향 자동"], ["이상", "이상"], ["이하", "이하"]]) { const o = el("option", null, T(t)); o.value = v; d.appendChild(o); }
    d.value = tfCyc.dir; d.addEventListener("change", () => { tfCyc.dir = d.value; }); f.appendChild(d);
    inp("cap", T("상한"), "4");
    const lb = el("label", "k"), c = el("input", null); c.type = "checkbox"; c.checked = tfCyc.stop;
    c.addEventListener("change", () => { tfCyc.stop = c.checked; }); lb.append(c, T(" 도달하면 끝")); f.appendChild(lb);
    const ok = el("button", "tf-btn do", T("저장")); ok.type = "submit"; f.appendChild(ok);
    f.appendChild(tfButton(T("취소"), T("고치기 칸을 닫는다"), () => { tfCyc = null; tfTodoSig = ""; drawTodoFile(state.data && state.data.todofile); }));
    f.addEventListener("submit", (ev) => {
      ev.preventDefault();
      tfRun({ name: "todo cycle", key: r.item.key, metric: tfCyc.metric.trim(), target: tfCyc.target.trim(), dir: tfCyc.dir, cap: tfCyc.cap.trim(), stop: tfCyc.stop }, "tfTodoSec");
    });
    setTimeout(() => first.focus(), 0);
    return f;
  }
  function tfFbBtn(r) {
    return tfButton(T("피드백"), T("Cycle의 돌고 있는 단계와 다음 분석, 명령에 사람 피드백을 넣는다. 지표와 목표값은 바뀌지 않는다 (jipsa todo feedback {no} | 글)", { no: r.item.no }), () => {
      const t = window.prompt(T("이 Cycle의 다음 분석과 명령에 넣을 피드백을 적는다. 돌고 있는 단계에도 다음 구간부터 닿는다. 지표와 목표값은 바뀌지 않는다.\n\n{t}", { t: r.text.trim() }));
      if (t && t.trim()) tfRun({ name: "todo feedback", key: r.item.key, text: t.trim() }, "tfTodoSec");
    });
  }
  function tfCycMark(v) { // 번호 왼쪽 C 표시. 칸 글이 툴팁이다
    const m = tfCycParse(v), c = el("b", `cm${m && m.pending ? " pend" : ""}`, "C");
    c.title = T("Cycle 켜짐: {v}", { v }) + (m && m.pending ? T(". 비운 칸은 Cycle 1 분석이 정해 이 줄에 채운다") : "");
    return c;
  }
  const g1 = (v) => (v == null || isNaN(v) ? "-" : (+v).toFixed(1));
  const fmtv = (v) => (v == null ? "-" : `${+Number(v).toFixed(3)}`);
  // 회차별 값 작은 선. 점선은 목표, 속 찬 점은 채택한 회차다. 잰 회차가 없으면 그리지 않는다
  function tfSpark(rounds, target, w = 180, h = 46) {
    const vs = rounds.map((r) => r.score).filter((v) => v != null), ns = "http://www.w3.org/2000/svg";
    if (!vs.length) return null;
    const svg = document.createElementNS(ns, "svg"); svg.setAttribute("class", "spark"); svg.setAttribute("width", w); svg.setAttribute("height", h);
    const tg = target != null && !isNaN(+target) ? +target : null, all = tg == null ? vs : vs.concat([tg]);
    const P = 4, lo = Math.min(...all), hi = Math.max(...all), sp = hi - lo || 1, n = Math.max(2, rounds.length);
    const X = (i) => P + (i * (w - 2 * P)) / (n - 1), Y = (v) => h - P - ((v - lo) / sp) * (h - 2 * P);
    const mk = (tag, at) => { const e = document.createElementNS(ns, tag); for (const k in at) e.setAttribute(k, at[k]); svg.appendChild(e); return e; };
    if (tg != null) mk("line", { x1: P, x2: w - P, y1: Y(tg), y2: Y(tg), stroke: "var(--good)", "stroke-dasharray": "3 3" });
    const pts = rounds.map((r, i) => (r.score == null ? null : [X(i), Y(r.score)])).filter(Boolean);
    mk("polyline", { points: pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join(" "), fill: "none", stroke: "var(--run)", "stroke-width": 1.5 });
    rounds.forEach((r, i) => {
      if (r.score == null) return;
      const c = mk("circle", { cx: X(i), cy: Y(r.score), r: 2.5, fill: r.adopt ? "var(--run)" : "var(--surface)", stroke: "var(--run)" });
      const t = document.createElementNS(ns, "title"); t.textContent = `Cycle ${r.n} ${fmtv(r.score)}${r.adopt ? T(", 채택") : ""}`; c.appendChild(t);
    });
    return svg;
  }
  // 왼쪽 상자는 대기열과 예약이다(261029-jipsa-20). GPU와 RAM 실측은 머리 줄에 있어 이 탭에서는 보이지 않는다.
  // 줄은 한 줄이다. 순번(예약은 시각), 프로젝트, 이름, 오른쪽 끝 단추다. 이름이 길면 말줄임하고 마우스를 올리면 전문이 보인다
  function tfLine(lead, project, text, tail) {
    const it = el("div", "qi"), hd = el("div", "qh");
    hd.appendChild(lead);
    const sp = el("span", "sp"); sp.appendChild(el("span", "pj", pname(project))); sp.append(` ${text}`); sp.title = `${pname(project)} ${text}`;
    hd.append(sp, tail); it.appendChild(hd); return it;
  }
  function drawRes(L) {
    const box = $("tfRes"); box.textContent = "";
    const g = L.gpu || {};
    if (g.over) box.appendChild(el("div", "rb why", T("GPU 실측이 커 새 GPU 작업을 {t}까지 멈춘다({p})", { t: hhmm(parse(g.over.until)), p: pname(g.over.project) })));
    const q = L.queue || [], qs = el("div", "q");
    qs.appendChild(el("h2", null, T("대기열")));
    q.forEach((r, i) => qs.appendChild(tfLine(el("span", "no", String(i + 1)), r.project, r.title,
      tfButton(T("빼기"), T("대기열에서 빼고 요청을 거둔다"), () => gpuAct(r.key, "cancel", r.title), true))));
    if (!q.length) qs.appendChild(el("div", "hint pad", T("없다")));
    box.appendChild(qs);
    const sch = L.scheduled || [], ss = el("div", "q");
    ss.appendChild(el("h2", null, T("예약")));
    for (const c of sch) {
      const at = el("span", "no wide", hhmm(parse(c.start)));
      if (c.cycle) at.title = T("{a}에 시작, 마감 {b}", { a: hhmm(parse(c.start)), b: hhmm(parse(c.cutoff)) });
      ss.appendChild(tfLine(at, c.project, c.text,
        tfButton(T("빼기"), T("예약을 지우고 할 일로 둔다 (jipsa todo stop {no})", { no: c.no }), () => tfRun({ name: "todo stop", key: c.key }, "tfTodoSec"), true)));
    }
    if (!sch.length) ss.appendChild(el("div", "hint pad", T("없다")));
    box.appendChild(ss);
  }
  function drawNow(L) {
    const box = $("tfNow"); box.textContent = "";
    const cs = L.cycles || [];
    box.appendChild(el("h2", null, "Cycle"));
    for (const c of cs) {
      const lane = el("div", `lane${c.running ? "" : " wait"}`);
      const nm = el("div", "nm"), t = el("b");
      t.appendChild(el("span", "lno", `${c.no} `)); t.append(c.text); nm.appendChild(t);
      nm.appendChild(el("div", "meta", pname(c.project)));
      const st = el("span", `st ${c.state === "closing" ? "stop" : c.running ? "run" : "todo"}`); st.appendChild(el("i")); st.append(c.paused || c.where || c.note); st.title = c.note; nm.appendChild(st);
      if (c.branch || c.branch_open || c.branch_closed) {
        const br = el("div", "br", T("갈래 ")); br.appendChild(el("b", null, c.branch || "-"));
        if (c.branch_open || c.branch_closed) br.appendChild(el("span", "hint", T(" 열림 {a}, 닫힘 {b}", { a: c.branch_open, b: c.branch_closed }))); // 둘 다 0이면 이름만 둔다
        nm.appendChild(br);
      }
      const reached = c.score != null && c.target != null && (c.direction === "이하" ? c.score <= c.target : c.score >= c.target);
      const met = el("div", "met");
      met.appendChild(el("span", null, c.metric || T("지표 미정"))); met.append(T(" 지금 "));
      met.appendChild(el("b", reached ? "ok" : null, `${fmtv(c.score)} `)); // 잰 값이 없으면 "-"다. 회차 수는 아래 진척 막대 옆에 있다
      met.appendChild(el("span", "tg", T("목표 {t}", { t: c.target == null ? T("미정") : `${fmtv(c.target)} ${T(c.direction)}` }))); nm.appendChild(met);
      const pct = Math.round((c.progress || 0) * 100), pb = el("div", "pbar"), bar = el("div", `bar${reached ? " good" : ""}`), fill = el("div");
      fill.style.width = `${pct}%`; bar.appendChild(fill); bar.title = T("시작에서 마감까지 {n}% 지남", { n: pct });
      pb.append(bar, T("{n}회차", { n: (c.rounds || []).filter((r) => r.judge).length })); nm.appendChild(pb);
      // GPU와 RAM 배지는 뗐다(261029-jipsa-20). 실측은 머리 줄에 있다. 새 GPU 작업을 막는 관찰만 배지로 남긴다
      if (c.signal) {
        const chips = el("div", "chips");
        chips.appendChild(el("span", "chip sig", T("큰 GPU 일 관찰 중{u}. 새 GPU 작업을 막는다", { u: c.signal.until ? T(", {t}까지", { t: hhmm(parse(c.signal.until)) }) : "" })));
        nm.appendChild(chips);
      }
      lane.appendChild(nm);
      const sk = el("div", "sk"), svg = tfSpark(c.rounds || [], c.target);
      if (svg) { sk.appendChild(svg); sk.title = T("회차별 값, 점선은 목표"); } // 잰 회차가 없으면 비워 둔다. 0회차가 아래에 보인다
      lane.appendChild(sk);
      // 피드백 칸(261029-jipsa-19). 결과지 서랍의 답 넣기 칸과 같은 여러 줄 칸이다. Enter는 줄바꿈, Ctrl+Enter는 넣기.
      // 줄마다 되풀이되던 키 안내와 글자 수는 뗐다(261029-jipsa-20). 키 안내는 빈 칸의 자리 글이다
      const fb = el("div", "fb"), fr = el("form", "fbr"); fr.autocomplete = "off";
      const fi = el("textarea", null); fi.rows = 3; fi.placeholder = T("Ctrl+Enter로 넣기"); fi.setAttribute("aria-label", T("피드백"));
      fi.value = tfFbDraft[c.key] || "";
      const row = el("div", "answer-row"), fbB = el("button", "tf-btn", T("피드백 넣기")); fbB.type = "submit";
      row.append(fbB);
      fr.append(fi, row);
      fi.addEventListener("input", () => { tfFbDraft[c.key] = fi.value; });
      fi.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" || ev.isComposing || ev.keyCode === 229) return;
        if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); fr.requestSubmit(); }
      });
      fr.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const text = fi.value.trim(); if (!text) return;
        delete tfFbDraft[c.key];
        tfRun({ name: "todo feedback", key: c.key, text }, "tfTodoSec");
      });
      fb.appendChild(fr);
      const fl = el("div", "fbls");
      for (const f of (c.feedback || []).slice().reverse()) { // 한 줄에 시각과 글. 길거나 여러 줄이면 말줄임하고 마우스를 올리면 전문이 보인다
        const l = el("div", "fbl"), t = el("div", "fbt", f.text.replace(/\s*\n\s*/g, " / "));
        l.title = f.text; l.append(el("span", null, f.at ? hhmm(parse(f.at)) : ""), t); fl.appendChild(l);
      }
      if ((c.feedback || []).length) fb.appendChild(fl);
      lane.appendChild(fb);
      const act = el("div", "act");
      const kv = (k, node) => { const d = el("div", "kv"); d.appendChild(el("span", null, k)); d.append(node); act.appendChild(d); };
      kv(T("시작"), hhmm(parse(c.start)));
      const ui = el("input", null); ui.type = "text"; ui.value = hhmm(parse(c.cutoff)); ui.setAttribute("aria-label", T("마감")); ui.title = T("HH:MM이나 +2h로 고치고 Enter. 돌던 단계는 끊지 않는다");
      ui.addEventListener("change", () => { if (ui.value.trim()) tfRun({ name: "todo until", key: c.key, until: ui.value.trim() }, "tfTodoSec"); });
      kv(T("마감"), ui);
      act.appendChild(el("div", "hint", T("끝 예상 {t}", { t: hhmm(parse(c.est_end)) })));
      const sb = tfButton(T("멈추기"), T("돌던 단계를 마치고 마감 결과지를 쓴 뒤 할 일로 돌린다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계) (jipsa todo stop)"), () => {
        if (window.confirm(T("이 Cycle을 멈춘다. 돌던 단계는 끝까지 두고 할 일로 돌아온다.\n\n{t}", { t: c.text }))) tfRun({ name: "todo stop", key: c.key }, "tfTodoSec");
      }, true);
      if (c.stopped || c.state === "closing") { sb.disabled = true; sb.textContent = T("닫는 중"); }
      act.appendChild(sb); lane.appendChild(act);
      box.appendChild(lane);
    }
    if (!cs.length) box.appendChild(el("div", "hint pad", T("없다")));
  }
  function drawBand(L) {
    const band = $("tfBand"), focus = document.activeElement;
    if (focus && band.contains(focus) && (focus.tagName === "INPUT" || focus.tagName === "TEXTAREA")) return; // 마감이나 피드백을 적는 중에는 다시 그리지 않는다
    if (tfBandPress) return; // 단추를 누르는 사이에 다시 그리면 그 누름이 사라진다. 다음 갱신에 그린다
    const sig = JSON.stringify([L, bandOpen()]);
    if (sig === tfBandSig) return;
    tfBandSig = sig;
    drawLine(L); band.hidden = !bandOpen();
    drawRes(L); drawNow(L);
  }
  // 한 줄 띠(42 초안 구역 11, 우선순위 3): 대기열, 예약, Cycle의 건수와 첫 항목만 한 줄에 적는다. 펼치기를 누르면 아래에 상자가 나오고 이 창에 기억한다
  const BAND_KEY = "jipsa.tfBand";
  const bandOpen = () => { try { return localStorage.getItem(BAND_KEY) === "1"; } catch { return false; } };
  const setBandOpen = (v) => { try { localStorage.setItem(BAND_KEY, v ? "1" : "0"); } catch { /* 저장이 막혀도 된다 */ } };
  function drawLine(L) {
    const line = $("tfLine"); line.textContent = "";
    const q = L.queue || [], sch = L.scheduled || [], cs = L.cycles || [], g = L.gpu || {};
    const item = (k, rows, text) => {
      const s = el("span", rows.length ? "it" : null); s.append(`${T(k)} `); s.appendChild(el("b", null, rows.length ? String(rows.length) : T("없음")));
      if (rows.length) { s.append(" "); s.appendChild(el("span", "mono", text(rows[0]))); if (rows.length > 1) s.append(T(" 외 {n}", { n: rows.length - 1 })); s.title = rows.map(text).join("\n"); }
      line.appendChild(s);
    };
    if (g.over) line.appendChild(el("span", "it why", T("GPU 실측이 커 새 GPU 작업을 {t}까지 멈춘다", { t: hhmm(parse(g.over.until)) })));
    item("대기열", q, (r) => `${pname(r.project)} ${r.title}`);
    item("예약", sch, (c) => `${pname(c.project)} ${hhmm(parse(c.start))} ${c.text}`);
    item("Cycle", cs, (c) => `${pname(c.project)} ${c.text}${c.where ? `, ${c.where}` : ""}`);
    const b = el("button", "lnk", bandOpen() ? T("접기") : T("펼치기")); b.type = "button"; b.title = T("대기열 빼기, 예약 빼기, Cycle 마감과 피드백과 멈추기");
    b.addEventListener("click", () => { setBandOpen(!bandOpen()); tfBandSig = ""; drawBand(state.data && state.data.todofile ? state.data.todofile.lanes || {} : {}); });
    line.appendChild(b);
  }
  // 한 칸의 줄. rows는 머리 줄(N건)을 뺀 번호 줄과 기타 줄(이어 갈 줄, 읽지 못한 줄)이다
  function tfList(host, rows, emptyText) {
    host.textContent = "";
    if (!rows.length) { host.appendChild(el("p", "tf-empty", emptyText)); return; }
    for (const r of rows) {
      const c = r.cells, row = el("div", c ? "tf-row wide b3" : /읽지 못한 줄/.test(r.text) ? "tf-row raw bad" : "tf-row raw");
      if (c) {
        row.dataset.no = c.no;
        const nn = el("span", "no"); if (c.cycle) nn.appendChild(tfCycMark(c.cycle)); nn.appendChild(el("i", null, `${c.no}`)); row.appendChild(nn);
        row.appendChild(el("span", "project", c.project));
        const main = el("div", "main"), tx = el("div", "text", c.text); main.appendChild(tx);
        if (TF_META.some((k) => c[k])) {
          const meta = el("div", "meta");
          for (const k of TF_META) {
            if (!c[k]) continue;
            const s = el("span", k), lab = k === "criteria" ? null : /^(\S+)(\s.*)$/.exec(c[k]); // 한도 칸은 첫 낱말이 칸 이름이다
            if (lab) { s.appendChild(el("span", "k", lab[1])); s.append(lab[2]); } else s.textContent = c[k];
            meta.appendChild(s);
          }
          main.appendChild(meta);
        }
        const cy = r.cycle;
        if (cy && (cy.rounds || []).length) { // 앞서 돈 Cycle 줄은 회차 수와 지금 값을 보인다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계)
          const m = el("div", "met"), p = tfCycParse(c.cycle) || {};
          m.append(T("{n}회차 돎. {m} 지금 ", { n: cy.rounds.length, m: p.metric || T("지표") })); m.appendChild(el("b", null, fmtv(cy.score)));
          if (p.target) m.appendChild(el("span", "tg", T("목표 {t}", { t: `${p.target} ${T(p.dir || "이상")}` })));
          main.appendChild(m);
        }
        if (cy && cy.paused) main.appendChild(el("div", "tf-note pause", cy.paused));
        if (c.status) { // 줄 끝 상태 글. jipsa todo 줄 끝과 같다
          const note = el("div", "tf-st tf-note"), dot = el("span", `st ${/^기준 고르기 대기/.test(c.status) ? "cue" : "run"}`);
          dot.appendChild(el("i")); dot.append(c.status); note.appendChild(dot); main.appendChild(note);
        }
        if (tfDo && r.item && tfDo.key === r.item.key) main.appendChild(tfDoForm(r));
        if (tfCyc && r.item && tfCyc.key === r.item.key) main.appendChild(tfCycForm(r));
        row.appendChild(main);
        row.appendChild(tfBtns(r));
      } else { // 칸으로 나누지 못한 줄은 줄 글 그대로 둔다
        const td = el("div", "rawtext");
        td.append(r.text.trim()); row.appendChild(td);
        if (r.item) row.appendChild(tfBtns(r));
      }
      host.appendChild(row);
    }
  }
  function drawTodoFile(v) {
    if (!v) return;
    const sel = $("tfProject"), want = (v.projects || []).join("\n");
    if (sel.dataset.list !== want) { // 등록부가 바뀔 때만 다시 채워 고른 값을 지킨다
      const keep = sel.value; sel.textContent = ""; sel.dataset.list = want;
      for (const p of v.projects || []) { const o = el("option", null, pname(p)); o.value = p; sel.appendChild(o); }
      let last = ""; try { last = localStorage.getItem("jipsa.tfProject") || ""; } catch { /* 비공개 창 */ } // 기본값은 마지막에 넣은 프로젝트다(42 초안 우선순위 12)
      if (keep && (v.projects || []).includes(keep)) sel.value = keep; else if (last && (v.projects || []).includes(last)) sel.value = last;
    }
    drawBand(v.lanes || {});
    // 할 일 칸: "할 일 N건" 줄과 파일이 비었다는 안내 줄은 빼고 머리 건수와 그 가운데 Cycle 수를 센다
    const todo = v.todo || [];
    tfBoxCheck(todo);
    drawPlacing(v.placing || []);
    // 한 번 돈 Cycle 줄(회차 기록이 있는 줄)은 결과지가 타임라인과 현황판에 있어 전체와 Cycle 고르기에서 감춘다(261029-jipsa-49).
    // 줄은 파일에 그대로 있다. 지난 Cycle 고르기에서 보이고 Do로 멈춘 자리부터 잇는다
    const ran = (r) => !!(r.cells && r.cells.cycle && r.cycle && (r.cycle.rounds || []).length);
    const all = todo.filter((r) => !/^할 일 \d+건/.test(r.text) && !/^할 일이 없다/.test(r.text) && !/^(Auto|메모) \d+건/.test(r.text));
    const nr = all.filter(ran).length;
    const nc0 = all.filter((r) => r.cells && r.cells.cycle && !ran(r)).length;
    if ((tfFilt === "ran" && !nr) || (tfFilt === "cycle" && !nc0)) tfFilt = "all";
    const tRows = all.filter((r) => tfFilt === "ran" ? ran(r) : !ran(r) && (tfFilt === "all" || (r.cells && r.cells.cycle)));
    const nc = nc0, nt = all.filter((r) => r.cells && !ran(r)).length;
    $("tfTodoN").textContent = nc ? T("{n}건, Cycle {c}", { n: nt, c: nc }) : T("{n}건", { n: nt });
    const rb = document.querySelector('#tfFilter button[data-f="ran"]');
    rb.hidden = !nr; rb.textContent = T("지난 Cycle {n}", { n: nr }); rb.title = T("한 번 돈 Cycle 줄. 결과지는 타임라인에 있고, Do로 멈춘 자리부터 잇는다");
    document.querySelector('#tfFilter button[data-f="cycle"]').hidden = !nc;
    $("tfFilter").hidden = !nc && !nr; // 고를 것이 없으면 숨긴다
    for (const x of document.querySelectorAll("#tfFilter button")) x.classList.toggle("on", x.dataset.f === tfFilt);
    if (tfDo && !all.some((r) => r.item && r.item.key === tfDo.key)) tfDo = null;
    if (tfCyc && !all.some((r) => r.item && r.item.key === tfCyc.key)) tfCyc = null;
    const focus = document.activeElement, typing = focus && $("tfTodo").contains(focus) && focus.tagName === "INPUT";
    const tSig = JSON.stringify([tRows, tfDo && tfDo.key, tfCyc && tfCyc.key]);
    if (tSig !== tfTodoSig && !typing) { // 입력 중인 값을 주기 새로 그리기가 지우지 않게 한다
      tfList($("tfTodo"), tRows, tfFilt === "all" ? T("할 일이 없다. 위 넣기 칸으로 넣는다") + (nr ? T(". 한 번 돈 Cycle {n}건은 지난 Cycle에 있다", { n: nr }) : "") : T("보일 줄이 없다"));
      tfTodoSig = tSig;
    }
  }
  for (const b of document.querySelectorAll("#tfFilter button")) {
    b.addEventListener("click", () => {
      tfFilt = b.dataset.f; for (const x of document.querySelectorAll("#tfFilter button")) x.classList.toggle("on", x === b);
      tfTodoSig = ""; drawTodoFile(state.data && state.data.todofile);
    });
  }
  // 넣는 중 띠(261029-jipsa-49). Do로 시켰고 아직 첫 실행이 시작하지 않은 줄만 한 줄씩 보인다. 서버가 실행 시작을 보면 그 줄을 빼므로
  // 타임라인과 현황판에 들어가면 다음 갱신에 저절로 사라진다. Do와 Rm의 성공 출력 칸은 이 띠로 갈음해 열지 않는다
  let tfPlaceSig = "";
  function drawPlacing(rows) {
    const box = $("tfPlacing"), sig = JSON.stringify(rows);
    if (sig === tfPlaceSig) return;
    tfPlaceSig = sig; box.textContent = ""; box.hidden = !rows.length;
    for (const p of rows) {
      const l = el("div", "tf-pl"), st = el("span", "st run"); st.appendChild(el("i")); st.append(p.session ? T("세션에 넣는 중") : T("스케줄러에 넣는 중"));
      const sp = el("span", "sp"); sp.appendChild(el("span", "pj", pname(p.project))); sp.append(` ${p.cycle ? "Cycle " : ""}${p.text}`);
      const nt = el("span", "nt", p.note.replace(/^[^.]*\.\s*/, ""));
      l.title = `${pname(p.project)} ${p.text}\n${p.note}`; l.append(st, sp, nt); box.appendChild(l);
    }
  }
  // 성공한 명령의 출력 칸은 할 일 칸의 줄 구성(번호 줄의 key)이 그 명령 뒤에 바뀌면 닫는다(261025-jipsa-54). 실패 출력은 그대로 둔다
  let tfBox = null; // {id: 출력 글, keys: 열 때의 줄 구성}
  function tfBoxCheck(todo) {
    const box = $("tfOutBox"), id = `${$("tfCmd").textContent}\n${$("tfOut").textContent}`;
    const keys = todo.filter((r) => r.item || /^이어 갈 줄: /.test(r.text))
      .map((r) => r.item ? `${r.item.section}:${r.item.key}` : r.text.split(" | ").slice(0, 3).join(" | ")).join("\n");
    if (box.hidden || !box.classList.contains("ok")) { tfBox = null; return; }
    if (!tfBox || tfBox.id !== id) { tfBox = { id, keys }; return; }
    if (tfBox.keys !== keys) { box.hidden = true; tfBox = null; }
  }
  // 명령을 돌리고 출력 칸을 그 명령을 돌린 칸의 머리 아래로 옮겨 보인다. 출력 칸은 하나다
  let tfGen = 0; // 명령 세대. 명령 앞에 나간 주기 갱신 응답이 명령 뒤에 닿아 옛 칸 줄로 덮는 것을 막는다(pollLive)
  async function tfRun(body, secId) {
    if (tfBusy) return; tfBusy = true; tfGen++;
    const panel = $("tfPanel"); panel.classList.add("busy");
    for (const b of panel.querySelectorAll("button")) b.disabled = true;
    let d;
    try { d = await postJson("/api/command", body); } catch (e) { d = { ok: false, out: T("서버에 닿지 못했다") }; }
    tfGen++;
    const box = $("tfOutBox"), sec = $(secId);
    if (sec && box.parentNode !== sec) sec.insertBefore(box, sec.querySelector(".tf-list"));
    box.hidden = false; box.className = `tf-out ${d.ok ? "ok" : "fail"}`;
    $("tfCmd").textContent = d.cmd || body.name || "";
    const out = $("tfOut"); out.textContent = "";
    for (const line of (d.out || d.error || "").split("\n")) out.appendChild(el("div", null, line));
    if (d.ok && /^todo (run|rm)$/.test(body.name)) box.hidden = true; // 성공한 Do와 Rm은 출력 칸을 열지 않는다. 시킨 줄은 넣는 중 띠에 보인다(261029-jipsa-49)
    for (const b of panel.querySelectorAll("button")) b.disabled = false;
    panel.classList.remove("busy"); tfBusy = false;
    if (d.ok && body.name === "todo add") $("tfText").value = "";
    if (d.ok && body.name === "todo memo") $("memoText").value = "";
    if (d.ok && /^todo (up|memo-rm)$/.test(body.name)) memoUp = null;
    if (d.ok && body.name === "todo run") tfDo = null;
    if (d.ok && body.name === "todo cycle") tfCyc = null;
    tfTodoSig = ""; tfBandSig = "";
    if (document.activeElement && $("tfBand").contains(document.activeElement)) document.activeElement.blur();
    if (d.view) {
      if (state.data) { state.data.todofile = d.view; state.data.todo_file_n = d.view.n; }
      drawTodoFile(d.view); memoSig = ""; drawMemo(d.view); // 할 일로 올린 줄이 할 일 칸에 바로 보인다
    }
    refreshNow(); // 머리 숫자를 바로 다시 받는다
    return d;
  }
  $("modePill").addEventListener("click", () => { if (state.view === "live") goQueue(); });
  $("gqPill").addEventListener("click", goQueue);
  $("tfAdd").addEventListener("submit", (ev) => {
    ev.preventDefault();
    try { localStorage.setItem("jipsa.tfProject", $("tfProject").value); } catch { /* 저장이 막혀도 된다 */ }
    tfRun({ name: "todo add", project: $("tfProject").value, text: $("tfText").value }, "tfTodoSec");
  });
  $("tfOutClose").addEventListener("click", () => { $("tfOutBox").hidden = true; });
  // 프로젝트 만들기(261103-jipsa-07). 이름 하나만 보내고 결과와 오류는 칸 아래 한 줄로 보인다. 만든 프로젝트를 넣기 줄에 바로 고른다
  $("tfNew").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const name = $("tfNewName").value.trim(), out = $("tfNewOut"), btn = $("tfNewBtn");
    if (!name) { $("tfNewName").focus(); return; }
    btn.disabled = true;
    let d;
    try { d = await postJson("/api/project", { name }); } catch (e) { d = { ok: false, text: T("만들지 못했다: 서버에 닿지 못했다") }; }
    btn.disabled = false;
    out.hidden = false; out.className = `tf-new-out ${d.ok ? "ok" : "fail"}`; out.textContent = d.text || "";
    if (d.ok) {
      $("tfNewName").value = "";
      try { localStorage.setItem("jipsa.tfProject", d.project); } catch { /* 저장이 막혀도 된다 */ }
    }
    if (d.view) {
      if (state.data) { state.data.todofile = d.view; state.data.todo_file_n = d.view.n; }
      tfTodoSig = ""; drawTodoFile(d.view);
    }
    if (d.ok) $("tfProject").value = d.project;
  });

  // 메모 칸. 할 일 파일의 메모 절이다. 넣기, 할 일로, 지우기는 jipsa todo memo, jipsa todo up, jipsa todo memo-rm과 같은 명령이다.
  // 할 일로는 줄 아래에 프로젝트와 기준을 받는 줄을 연다. 메모가 이미 프로젝트 | 할 일 꼴이면 프로젝트를 고르지 않고 올린다
  function memoUpRow(m, projects) {
    const row = el("div", "tf-row tf-up"), form = el("form", null); form.autocomplete = "off";
    const sel = el("select", null); sel.setAttribute("aria-label", T("올릴 프로젝트"));
    const none = el("option", null, T("프로젝트 고르기")); none.value = ""; sel.appendChild(none);
    for (const p of projects) { const o = el("option", null, pname(p)); o.value = p; sel.appendChild(o); }
    sel.value = memoUp.project || "";
    const inp = el("input", null); inp.type = "text"; inp.value = memoUp.text || "";
    inp.setAttribute("aria-label", T("덧붙일 칸")); inp.placeholder = T("기준(선택). cycle, 한도 칸은 | 뒤에");
    const ok = el("button", "tf-btn", T("올리기")); ok.type = "submit"; ok.title = T("jipsa todo up {l} <프로젝트> | <기준>", { l: m.label });
    const no = tfButton(T("취소"), T("할 일로 줄을 닫는다"), () => { memoUp = null; memoSig = ""; drawMemo(state.data && state.data.todofile); });
    sel.addEventListener("change", () => { memoUp.project = sel.value; });
    inp.addEventListener("input", () => { memoUp.text = inp.value; });
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      tfRun({ name: "todo up", key: m.key, project: sel.value, text: inp.value }, "memoPanel");
    });
    form.append(sel, inp, ok, no); row.appendChild(form);
    return row;
  }
  function drawMemo(v) {
    if (!v) return;
    const rows = v.memo || [], projects = v.projects || [];
    const sig = JSON.stringify([rows, projects, memoUp && memoUp.key]);
    if (sig === memoSig) return; // 주기 새로 그리기가 열린 할 일로 줄과 입력 중인 값을 지우지 않게 바뀔 때만 다시 그린다
    memoSig = sig;
    if (memoUp && !rows.some((m) => m.key === memoUp.key)) memoUp = null;
    $("memoN").textContent = T("{n}건", { n: rows.length });
    const host = $("memoList"); host.textContent = "";
    if (!rows.length) { host.appendChild(el("p", "tf-empty", T("메모가 없다. 위 넣기 칸으로 넣는다"))); return; }
    for (const m of rows) {
      const row = el("div", `tf-row memo${memoUp && memoUp.key === m.key ? " open" : ""}`);
      row.appendChild(el("span", "no", m.label));
      const main = el("div", "main"); main.appendChild(el("div", "text", m.text)); row.appendChild(main);
      const bs = el("div", "btns");
      bs.appendChild(tfButton(T("할 일로"), T("프로젝트와 기준을 붙여 할 일 칸으로 옮긴다 (jipsa todo up {l})", { l: m.label }), () => {
        memoUp = memoUp && memoUp.key === m.key ? null : { key: m.key, project: "", text: "" };
        memoSig = ""; drawMemo(state.data && state.data.todofile);
      }));
      bs.appendChild(tfMore(m.key, [tfButton(T("지우기"), T("메모를 지운다 (jipsa todo memo-rm {l})", { l: m.label }), () => {
        closeTfMenu();
        if (!window.confirm(T("이 메모를 지운다.\n\n{t}", { t: m.text }))) return;
        tfRun({ name: "todo memo-rm", key: m.key }, "memoPanel");
      }, true)]));
      row.appendChild(bs); host.appendChild(row);
      if (memoUp && memoUp.key === m.key) host.appendChild(memoUpRow(m, projects));
    }
  }
  $("memoAdd").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!$("memoText").value.trim()) return; // 빈 글은 넣지 않는다(서버도 거절한다)
    tfRun({ name: "todo memo", text: $("memoText").value }, "memoPanel");
  });

  // ----- 결과지 서랍 -----
  // 초안 미리보기 단추. 주소가 없으면 숨기고, 서버가 응답하지 않으면 옆에 꺼짐을 붙인다(확인은 대시보드 서버가 로컬 주소만 한다)
  async function setPreview(url) {
    const a = $("drPreview"), off = $("drPreviewOff");
    a.hidden = !url; off.hidden = true; a.href = url || "#"; a.onclick = null; a.title = "";
    if (!url) return;
    if (url.startsWith("file:")) { // 브라우저가 http 페이지에서 file 주소를 막으므로 주소를 복사해 알린다
      a.onclick = (ev) => { ev.preventDefault(); try { navigator.clipboard.writeText(url); } catch (e) { /* 복사 실패는 안내만 한다 */ } a.title = T("file 주소를 복사했다. 브라우저 주소창에 붙여 넣는다"); };
      return;
    }
    try { const r = await fetch(`/api/preview?url=${encodeURIComponent(url)}`); const d = await r.json(); if (a.getAttribute("href") === url) off.hidden = d.up !== false; }
    catch (e) { /* 확인 실패는 표시하지 않는다 */ }
  }
  // 초안 표식(261031-jipsa-10). begin --draft나 사람 입력의 '초안'으로 표시한 실행은 서랍 머리에 초안 표식을 두고,
  // 미리보기 주소가 비어 초안 보기 단추가 뜨지 못하면 그 자리에 주소 없음을 적어 결과지로만 보이는 까닭을 알린다
  function setDraft(m) {
    const d = $("drDraft"), off = $("drPreviewOff");
    d.hidden = !m.draft;
    if (m.draft && !m.preview_url) { off.textContent = T("초안 주소 없음"); off.title = T("초안 실행인데 결과 파일의 미리보기 주소가 비어 초안 보기 단추가 뜨지 않는다"); off.hidden = false; }
    else { off.textContent = T("미리보기 꺼짐"); off.title = ""; }
  }
  const draftTag = (r) => el("span", `tag draft${r.preview ? "" : " miss"}`, r.preview ? T("초안") : T("초안, 주소 없음")); // 목록 줄의 초안 표식

  // 서랍 머리의 지시 글은 세 줄을 넘으면 접고 [전체 보기]를 둔다. 펼친 상태는 같은 실행을 주기로 다시 받을 때만 이어 간다
  function fitName(runId) {
    const n = $("drName"), b = $("drNameMore"), open = !!runId && state.nameOpen === runId;
    n.classList.remove("open"); n.classList.add("clamp");
    const long = n.scrollHeight > n.clientHeight + 1;
    n.classList.toggle("clamp", !(long && open)); n.classList.toggle("open", long && open);
    b.hidden = !long; b.textContent = open ? T("접기") : T("전체 보기"); b.setAttribute("aria-expanded", long && open ? "true" : "false");
  }
  $("drNameMore").addEventListener("click", () => { state.nameOpen = state.nameOpen === state.open ? "" : state.open; fitName(state.open); });
  window.addEventListener("resize", () => { if (!$("drawer").hidden) fitName(state.open); }); // 폭이 바뀌면 줄 수도 바뀐다

  // quiet: 진행 중 작업의 서랍을 주기로 다시 받을 때다. 비우지 않고 스크롤과 입력 중인 답을 그대로 둔다
  async function openResult(runId, quiet) {
    if (!runId) return;
    state.open = runId;
    $("drawer").hidden = false; $("scrim").hidden = false;
    if (!quiet) {
      state.nameOpen = ""; $("drName").textContent = runId; fitName(""); $("drMeta").textContent = ""; $("drStatus").textContent = ""; $("drBody").textContent = T("불러오는 중");
      $("drAnswer").hidden = true; $("drFoot").hidden = true; $("drRawLine").hidden = true; setPreview("");
    }
    const scrollTop = $("drScroll").scrollTop;
    clearTimeout(state.drawerTimer);
    try {
      const r = await fetch(`/api/run?id=${encodeURIComponent(runId)}`); const d = await r.json();
      if (d.error) { $("drBody").textContent = d.error; return; }
      const m = d.meta;
      $("drName").textContent = runName(m); fitName(runId);
      drawHeadStatus(runId, m, d.shown);
      $("drMeta").textContent = `${m.run_id}  ${T(EXECUTOR[m.executor] || "")}  ${dur(m.minutes_used, m.minutes_limit)}${budgetText(m) ? `  (${budgetText(m)})` : ""}`;
      $("drRaw").href = `/api/sheet?id=${encodeURIComponent(runId)}`; $("drRawLine").hidden = false; // 원문 링크는 본문 끝 열어 볼 파일 옆이다(42 초안 우선순위 16)
      setPreview(m.preview_url || ""); setDraft(m);
      renderMd(d.sheet || "", $("drBody"), d.base || "");
      drawConfirm(runId, m); // 끝난 실행과 상태 값 확인 필요 모두 답 칸과 확인 단추를 같이 둔다. 확인 단추는 서랍 바닥 고정 줄이다
      drawAnswered(runId, d.answered);
      if (quiet) $("drScroll").scrollTop = scrollTop;
      if (!d.answerable) $("drAnswer").hidden = true; // 확인을 누르거나 답을 넣으면 답 칸을 닫는다
      if (d.answerable && quiet && !$("drAnswer").hidden) { /* 답을 쓰는 중이면 건드리지 않는다 */ }
      else if (d.answerable) {
        $("drAnswer").hidden = false; $("drAnswerNote").textContent = ""; $("drInput").value = ""; clearImages(); fitAnswer();
        // 끝난 실행의 답은 다시 돌리지 않고 세션에 넘긴다. 선택지를 보고서 정할 것에서 자동으로 뽑았으면 그렇게 적는다
        // 확인하지 않은 완료와 실패도 확인 필요다. 답을 넣으면 확인되어 완료가 된다(261023-jipsa-26)
        const plain = m.status !== "확인 필요" && !(d.choices || []).length && !(d.notes || []).length; // 고를 것 없는 확인 필요 결과
        const unseen = m.status !== "확인 필요" && ackState(runId, m.status, m.finished) === "cue";
        $("drAnswer").querySelector(".t").textContent = m.status === "확인 필요" ? T("확인 필요, 답을 넣을 것. 선택지를 누르거나 직접 적는다.")
          : plain ? T("확인 필요 결과다. 확인이라고 넣거나 덧붙일 지시를 적으면 확인되어 완료가 된다. 지시는 세션에 넘어가고 다시 돌리지 않는다.")
          : unseen ? T("확인 필요 결과다. {c}직접 적어 넣으면 확인되어 완료가 된다. 답은 세션에 넘어가고 다시 돌리지 않는다.{a}", { c: (d.choices || []).length ? T("안을 누르거나 ") : "", a: m.options_auto && (d.choices || []).length ? T(" 안은 보고서 정할 것에서 자동으로 뽑았다.") : "" })
          : T("고를 것이 남은 {s} 결과다. {c}직접 적는다. 답은 세션에 넘어가고 다시 돌리지 않는다.{a}", { s: stName(m.status), c: (d.choices || []).length ? T("안을 누르거나 ") : "", a: m.options_auto && (d.choices || []).length ? T(" 안은 보고서 정할 것에서 자동으로 뽑았다.") : "" });
        // 단추는 고를 안(1안, 2안)에만 짧게 두고 안 내용은 옆에 글자로 보인다. 누르면 답 칸에 안 이름이 채워지고 뒤에 추가 지시를 이어 쓸 수 있다
        // 안 이름이 숫자 묶음(1안, 2안)과 가나다 묶음(가안, 나안)처럼 둘 이상이면 묶음마다 단추 한 줄을 두고 묶음마다 하나씩 골라 "1안, 나안"으로 잇는다
        const cs = d.choices || [], groups = [...new Set(cs.map((c) => c.group || ""))], multi = groups.length > 1;
        const opts = $("drOpts"); opts.textContent = ""; opts.className = multi ? "opts groups" : "opts alts"; opts.hidden = !cs.length;
        const btns = [];
        const mark = () => { const got = answerPicks($("drInput").value, cs).picks; for (const [b, c] of btns) { const on = got.get(c.group || "") === c.name; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on ? "true" : "false"); } };
        const button = (c, rec) => {
          const b = el("button", null, rec ? T("{n} (추천)", { n: c.name }) : c.name); b.type = "button"; btns.push([b, c]);
          b.addEventListener("click", () => { const inp = $("drInput"); inp.value = pickAnswer(inp.value, cs, c); mark(); $("drAnswerNote").textContent = T("뒤에 쉼표와 추가 지시를 이어 써도 된다. 답 넣기를 누르면 확정된다"); fitAnswer(); inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }); // 한 번 눌러서는 확정되지 않는다
          return b;
        };
        if (!multi) cs.forEach((c, i) => { opts.appendChild(button(c, i === 0 && c.text.includes("추천"))); opts.appendChild(el("span", "alt-text", c.text)); });
        else for (const g of groups) {
          const mine = cs.filter((c) => (c.group || "") === g), row = el("div", "opt-row"), texts = el("div", "opt-texts");
          mine.forEach((c, i) => { row.appendChild(button(c, i === 0 && c.text.includes("추천"))); texts.appendChild(el("div", "alt-text", c.text)); });
          const box = el("div", "opt-group"); box.append(row, texts); opts.appendChild(box);
        }
        $("drInput").oninput = () => { mark(); syncImages(); };
        for (const id of ["drNotes", "drNotesToggle"]) { const old = $(id); if (old) old.remove(); }
        if ((d.notes || []).length) { // 고를 안이 아닌 정할 것과 남은 일은 단추 없이 글자로만 보인다. 보고서 끝 절과 같은 글이라 기본은 개수 한 줄로 접는다
          // 펼치기 단추는 칸을 스크롤해도 늘 보이는 답 넣기 줄에 두고, 목록은 안 단추 아래에 펼친다
          const label = T("{k} {n}개", { k: cs.length ? T("그 밖의 정할 것") : T("정할 것"), n: d.notes.length });
          const box = el("div", "notes"); box.id = "drNotes";
          box.appendChild(el("div", "notes-t", T("{k} (답 칸에 직접 적는다)", { k: cs.length ? T("그 밖의 정할 것") : T("정할 것") })));
          const ul = el("ul"); for (const t of d.notes) ul.appendChild(el("li", null, t)); box.appendChild(ul);
          const tog = el("button", "notes-toggle"); tog.type = "button"; tog.id = "drNotesToggle"; tog.setAttribute("aria-controls", "drNotes");
          const show = (open) => { box.hidden = !open; tog.setAttribute("aria-expanded", open ? "true" : "false"); tog.textContent = `${label} ${open ? T("접기") : T("펼치기")}`; };
          tog.addEventListener("click", () => {
            const open = box.hidden; setNotesOpen(open); show(open);
            if (open) { const a = $("drAnswer"); a.scrollTop = box.offsetTop - a.offsetTop - 8; } // 펼친 목록이 답 상자 뒤에 숨지 않게 칸 위쪽으로 올린다
          });
          show(notesOpen());
          opts.after(box);
          $("drForm").querySelector(".answer-row button[type=submit]").after(tog);
        }
        $("drForm").onsubmit = (ev) => {
          ev.preventDefault();
          if (pasted.busy) { $("drAnswerNote").textContent = T("그림을 올리는 중이다. 다 올라간 뒤 넣는다"); return; } // 올리기 전에 넣으면 그 그림의 경로 줄이 답에서 빠진다
          const v = $("drInput").value.trim(), ims = keptImages(v);
          if (v && window.confirm(T("이 답으로 확정한다:\n{v}{i}", { v, i: ims.length ? T("\n\n붙인 그림 {n}장은 답 끝에 저장 경로 줄로 붙는다", { n: ims.length }) : "" }))) sendAnswer(runId, v, ims);
        };
      }
      if (m.status === "진행 중") state.drawerTimer = setTimeout(() => { if (state.open === runId) openResult(runId, true); }, 10000);
    } catch (e) { $("drBody").textContent = T("결과지를 불러오지 못했다"); }
  }
  // 답 머리의 안 이름을 묶음별로 읽는다. 안 이름이 아닌 낱말이 나오면 그 뒤는 추가 지시다
  // 서버의 고른 안 판정과 같은 규칙이다. "(추천)"은 건너뛰고 "2안으로"처럼 조사가 붙은 이름도 안 이름으로 읽는다
  const PARTICLE = /(?:\(추천\)|으로|로|을|를|과|와|이|만|도)$/;
  function answerPicks(v, cs) {
    const group = new Map(cs.map((c) => [c.name, c.group || ""])), picks = new Map();
    let rest = v;
    for (;;) {
      const m = rest.match(/^[\s,]*([^\s,]+)/);
      if (!m) break;
      const name = group.has(m[1]) ? m[1] : m[1].replace(PARTICLE, "");
      if (m[1] !== "(추천)" && !group.has(name)) break;
      if (m[1] !== "(추천)" && !picks.has(group.get(name))) picks.set(group.get(name), name);
      rest = rest.slice(m[0].length);
    }
    return { picks, rest: rest.replace(/^[\s,]+/, "") };
  }
  // 안 단추를 누른 뒤의 답. 같은 묶음의 이름만 바꾸고 다른 묶음의 이름과 뒤에 쓴 추가 지시는 그대로 둔다
  function pickAnswer(v, cs, c) {
    const { picks, rest } = answerPicks(v, cs);
    picks.set(c.group || "", c.name);
    const names = [...new Set(cs.map((x) => x.group || ""))].map((g) => picks.get(g)).filter(Boolean);
    return [...names, ...(rest ? [rest] : [])].join(", ");
  }
  const NOTES_KEY = "jipsa.answer.notesOpen"; // 그 밖의 정할 것 목록을 펼쳐 둘지. 기본은 접힘이다
  const notesOpen = () => { try { return localStorage.getItem(NOTES_KEY) === "1"; } catch { return false; } };
  const setNotesOpen = (v) => { try { localStorage.setItem(NOTES_KEY, v ? "1" : "0"); } catch { /* 저장이 막혀도 화면은 돈다 */ } };
  // 답 칸은 글 길이에 맞춰 12줄까지 늘고 그 뒤로는 칸 안에서 스크롤한다. 값을 코드로 바꾼 뒤에도 불러 높이와 글자 수를 맞춘다
  // 답 칸 전체는 화면 높이의 30%가 상한이라 답 상자도 그 안에서만 자란다. 안 내용이 세 줄쯤 보일 자리는 남긴다
  function fitAnswer() {
    const t = $("drInput"); t.style.height = "auto";
    const cs = getComputedStyle(t), lh = parseFloat(cs.lineHeight) || 20, pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    const box = $("drAnswer"), bs = getComputedStyle(box), row = box.querySelector(".answer-row"), title = box.querySelector(".t");
    const room = window.innerHeight * 0.3 - parseFloat(bs.paddingTop) - parseFloat(bs.paddingBottom) - (row ? row.offsetHeight + 6 : 0) - (title ? title.offsetHeight + 6 : 0) - lh * 3;
    const min = lh * 3 + pad, max = Math.max(min, Math.min(lh * 12 + pad, room));
    t.style.height = `${Math.min(Math.max(t.scrollHeight, min), max)}px`;
    $("drCount").textContent = T("{n}자", { n: t.value.length.toLocaleString() });
  }
  function wireAnswerBox() {
    const t = $("drInput");
    t.addEventListener("input", fitAnswer);
    window.addEventListener("resize", () => { if (!$("drAnswer").hidden) fitAnswer(); }); // 창 높이가 바뀌면 상한도 바뀐다
    t.addEventListener("keydown", (ev) => { // Enter는 줄바꿈이다. Ctrl+Enter(맥은 Cmd+Enter)만 넣기이고 한글 조합 중에는 건드리지 않는다
      if (ev.key !== "Enter" || ev.isComposing || ev.keyCode === 229) return;
      if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); $("drForm").requestSubmit(); }
    });
  }
  wireAnswerBox();
  // 답 칸에 붙인 그림. 칸에는 Claude Code CLI처럼 [Image #N] 표시 글자만 들어가고 그림은 칸 아래 미리보기로 보인다(261029-jipsa-23)
  // 서버가 runs/<실행>/answers/에 저장하고, 답을 넣으면 답 끝에 "[Image #N] 절대경로" 줄을 붙여 세션과 작업자가 그 경로로 그림을 연다
  // 표시 글자를 지우면 그 그림도 빠진다. 번호는 지워도 다시 쓰지 않아 앞에 붙인 그림과 헷갈리지 않는다
  const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"], IMAGE_MAX = 10 * 1024 * 1024;
  const pasted = { list: [], next: 1, busy: 0 };
  const imageTag = (n) => `[Image #${n}]`;
  const keptImages = (v) => pasted.list.filter((p) => v.includes(imageTag(p.n))).map((p) => ({ n: p.n, name: p.name }));
  function clearImages() { pasted.list = []; pasted.next = 1; drawImages(); }
  function drawImages() {
    const box = $("drImages"); box.textContent = ""; box.hidden = !pasted.list.length;
    for (const p of pasted.list) {
      const item = el("div", "pasted"), a = el("a"), img = el("img"), rm = el("button", null, T("지우기"));
      a.href = p.url; a.target = "_blank"; a.rel = "noopener"; a.title = T("새 탭에서 크게 본다"); img.src = p.url; img.alt = imageTag(p.n); a.appendChild(img);
      rm.type = "button"; rm.setAttribute("aria-label", T("{n} 지우기", { n: imageTag(p.n) }));
      rm.addEventListener("click", () => { // 칸의 표시 글자와 그림을 같이 지운다
        const t = $("drInput"); t.value = t.value.split(`${imageTag(p.n)} `).join("").split(imageTag(p.n)).join(""); // 붙일 때 넣은 표시 글자와 뒤 공백 하나만 지우고 나머지 글은 그대로 둔다
        pasted.list = pasted.list.filter((x) => x !== p); drawImages(); fitAnswer(); t.dispatchEvent(new Event("input")); t.focus();
      });
      item.append(a, el("span", "tag", imageTag(p.n)), rm); box.appendChild(item);
    }
  }
  function syncImages() { // 칸에서 표시 글자를 지운 그림은 미리보기에서도 뺀다
    const v = $("drInput").value, keep = pasted.list.filter((p) => v.includes(imageTag(p.n)));
    if (keep.length !== pasted.list.length) { pasted.list = keep; drawImages(); }
  }
  // 그림 하나를 확인하고 올린 뒤 커서 자리에 표시 글자를 넣는다. 서버는 머리 서명만 보므로 브라우저가 먼저 그림으로 해독해 보고 실패하면 올리지 않는다
  async function attachImage(blob) {
    const note = $("drAnswerNote"), runId = state.open;
    if (!IMAGE_TYPES.includes(blob.type)) { note.textContent = T("{t}은 붙이지 않는다. PNG, JPEG, GIF, WebP만 받는다", { t: blob.type || T("알 수 없는 형식") }); return false; }
    if (blob.size > IMAGE_MAX) { note.textContent = T("그림이 {n}MB다. 10MB 이하만 붙인다", { n: (blob.size / 1048576).toFixed(1) }); return false; }
    try { const bm = await createImageBitmap(blob); bm.close(); }
    catch (e) { note.textContent = T("그림으로 읽히지 않아 올리지 않았다"); return false; }
    const t = $("drInput"), at = [t.selectionStart, t.selectionEnd];
    pasted.busy += 1; note.textContent = T("그림을 올리는 중");
    try {
      const r = await fetch(`/api/answer_image?run=${encodeURIComponent(runId)}`, { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
      const d = await r.json();
      if (!d.ok) { note.textContent = T("그림을 올리지 못했다: {w}", { w: d.why || "" }); return false; }
      if (state.open !== runId) return false; // 올리는 사이 다른 결과지를 열었다
      const n = pasted.next++; pasted.list.push({ n, name: d.name, url: d.url });
      const before = t.value.slice(0, at[0]), pad = before && !/\s$/.test(before) ? " " : "";
      t.setRangeText(`${pad}${imageTag(n)} `, at[0], at[1], "end");
      drawImages(); fitAnswer(); t.dispatchEvent(new Event("input")); t.focus();
      note.textContent = T("{n}를 붙였다. 답을 넣으면 저장 경로가 답 끝에 붙는다", { n: imageTag(n) });
      return true;
    } catch (e) { note.textContent = T("그림을 올리지 못했다: 서버에 닿지 않는다"); return false; }
    finally { pasted.busy -= 1; }
  }
  function wireImagePaste() {
    const t = $("drInput");
    t.addEventListener("paste", async (ev) => { // Ctrl+V. 그림이 없으면 글자 붙여넣기는 브라우저에 맡긴다
      const files = [...(ev.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
      if (!files.length) return;
      ev.preventDefault();
      for (const f of files) await attachImage(f);
    });
    // Alt+V는 Claude Code CLI의 Windows 그림 붙이기 키다. Alt+C도 같은 일을 한다. 한글 입력 상태에서도 잡히게 글자 대신 키 자리(code)로 본다
    t.addEventListener("keydown", async (ev) => {
      if (!ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey || !["KeyV", "KeyC"].includes(ev.code)) return;
      ev.preventDefault();
      const note = $("drAnswerNote");
      if (!navigator.clipboard?.read) { note.textContent = T("이 브라우저는 클립보드 읽기를 지원하지 않는다. Ctrl+V로 붙인다"); return; }
      let items;
      try { items = await navigator.clipboard.read(); }
      catch (e) { note.textContent = T("클립보드 읽기가 막혀 있다. 주소창 왼쪽의 사이트 설정에서 클립보드를 허용하거나 Ctrl+V로 붙인다"); return; }
      const types = items.map((it) => [it, it.types.find((x) => x.startsWith("image/"))]).filter(([, type]) => type);
      if (!types.length) { note.textContent = T("클립보드에 그림이 없다"); return; }
      for (const [it, type] of types) await attachImage(await it.getType(type));
    });
  }
  wireImagePaste();
  async function sendAnswer(runId, text, images) {
    const note = $("drAnswerNote"); note.textContent = T("보내는 중");
    try {
      const r = await fetch("/api/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, answer: text, images: images || [] }) });
      const d = await r.json();
      // 세션으로 가는 답은 어디로 가는지 같이 보인다. 2분 안에 세션이 받지 않으면 스케줄러 작업자로 넘어간다(261103-jipsa-08)
      note.textContent = d.ok ? (d.resume ? T("답을 넣었다. 스케줄러가 다음 주기에 이어 돌린다") : T("답을 기록에 적었다. {d}", { d: d.delivery || "" })) : T("넣지 못했다: {w}", { w: d.why || "" });
      if (!d.ok) return;
      // 답을 넣으면 서버가 확인을 같이 적는다. 상태 전체를 다시 받는 데 10초쯤 걸리므로 돌려받은 확인 기록으로 먼저 상단, 막대, 서랍 머리를 바꾸고
      // 다 받은 뒤 서랍을 한 번 더 그린다. 옛 서버는 확인 기록을 돌려주지 않으므로 다 받은 뒤에야 바뀐다(261022-jipsa-59)
      $("drAnswer").hidden = true; $("drInput").value = ""; clearImages(); fitAnswer();
      if (d.confirm && state.data) { state.data.confirm = d.confirm; render(); }
      if (state.open === runId) openResult(runId, true);
      await refreshNow();
      if (state.open === runId) openResult(runId, true);
    } catch (e) { note.textContent = T("서버에 닿지 않는다"); }
  }
  // 이미 답이 들어간 결과지 맨 위의 표시. 물리기는 세션에서 jipsa answer --undo로 한다
  function drawAnswered(runId, a) {
    if (!a || !a.answer) return;
    const box = el("div", "confirm done"); box.id = "drAnswered";
    const urls = new Map((a.images || []).map((x) => [`[Image #${x.n}]`, x])), memo = el("div", "memo");
    const shown = urls.size ? a.answer.split("\n").filter((l) => !/^\[Image #\d+\] \S/.test(l.trim()) || !urls.has(l.trim().split("] ")[0] + "]")).join("\n").trim() : a.answer;
    memo.append(T("넣은 답{t}: ", { t: a.answered_at ? ` (${mdhm(parse(a.answered_at))})` : "" }));
    for (const part of shown.split(/(\[Image #\d+\])/)) { // 표시 글자는 그림을 여는 링크다. 경로는 마우스를 올리면 보인다
      const x = urls.get(part);
      if (!x) { memo.append(part); continue; }
      const link = el("a", "image-tag", part); link.href = x.url; link.target = "_blank"; link.rel = "noopener"; link.title = x.path; memo.appendChild(link);
    }
    box.appendChild(memo);
    // 그 답이 지금 어디에 있는지. 서버 기록에서 읽어 새로 고쳐도 같다. 아무도 받지 않은 답은 처리된 것처럼 읽히지 않게 강조한다(261103-jipsa-08)
    if (a.route) {
      const line = el("div", a.route.done ? "muted" : "route-open", a.route.text);
      if (a.route.run) { const go = el("a", "", T(" 결과지 열기")); go.href = "#"; go.addEventListener("click", (e) => { e.preventDefault(); openResult(a.route.run); }); line.appendChild(go); }
      box.appendChild(line);
    }
    box.appendChild(el("span", "muted", T("잘못 넣었으면 세션에서 jipsa answer {id} --undo로 물린다", { id: runId })));
    $("drBody").prepend(box);
  }
  // 서랍 머리 배지도 타임라인 막대와 같은 판정이다. 서버가 준 판정(confirm.shown)이 먼저고 없으면 화면의 같은 규칙(shownOf)이다.
  // 확인하지 않은 완료는 확인 필요, 실패는 확인 필요(실패), 답 없이 확인한 상태 값 확인 필요는 확인함, 확인된 것은 상태 값 그대로다
  function drawHeadStatus(runId, meta, shown) {
    const st = $("drStatus"); let cls = (meta.status || "").replace(" ", ""), text = stName(meta.status) || ""; // 모양은 상태 표기 한 벌의 CSS가 그린다(8안)
    const s = state.view === "live" && shown ? shown : shownOf(runId, meta.status, meta.finished);
    if (s === "확인 필요" && meta.status !== "확인 필요") { cls = "확인필요"; text = meta.status === "실패" ? T("확인 필요(실패)") : T("확인 필요"); }
    else if (s === "확인함") { cls = "완료"; text = T("확인함"); }
    st.className = `stpill ${cls}`; st.textContent = text;
  }
  // 결과지 맨 아래의 확인 단추. 진행 중과 세션 기록에는 두지 않는다
  // 상태 값 확인 필요(옛 값 판단 대기)도 답 없이 확인하면 확인 필요에서 빠진다. 상태 값과 큐 보류는 그대로라 다시 돌지 않고 Auto 모드 상한에도 그대로 든다(261022-jipsa-51)
  function drawConfirm(runId, meta) {
    const old = $("drConfirm"); if (old) old.remove();
    const foot = $("drFoot"); foot.hidden = true;
    const hold = ["확인 필요", "판단 대기"].includes(meta.status);
    if (state.view !== "live" || !conf() || !(hold || ["완료", "실패"].includes(meta.status)) || (runId || "").startsWith("session-") || (hold && answeredOf(state.data).has(runId))) return; // 큐에 답이 들어가 처리 대기인 실행은 확인할 것이 없다
    const a = ackState(runId, meta.status, meta.finished);
    const done = !a; // 기준 시각 전에 끝난 완료와 실패는 확인된 것이다. 상태 값 확인 필요는 확인을 눌러야 빠진다
    const box = el("div", `confirm${done ? " done" : ""}`); box.id = "drConfirm";
    foot.hidden = false; foot.className = `drawer-foot${done ? " done" : ""}`; // 바닥 고정 줄(42 초안 구역 17). 본문이 길어도 첫 화면에 보인다
    const btn = (text, cls, fn) => { const b = el("button", cls, text); b.type = "button"; b.addEventListener("click", fn); return b; };
    const row = el("div", "row"), note = el("span", "muted");
    if (meta.confirmed_from) box.appendChild(el("div", "memo", T("{s}였으나 확인해 완료로 처리 ({t})", { s: stName(meta.confirmed_from), t: mdhm(parse(meta.confirmed_at)) }))); // 원래 사유는 결과지에 그대로 있다
    if (hold && done) box.appendChild(el("div", "memo", T("답 없이 확인함. 상태 값과 큐 보류는 그대로라 다시 돌지 않는다. 되돌리면 답 칸이 다시 열린다"))); // 머리 배지도 확인함이다(261025-jipsa-04)
    if (done) row.appendChild(btn(T("확인 필요로 되돌리기"), "small", () => sendConfirm(runId, "reset", "", note)));
    else {
      row.appendChild(btn(hold ? T("답 없이 확인") : T("확인"), "primary", () => {
        // 끝난 실행의 확인은 답 칸에 글이 있으면 확인만 적어 글을 버리지 않고 답 넣기와 같은 확정 창을 거쳐 답으로 넣는다. 답이 들어가면 서버가 확인도 같이 적는다(261029-jipsa-45)
        // 상태 값 확인 필요의 "답 없이 확인"은 이름대로 답 없이 확인한다
        if (!hold && !$("drAnswer").hidden && $("drInput").value.trim()) { $("drForm").requestSubmit(); return; }
        sendConfirm(runId, "ack", "", note);
      }));
      if (hold) note.textContent = T("확인하면 답 칸이 닫히고 확인 필요에서 빠진다. 상태와 큐 보류는 그대로라 다시 돌지 않는다");
    }
    box.appendChild(row); box.appendChild(note); foot.appendChild(box);
  }
  async function sendConfirm(runId, action, memo, note) {
    note.textContent = T("보내는 중");
    try {
      const r = await fetch("/api/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, action, memo }) });
      const d = await r.json();
      if (!d.ok) { note.textContent = T("적지 못했다: {w}", { w: d.why || "" }); return; }
      state.data.confirm = d.confirm; render();
      if (state.open === runId) openResult(runId, true);
      refreshNow(); // 실패가 완료로 바뀌거나 돌아오므로 실행 상태를 서버에서 다시 받는다
    } catch (e) { note.textContent = T("서버에 닿지 않는다. 대시보드 서버를 다시 켜야 할 수 있다"); }
  }
  function closeResult() { state.open = null; $("drawer").hidden = true; $("scrim").hidden = true; clearTimeout(state.drawerTimer); }
  $("drClose").addEventListener("click", closeResult); $("scrim").addEventListener("click", closeResult);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("drawer").hidden) closeResult(); });

  // ----- 보고 -----
  async function openReport() {
    const d0 = new Date(); const date = state.view === "live" ? `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, "0")}-${String(d0.getDate()).padStart(2, "0")}` : (state.data?.date || "");
    state.open = `report:${date}`;
    $("drawer").hidden = false; $("scrim").hidden = false; $("drAnswer").hidden = true; $("drFoot").hidden = true; $("drFoot").textContent = "";
    $("drName").textContent = T("보고 {d}", { d: date }); fitName(""); $("drStatus").textContent = ""; $("drStatus").className = "stpill"; $("drMeta").textContent = ""; $("drBody").textContent = T("불러오는 중");
    $("drRaw").href = `/api/report?date=${encodeURIComponent(date)}`; $("drRawLine").hidden = false; setPreview("");
    try { const r = await fetch(`/api/report?date=${encodeURIComponent(date)}`); const d = await r.json(); renderMd(d.text || "", $("drBody")); foldReport($("drBody")); }
    catch (e) { $("drBody").textContent = T("보고를 불러오지 못했다"); }
  }
  // 하루 보고의 항목 줄(프로젝트 | 지시 | 결과 | 커밋이나 바뀐 파일 | 분)은 프로젝트, 결과, 분만 보이고 지시문 전문과 아래 분석, 주체, 토큰 줄은 자세히로 접는다(42 초안 우선순위 6)
  function foldReport(host) {
    for (const li of host.querySelectorAll(":scope > ul > li")) {
      const sub = li.querySelector(":scope > ul");
      const text = [...li.childNodes].filter((n) => n !== sub).map((n) => n.textContent).join("").trim();
      const parts = text.split(" | ").map((s) => s.trim());
      if (parts.length < 3) continue; // 없음, 안내 줄 등은 그대로 둔다
      const [pj, title, result, ...tail] = parts;
      const mn = tail.length && /^\d+분$/.test(tail[tail.length - 1]) ? tail.pop() : "";
      li.textContent = ""; li.className = "day";
      const l1 = el("div", "l1"); l1.appendChild(el("span", "pj", pname(pj))); l1.appendChild(el("span", "rs", result)); if (mn) l1.appendChild(el("span", "mn", mn)); li.appendChild(l1);
      const det = el("details"); det.appendChild(el("summary", null, T("자세히")));
      det.appendChild(el("p", null, T("지시: {t}", { t: title }))); if (tail.length) det.appendChild(el("p", null, tail.join(", ")));
      if (sub) det.appendChild(sub);
      li.appendChild(det);
    }
  }
  $("reportBtn").addEventListener("click", openReport);
  $("reportBtn2").addEventListener("click", () => { setMenu(false); openReport(); }); // 폰의 설정 메뉴 안
  $("reportBtn3").addEventListener("click", openReport); // 현황판 오늘 끝난 일 표의 전체 보기

  // 마감 전 Sol 공격 요약(meta.attack). 툴팁은 전체, 막대 위 표시는 '공격 3, 반영 2, 사람 1'이다(261024-jipsa-11)
  function atkShort(r) {
    const a = r && r.attack; if (!a) return "";
    return a.state === "있음" ? T("공격 {n}, 반영 {a}, 사람 {h}", { n: a.n, a: a.applied, h: a.human }) : T("공격 없음");
  }
  function atkText(r) {
    const a = r && r.attack; if (!a) return "";
    return a.state === "있음" ? T("판정 {v}, {s}", { v: a.verdict, s: atkShort(r) }) + (a.rebut ? T(", 반박 {n}", { n: a.rebut }) : "") + (a.unanswered ? T(", 답 없음 {n}", { n: a.unanswered }) : "") : T("공격 없음({w})", { w: a.why || T("사유 없음") });
  }
  // ----- 작은 마크다운 그리기. 글자는 모두 textContent로 넣는다 -----
  function renderMd(text, host, base) {
    host.textContent = "";
    const src = (s) => (/^(https?:|data:|\/)/.test(s) ? s : (base || "") + s);
    const lines = text.replace(/\r/g, "").split("\n");
    let i = 0, para = [], listStack = [];
    const flushPara = () => { if (para.length) { const txt = para.join(" "); const p = el("p", /^\*\*[^*]+\.\*\*/.test(txt) ? "lead" : null); inline(txt, p); host.appendChild(p); para = []; } };
    const closeLists = (depth) => { while (listStack.length > depth) listStack.pop(); };
    while (i < lines.length) {
      const line = lines[i];
      if (/^<details>\s*$/.test(line)) { // 결과지 보고서 아래 접힌 Sol 공격과 답 표(261024-jipsa-11)
        flushPara(); closeLists(0);
        const buf = []; let sum = ""; i++;
        while (i < lines.length && !/^<\/details>\s*$/.test(lines[i])) { const s = /^<summary>(.*)<\/summary>\s*$/.exec(lines[i]); if (s && !sum) sum = s[1]; else buf.push(lines[i]); i++; }
        i++;
        const d = el("details", "fold"); d.appendChild(el("summary", null, sum || T("펼치기"))); const inner = el("div"); renderMd(buf.join("\n"), inner, base); d.appendChild(inner); host.appendChild(d); continue;
      }
      if (/^```/.test(line)) {
        flushPara(); closeLists(0);
        const lang = line.replace(/^```/, "").trim();
        const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        if (["요약", "용어", "핵심"].includes(lang)) { // 보고서의 요약 상자
          const box = el("aside", "box"); box.appendChild(el("div", "label", T(lang)));
          for (const l of buf) if (l.trim()) { const p = el("p"); inline(l, p); box.appendChild(p); }
          host.appendChild(box); continue;
        }
        const pre = el("pre"); pre.appendChild(el("code", null, buf.join("\n"))); host.appendChild(pre); continue;
      }
      const img = /^!\[(.*?)\]\((.*?)\)\s*$/.exec(line);
      if (img) {
        flushPara(); closeLists(0);
        const fig = el("figure"); const im = el("img"); im.src = src(img[2]); im.alt = img[1]; im.loading = "lazy";
        const link = el("a"); link.href = im.src; link.target = "_blank"; link.rel = "noopener"; link.title = T("원본 크기로 열기"); link.appendChild(im); fig.appendChild(link); // 서랍이 좁아도 원본은 새 탭에서 본다
        if (img[1]) fig.appendChild(el("figcaption", null, img[1]));
        host.appendChild(fig); i++; continue;
      }
      const cap = /^\{caption="(.*?)".*\}\s*$/.exec(line);
      if (cap) { flushPara(); closeLists(0); const c = el("div", "caption"); inline(cap[1], c); host.appendChild(c); i++; continue; }
      if (/^>\s?/.test(line)) { flushPara(); closeLists(0); const q = el("blockquote"); inline(line.replace(/^>\s?/, ""), q); host.appendChild(q); i++; continue; }
      const h = /^(#{1,3})\s+(.*)$/.exec(line);
      if (h) { flushPara(); closeLists(0); const e = el(`h${h[1].length}`); inline(h[2], e); host.appendChild(e); i++; continue; }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flushPara(); closeLists(0);
        const rows = []; while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
        const table = el("table"); let head = true;
        for (const r of rows) {
          if (/^\s*\|[\s:|-]+\|\s*$/.test(r)) { head = false; continue; }
          const cells = r.trim().slice(1, -1).split("|");
          const tr = el("tr"); for (const c of cells) { const cell = el(head ? "th" : "td"); inline(c.trim(), cell); tr.appendChild(cell); } table.appendChild(tr);
          if (head) head = false;
        }
        host.appendChild(table); continue;
      }
      const li = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(line);
      if (li) {
        flushPara();
        const depth = Math.floor(li[1].replace(/\t/g, "  ").length / 2) + 1;
        const ordered = /\d/.test(li[2]);
        while (listStack.length > depth) listStack.pop();
        while (listStack.length < depth) {
          const parent = listStack.length ? listStack[listStack.length - 1].lastElementChild || listStack[listStack.length - 1] : host;
          const l = el(ordered ? "ol" : "ul"); parent.appendChild(l); listStack.push(l);
        }
        const item = el("li"); inline(li[3], item); listStack[listStack.length - 1].appendChild(item); i++; continue;
      }
      if (!line.trim()) { flushPara(); closeLists(0); i++; continue; }
      if (listStack.length && /^\s{2,}/.test(line)) { const last = listStack[listStack.length - 1].lastElementChild; if (last) { last.appendChild(document.createTextNode(" ")); inline(line.trim(), last); i++; continue; } }
      closeLists(0); para.push(line.trim()); i++;
    }
    flushPara();
  }
  function inline(text, host) {
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|https?:\/\/[^\s)<>]+)/g; // 맨 주소도 링크로 건다(수집 메모의 출처)
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) host.appendChild(document.createTextNode(text.slice(last, m.index)));
      const tok = m[0];
      if (tok.startsWith("**")) host.appendChild(el("strong", null, tok.slice(2, -2)));
      else if (tok.startsWith("`")) host.appendChild(el("code", null, tok.slice(1, -1)));
      else if (tok.startsWith("http")) { const a = el("a", null, tok); a.href = tok; a.target = "_blank"; a.rel = "noopener"; host.appendChild(a); }
      else { const a = el("a", null, tok.slice(1, tok.indexOf("]"))); a.href = m[2]; a.target = "_blank"; a.rel = "noopener"; host.appendChild(a); }
      last = m.index + tok.length;
    }
    if (last < text.length) host.appendChild(document.createTextNode(text.slice(last)));
  }

  // ----- 현황판(261023-jipsa-37 1안): 프로젝트마다 카드 하나와 맨 위 지금 볼 것 한 줄 -----
  const ago = (iso) => {
    const t = parse(iso); if (!t) return "";
    const m = Math.max(0, Math.round(((parse(state.data?.now) || new Date()) - t) / 60000));
    return m < 60 ? T("{n}분 전", { n: m }) : m < 1440 ? T("{n}시간 전", { n: Math.floor(m / 60) }) : T("{n}일 전", { n: Math.floor(m / 1440) });
  };
  // 상태 기호: 모양과 색을 같이 쓴다. 진행 중 원, 확인 필요 마름모, 실패 네모, 쉬는 중 빈 원
  const stChip = (cls, text) => { const s = el("span", `st ${cls}`); s.appendChild(el("i")); s.appendChild(document.createTextNode(text)); return s; };
  const cueCls = (kind) => (kind === "실패" ? "fail" : "cue");
  const cueAct = (kind) => (kind === "실패" ? T("다시 보기") : kind === "답 대기" || kind === "종합 보고" ? T("답 넣기") : T("결과지"));
  const clickable = (node, fn) => {
    node.tabIndex = 0; node.setAttribute("role", "button");
    node.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); });
    node.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); } });
    return node;
  };
  function boardSpark(c) {
    const W = 150, H = 44, P = 6;
    const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "pspark", role: "img", "aria-label": T("Cycle별 다시 잰 값과 목표선") });
    // 시작값, Cycle별 다시 잰 값과 95% 구간, 목표선이다(6안). 채택은 채운 점, 버림은 속이 빈 점, 목표에 닿은 점은 초록이다
    const sp = scorePts(c);
    const pts = (sp.start != null ? [{ n: 0, s: sp.start, adopt: true, start: true }] : []).concat(sp.pts);
    if (!pts.length) { const t = svgEl("text", { x: 2, y: H / 2 + 4, class: "lb" }); t.textContent = T("지표 없음"); svg.appendChild(t); return svg; }
    const vals = pts.flatMap((p) => [p.s, p.low, p.high]).concat(c.target != null ? [c.target] : []).filter((v) => v != null);
    const pad = Math.max(1, (Math.max(...vals) - Math.min(...vals)) * 0.08), lo = Math.min(...vals) - pad, hi = Math.max(...vals) + pad;
    const maxN = Math.max(1, ...pts.map((p) => p.n));
    const x = (n) => P + (n * (W - 2 * P)) / maxN, y = (v) => H - 3 - ((v - lo) / (hi - lo)) * (H - 6);
    if (c.target != null) svg.appendChild(svgEl("line", { x1: 0, x2: W, y1: y(c.target), y2: y(c.target), class: "tg" }));
    for (const p of pts) if (p.low != null && p.high != null) svg.appendChild(svgEl("line", { x1: x(p.n), x2: x(p.n), y1: y(p.low), y2: y(p.high), class: "ci" }));
    svg.appendChild(svgEl("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${x(p.n).toFixed(1)},${y(p.s).toFixed(1)}`).join(" "), class: "ln" }));
    const hit = (v) => c.target != null && (c.direction === "이하" ? v <= c.target : v >= c.target);
    for (const p of pts) svg.appendChild(svgEl("circle", { cx: x(p.n).toFixed(1), cy: y(p.s).toFixed(1), r: 3, class: `pt${hit(p.s) ? " hit" : ""}${p.adopt ? "" : " drop"}` }));
    svg.appendChild(svgEl("title", {})).textContent = pts.map((p) => `${p.n ? `Cycle ${p.n}` : T("시작")} ${p.s}${p.low != null ? ` (${p.low}~${p.high})` : ""}${p.start ? "" : p.adopt ? T(" 채택") : T(" 버림")}`).join(", ") + (c.target != null ? T(", 목표 {t} {d}", { t: c.target, d: T(c.direction) }) : "");
    return svg;
  }
  const cycLive = (c) => !!(c.cycle && c.cycle.status !== "끝"); // 현황판 카드의 Cycle 목표가 아직 도는지
  // 카드의 단계 세 줄(261029-jipsa-47, 46 답): 지금 도는 서브에이전트 안의 단계다. 빨간 원 끝난 단계, 초록 원 지금 단계, 회색 원 다음 단계.
  // 단계 이름만 보이고 모르면 --다. 줄 오른쪽의 상대 시각(N분 전, N분째)은 261031-jipsa-09에서 사용자 지시로 뗐다. 진행 중 실행이 여럿이면 실행마다 세 줄 묶음이고, 묶음을 누르면 그 실행의 결과지가 열린다.
  // 묶음 윗줄(261031-jipsa-06, 05 답 2안): 묶음마다 상자이고 윗줄에 작은 상태 칩(서브에이전트, 작업자, 멈춤)과 제목 20자를 둔다.
  // 넓은 폭에서는 묶음이 가로로 나란히 놓여 카드가 짧다. 자른 제목 전체는 마우스 올림에 보인다.
  // 모르는 단계는 -- 점으로 그리지 않고 뺀다. 아는 단계가 하나도 없으면 안내 한 줄이다. 진행 중 실행이 없을 때의 빈 묶음은 그리지 않고 절의 안내 한 줄로 둔다(261102-jipsa-16)
  function stepLines(c) {
    const box = el("div", "sl");
    const group = (r) => {
      const s = r.steps || {}, g = el("div", "sg");
      const h = el("div", "sh");
      h.appendChild(stChip(r.stall_min > 0 ? "stop" : "run", r.stall_min > 0 ? T("멈춤") : r.executor === "subagent" ? T("서브에이전트") : T("작업자")));
      h.appendChild(el("span", "stt", r.title.length > 20 ? `${r.title.slice(0, 20)}…` : r.title));
      g.title = `${r.title}${r.stall_min > 0 ? T(" (멈춤 {n}분)", { n: r.stall_min }) : ""}`;
      g.appendChild(h);
      const ul = el("ul", "pl");
      const line = (cls, st) => {
        if (!st) return;
        const li = el("li", cls); li.appendChild(el("i", "dot"));
        li.appendChild(el("span", "tt", st.name)); li.title = T("{n}단계 {s}", { n: st.no, s: st.name }); ul.appendChild(li);
      };
      line("done", s.done);
      line("now", s.now);
      line("next", s.next);
      if (!ul.children.length) ul.appendChild(el("li", "none", T("단계 기록 아직 없음")));
      g.appendChild(ul);
      return g;
    };
    for (const r of c.running) box.appendChild(clickable(group(r), () => openResult(r.run_id)));
    return box;
  }
  // 카드 절 하나(261102-jipsa-16): 위 구분선, 이름 줄, 내용 순서다. 내용이 없으면 안내 한 줄만 둔다
  const cardSec = (cls, label, empty) => {
    const b = el("div", `psec ${cls}`); b.appendChild(el("div", "lbl", label));
    if (empty) b.appendChild(el("div", "muted pempty", empty));
    return b;
  };
  // 카드 절 순서는 상태와 무관하게 하나다(261102-jipsa-16): 머리 줄, Cycle 목표(있을 때만), 확인 필요(있을 때만), 최근 결과, 진행 중인 실행, 미병합 꼬리.
  // 최근 결과와 진행 중인 실행은 늘 그리고 비면 안내 한 줄이다. 옛 화면은 진행 중이 아닌 카드에만 목표 없음 절과 -- 점 세 줄을 그려 카드마다 구성이 달랐다.
  // 같은 행의 카드는 격자가 같은 높이로 늘이고 꼬리는 카드 바닥에 붙는다
  function boardCard(c, cues) {
    const n = cues.length, run = c.running.length;
    const card = el("article", `pc${n ? " cue" : run ? " run" : ""}`);
    const head = el("div", "ph"); head.appendChild(el("span", "pn", pname(c.name)));
    head.appendChild(n ? stChip("cue", T("확인 필요 {n}", { n })) : c.running.some((r) => r.stall_min > 0) ? stChip("stop", T("멈춤")) : run ? stChip("run", T("진행 중")) : cycLive(c) ? stChip("run", T("목표 진행")) : (c.recent || []).length ? ((c.recent || []).every((r) => r.status === "실패") ? stChip("fail", T("최근 실패")) : stChip("done", T("최근 완료"))) : stChip("todo", T("쉬는 중")));
    card.appendChild(head);
    if (c.cycle) { // Auto 절 Cycle 목표 하나. 옛 Auto 목표 큐 칸을 261026-jipsa-07에서 이것으로 바꿨다. 작은 그래프는 그 목표의 Cycle 값이다
      const cy = c.cycle, box = el("div", "psec pcyc");
      if (cy.rounds.length || cy.base != null) box.appendChild(boardSpark(cy)); // 잰 값이 없으면 그래프 자리를 비우지 않는다
      const t = el("div", "pcyc-t"); t.appendChild(el("div", "lbl", T("Cycle 목표")));
      t.appendChild(el("div", "cyc-t", cy.title.length > 18 ? `${cy.title.slice(0, 18)}…` : cy.title)); t.title = cy.title;
      t.appendChild(el("div", "mono cyc-s", `Cycle ${cy.rounds.length}${cy.pending ? T(", 목표 미정") : cy.target != null ? T(", 목표 {t} {d}", { t: cy.target, d: T(cy.direction) }) : ""}`));
      if (cy.pending) t.title = T("{t}. 목표 미정: {p}을 Cycle 1 분석이 정한다", { t: cy.title, p: cy.pending });
      if ((cy.branches || []).length) { // 아이디어 갈래 줄(261029-jipsa-10 1안). 열림과 닫힘 수, 지금 갈래, 툴팁에 갈래별 바퀴 수
        const bs = cy.branches, cnt = (s) => bs.filter((b) => b.status === s).length, last = [...cy.rounds].reverse().find((r) => r.branch);
        const bl = el("div", "mono cyc-s", T("갈래 열림 {o} 닫힘 {c}", { o: cnt("열림"), c: cnt("닫힘") }) + (cnt("사람 확인") ? T(" 사람 확인 {n}", { n: cnt("사람 확인") }) : "") + (last ? T(", 지금 [{b}]", { b: last.branch }) : ""));
        bl.title = bs.map((b) => `${b.name}: ${b.status}, ${b.rounds}바퀴, 연속 미개선 ${b.streak}${b.closed_at ? `, Cycle ${b.closed_at}에 닫힘` : ""}`).join("\n");
        t.appendChild(bl);
      }
      const st = el("div", "cyc-st"); st.appendChild(stChip(cycLive(c) ? "run" : "todo", cy.where || cy.status)); t.appendChild(st);
      box.appendChild(t);
      card.appendChild(box);
    }
    const ul = el("ul", "pl");
    for (const q of cues.slice(0, 2)) {
      const li = el("li", "q"); li.appendChild(stChip(cueCls(q.kind), stName(q.kind))); li.appendChild(el("span", "tt", q.title)); li.title = q.title;
      ul.appendChild(clickable(li, () => openResult(q.run_id)));
    }
    if (n > 2) { const li = el("li", "more"); li.appendChild(el("span", "tt", T("확인 필요 {n}건 더", { n: n - 2 }))); ul.appendChild(clickable(li, goCue)); }
    if (ul.children.length) { const box = cardSec("pcue", T("확인 필요")); box.appendChild(ul); card.appendChild(box); }
    // 최근 결과 줄(261031-jipsa-08): 24시간 안에 끝난 실행을 끝난 순으로 3건까지. 확인을 거친 완료는 확인 필요 목록에서 빠지고 카드에 자리가 없어
    // 답으로 낳은 초안이 어디에도 보이지 않았다. 다른 실행의 답으로 시작한 실행은 부모 바로 아래에 들여 쓴다. 누르면 결과지이고 마우스 올림에 제목과 넣은 답이다
    const rc = c.recent || [];
    if (!rc.length) card.appendChild(cardSec("prc", T("최근 결과"), T("24시간 안에 끝난 실행 없음")));
    else {
      const box = cardSec("prc", T("최근 결과"));
      const rl = el("ul", "pl");
      const all = state.rcOpen?.has(c.name); // 더 보기 줄을 누르면 그 카드만 전부 펼친다. 다음 상태 응답에도 남는다
      for (const r of (all ? rc : rc.slice(0, 3))) {
        const li = el("li", `q rc${r.parent ? " child" : ""}`);
        li.appendChild(stChip(r.status === "실패" ? "fail" : "done", stName(r.status)));
        li.appendChild(el("span", "tt", r.label || r.title)); // 끝난 시각의 상대 표시는 뗐다(261031-jipsa-09)
        if (r.draft) li.appendChild(draftTag(r)); // 초안 실행은 제목 뒤에 초안 표식(261031-jipsa-10)
        li.title = `${r.title}${r.answer ? T("\n답 들어감: {a}", { a: r.answer }) : ""}${r.parent ? T("\n위 실행에 넣은 답으로 시작했다") : ""}`;
        rl.appendChild(clickable(li, () => openResult(r.run_id)));
      }
      if (rc.length > 3 && !all) { const li = el("li", "more"); li.appendChild(el("span", "tt", T("최근 결과 {n}건 더", { n: rc.length - 3 }))); li.title = T("누르면 전부 펼친다"); rl.appendChild(clickable(li, () => { (state.rcOpen ||= new Set()).add(c.name); drawBoard(state.data); })); }
      box.appendChild(rl); card.appendChild(box);
    }
    const rbox = cardSec("prun", T("진행 중인 실행"), run ? "" : T("진행 중인 실행 없음"));
    if (run) rbox.appendChild(stepLines(c));
    card.appendChild(rbox);
    // 숫자 4칸(진행 중, 확인 필요, 할 일, 미병합) 대신 미병합 한 줄이다(42 초안 우선순위 8, 11). 진행 중과 확인 필요는 머리 칩과 목록이 보이고 할 일은 TODO 탭에 있다
    const um = c.unmerged, ft = el("div", "pft"), umb = el("span", null, T("미병합 "));
    umb.appendChild(el("b", um >= 3 ? "v-warn" : "", um == null ? "-" : String(um)));
    umb.title = um == null ? T("저장소가 git이 아니거나 기본 브랜치가 없다") : T("main에 병합되지 않은 orch/ 브랜치 수. 5분마다 다시 센다");
    ft.appendChild(umb);
    if (c.todo_n) { const td = el("span", null, T("할 일 ")); td.appendChild(el("b", null, String(c.todo_n))); ft.appendChild(td); }
    card.appendChild(ft);
    return card;
  }
  // 확인 필요 띠(42 초안 구역 4, 261029-jipsa-43 1안): 1건 이상일 때만 보인다. 건수와 종류를 적고 멈춘 실행이 있으면 그것을 먼저 적는다.
  // 띠 아래에 항목마다 한 줄과 답 넣기 단추가 펼쳐진다(옛 확인 필요 탭의 목록). 0건이면 띠 자체가 없다(우선순위 4)
  function drawAttn(cue, cards) {
    const wrap = $("attnWrap"), box = $("attn"); box.textContent = "";
    const stalled = cards.flatMap((c) => c.running.filter((r) => r.stall_min > 0).map((r) => ({ ...r, project: c.name })));
    wrap.hidden = !cue.length && !stalled.length;
    if (wrap.hidden) { $("cueList").textContent = ""; return; }
    const n = (k) => cue.filter((q) => q.kind === k).length;
    const kinds = [["종합 보고", n("종합 보고")], ["답 대기", n("답 대기")], ["실패", n("실패")], ["확인 전 완료", n("확인 필요")]].filter(([, v]) => v).map(([k, v]) => `${T(k)} ${v}`).join(", ");
    const tt = el("span", "tt");
    if (cue.length) { tt.appendChild(el("b", null, T("확인 필요 {n}건", { n: cue.length }))); tt.append(` ${kinds}`); }
    if (stalled.length) {
      const r = stalled[0];
      tt.append((cue.length ? ". " : "") + T("{p} {t}, {n}분째 활동이 없다. 띄운 세션에 깨우라고 알렸다", { p: pname(r.project), t: r.title, n: r.stall_min }));
      const b = el("button", "acc", T("결과지 열기")); b.type = "button"; b.addEventListener("click", () => openResult(r.run_id)); box.appendChild(stChip("stop", T("멈춤"))); box.appendChild(tt); box.appendChild(b);
    } else { box.appendChild(stChip("cue", T("지금 볼 것"))); box.appendChild(tt); }
    drawCueQueue(cue);
  }
  function drawBoard(data) {
    const host = $("board"); host.textContent = "";
    $("boardPast").hidden = state.view === "live";
    if (state.view !== "live" || !data.board) { $("attnWrap").hidden = true; $("boardCols").hidden = true; return; }
    const cue = liveCue(), by = new Map();
    for (const q of cue) { if (!by.has(q.project)) by.set(q.project, []); by.get(q.project).push(q); }
    const cards = [...data.board.projects];
    for (const p of by.keys()) if (!cards.some((c) => c.name === p)) cards.push({ name: p, running: [], todo_n: 0, next: "", unmerged: null, cycle: null, last: null, recent: [] });
    // 확인 필요가 있는 카드를 앞에, 그다음 진행 중, 최근 결과 순이다
    cards.sort((a, b) => ((by.get(b.name) || []).length - (by.get(a.name) || []).length) || (b.running.length - a.running.length)
      || String(b.last?.finished || "").localeCompare(String(a.last?.finished || "")) || a.name.localeCompare(b.name));
    drawAttn(cue, cards);
    // 쉬는 중 카드(확인 필요도 진행 중도 도는 목표도 없는 프로젝트)는 카드 대신 아래 한 줄 표에 둔다(42 초안 우선순위 5). 카드 펼치기 단추는 뗐다
    const busy = (c) => (by.get(c.name) || []).length || c.running.length || cycLive(c) || (c.recent || []).length; // 24시간 안에 끝난 실행이 있는 프로젝트도 카드다(261031-jipsa-08)
    const rest = cards.filter((c) => !busy(c));
    for (const c of cards.filter(busy)) host.appendChild(boardCard(c, by.get(c.name) || []));
    $("boardCols").hidden = false;
    drawIdleTable(rest, data.board.idle || []);
    drawTodayTable(data.board.today || [], data.board.today_n || 0);
  }
  // 쉬는 프로젝트 한 줄 표(구역 6): 프로젝트, 최근 결과(누르면 결과지), 미병합, 언제. 최근 기록이 없는 프로젝트는 맨 아래 한 줄에 이름만 적는다
  function drawIdleTable(rest, idle) {
    const t = $("idleTable"); t.textContent = "";
    $("idleN").textContent = T("{n}개", { n: rest.length + idle.length });
    const sorted = [...rest].sort((a, b) => String(b.last?.finished || "").localeCompare(String(a.last?.finished || "")));
    for (const c of sorted) {
      const tr = el("tr"); tr.appendChild(el("td", "p", pname(c.name)));
      const lb = el("td", `lb${c.last && c.last.status === "실패" ? " fail" : ""}`, c.last ? (c.last.label || c.last.title) : T("최근 기록 없음"));
      if (c.last) { lb.title = c.last.title; clickable(lb, () => openResult(c.last.run_id)); } else lb.className = "note";
      tr.appendChild(lb);
      tr.appendChild(el("td", "n", c.unmerged == null ? "" : T("미병합 {n}", { n: c.unmerged })));
      tr.appendChild(el("td", "t", c.last ? ago(c.last.finished) : ""));
      t.appendChild(tr);
    }
    if (idle.length) { const tr = el("tr"), td = el("td", "note", T("{p}은 최근 기록이 없다", { p: idle.map(pname).join(", ") })); td.colSpan = 4; tr.appendChild(td); t.appendChild(tr); }
    if (!sorted.length && !idle.length) { const tr = el("tr"), td = el("td", "note", T("모든 프로젝트가 돌고 있다")); td.colSpan = 4; tr.appendChild(td); t.appendChild(tr); }
  }
  // 오늘 끝난 일 최근 5건(구역 7): 시각, 프로젝트, 결과 이름(누르면 결과지), 요약 한 줄. 전체는 오늘 보고에서 본다
  function drawTodayTable(rows, total) {
    const t = $("todayTable"); t.textContent = "";
    $("todayN").textContent = total ? T("{n}건, 최근 {m}건", { n: total, m: Math.min(5, rows.length) }) : "";
    $("todayEmpty").hidden = rows.length > 0;
    for (const r of rows) {
      const tr = el("tr"); tr.appendChild(el("td", "tm", hhmm(parse(r.finished)))); tr.appendChild(el("td", "p", pname(r.project)));
      const lb = el("td", `lb${r.status === "실패" ? " fail" : ""}`, r.label || r.title); lb.title = r.title; clickable(lb, () => openResult(r.run_id)); tr.appendChild(lb);
      if (r.draft) lb.insertBefore(draftTag(r), lb.firstChild); // 초안 실행은 결과 이름 앞에 초안 표식. 칸이 한 줄로 잘려 뒤에 두면 가려진다(261031-jipsa-10)
      const sm = el("td", "sm", r.summary || ""); sm.title = r.summary || ""; tr.appendChild(sm);
      t.appendChild(tr);
    }
  }

  // ----- 확인 필요 목록(3안, 44에서 현황판 띠 아래로): 답하기 단추가 붙은 한 줄씩의 큐 -----
  function queueRow(kind, cls, project, title, sub, when, act, runId) {
    const li = el("li"); li.appendChild(stChip(cls, stName(kind))); li.appendChild(el("span", "mono pj", pname(project)));
    const t = el("span", "tt"); t.appendChild(document.createTextNode(title)); if (sub) t.appendChild(el("span", "tsub", sub)); t.title = title; li.appendChild(t);
    li.appendChild(el("span", "muted mono when", when));
    const b = el("button", kind === "실패" ? "" : "acc", act); b.type = "button"; b.addEventListener("click", (ev) => { ev.stopPropagation(); openResult(runId); }); li.appendChild(b);
    li.addEventListener("click", () => openResult(runId));
    return li;
  }
  function drawCueQueue(cue) {
    const list = $("cueList"); list.textContent = ""; list.hidden = !cue.length;
    for (const q of cue) list.appendChild(queueRow(q.kind, cueCls(q.kind), q.project, q.title, q.label && q.label !== q.title ? q.label : "", q.finished ? ago(q.finished) : "", cueAct(q.kind), q.run_id));
  }

  // ----- 탭(2안): 현황판, 타임라인, 확인 필요, TODO. 주소 해시(#board 등)로 기억하고 탭마다 그 탭 값만 받는다 -----
  // 환경 탭은 머리 줄 한 줄 현황으로 옮기고 없앴다(261023-jipsa-41). 옛 #env 주소는 현황판으로 간다
  // 확인 필요 탭은 현황판 띠 아래 목록으로 옮기고 없앴다(261029-jipsa-43 1안). 옛 #cue 주소는 현황판으로 간다
  const TABS = ["board", "timeline", "todo"], OLD_TABS = ["cue", "env"];
  const tabOfHash = () => { const h = (location.hash || "").replace(/^#/, "").split("&")[0]; return TABS.includes(h) ? h : "board"; };
  function showTab() {
    for (const t of TABS) {
      const on = t === state.tab, b = $(`tab-${t}`);
      $(`pane-${t}`).hidden = !on; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1;
    }
  }
  function setTab(tab, opts = {}) {
    if (!TABS.includes(tab)) tab = "board";
    if (state.view !== "live" && tab !== "timeline") { state.tab = tab; showTab(); switchView("live"); return; } // 지난 날짜는 타임라인에만 있다. 다른 탭을 누르면 실시간으로 돌아간다
    const changed = tab !== state.tab; state.tab = tab; showTab();
    const rest = (location.hash || "").replace(/^#/, "").split("&").filter((p) => p && !TABS.includes(p) && !OLD_TABS.includes(p));
    const h = `#${[tab, ...rest].join("&")}`;
    if (location.hash !== h) history.replaceState(null, "", h);
    render();
    if (changed && !opts.noFetch) refreshNow();
  }
  for (const t of TABS) $(`tab-${t}`).addEventListener("click", () => setTab(t));
  $("tabs").addEventListener("keydown", (ev) => { // 화살표로 탭을 옮긴다
    const i = TABS.indexOf(state.tab), d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
    if (!d) return; ev.preventDefault(); const t = TABS[(i + d + TABS.length) % TABS.length]; setTab(t); $(`tab-${t}`).focus();
  });
  window.addEventListener("hashchange", () => { const t = tabOfHash(); if (t !== state.tab) setTab(t); });

  // ----- 그리기 -----
  // 다시 그려도 스크롤 위치가 튀지 않게 창과 가로 스크롤 영역의 위치를 되돌린다
  function render() {
    const hosts = ["tl"].map($).concat([...document.querySelectorAll(".tablewrap")]);
    const saved = hosts.map((h) => [h, h.scrollLeft, h.scrollTop]), wy = window.scrollY, wx = window.scrollX;
    try { draw(); } finally {
      for (const [h, l, t] of saved) { h.scrollLeft = l; h.scrollTop = t; }
      if (window.scrollY !== wy || window.scrollX !== wx) window.scrollTo(wx, wy);
    }
  }
  // 머리와 지금 탭만 그린다. 다른 탭의 값은 그 탭을 열 때 받는다
  function draw() {
    const data = state.data; if (!data) return;
    const vnow = state.view === "live" ? parse(data.now) : state.vnow;
    const cutoff = data.cutoff ? parse(data.cutoff) : null;
    const nightStart = state.view === "live" ? null : (cutoff ? new Date(cutoff.getTime() - 8.5 * 3600000) : null);
    drawTop(data, vnow);
    const tab = state.tab;
    if (tab === "board") drawBoard(data);
    if (tab === "timeline" && data.runs) {
      drawTimeline(data.runs, vnow, cutoff, nightStart);
      drawGoals(state.view === "live" && data.scope ? data.scope.cycles || [] : []);
    }
    if (tab === "todo" && data.todofile) drawTodoFile(data.todofile);
    if (tab === "todo" && data.todofile) drawMemo(data.todofile); // 주간 계획 항목 표는 메모 칸으로 갈음했다(261025-jipsa-36)
    if (state.view !== "live") $("vnow").textContent = `${vnow.getMonth() + 1}/${vnow.getDate()} ${hhmm(vnow)}`;
  }

  async function pollLive() {
    try {
      // 지금 탭의 값과 머리만 받는다. 받은 값은 앞서 받은 다른 탭 값 위에 덮어 탭을 옮겨도 다음 응답 전까지 옛 값으로 그린다
      const tab = state.tab, gen = tfGen;
      const r = await fetch(`/api/state?tab=${encodeURIComponent(tab)}`); const data = await r.json();
      if (gen !== tfGen) { delete data.todofile; delete data.todo_file_n; } // 받는 사이 TODO 명령이 돌았다. 명령 응답의 칸 줄을 지킨다(261025-jipsa-48)
      if (state.server && data.server && data.server !== state.server) { location.reload(); return; } // 서버가 새로 떴으면 화면도 새로 받는다
      // 화면 파일만 고친 경우에도 새로 받는다. 옛 화면 코드가 남아 확인 전 결과를 완료로 보이던 일이 있었다(261022-jipsa-57). 답을 쓰는 중이면 다음 주기로 미룬다
      if (state.web && data.web && data.web !== state.web && !$("drInput").value.trim()) { location.reload(); return; }
      state.server = data.server || state.server; state.web = state.web || data.web;
      if (state.view !== "live") return; // 받는 사이 지난 날짜로 옮겼다
      state.data = { ...(state.data && !state.data.date ? state.data : {}), ...data }; render();
      if (data.confirm && !state.moved) { state.moved = true; moveLocalRead(data.confirm); }
    } catch (e) { $("mode").textContent = T("서버에 닿지 않는다"); }
    clearTimeout(state.pollTimer);
    if (state.view === "live" && state.pollSec > 0) state.pollTimer = setTimeout(pollLive, state.pollSec * 1000);
  }
  // 화면 모드(261102-jipsa-41). 첫 칠 전 적용은 index.html 머리에서 하고, 여기서는 위 줄 전환 버튼과 다른 탭의 변경만 맞춘다. 색은 모두 CSS 토큰이라 다시 그릴 것이 없다
  const THEME_KEY = "jipsa.theme";
  const setTheme = (t) => {
    document.documentElement.setAttribute("data-theme", t);
    themeWant = t;
    const b = $("themeBtn"), now = t === "dark" ? "dark" : "white", next = t === "dark" ? "white" : "dark", say = T("화면 모드 {now}. 누르면 {next}로 바뀐다", { now, next });
    b.textContent = now; b.title = say; b.setAttribute("aria-label", say);
  };
  let themeWant = null, themeTimer = null;
  setTheme(document.documentElement.getAttribute("data-theme") || window.THEME_DEFAULT);
  $("themeBtn").addEventListener("click", () => {
    const t = themeWant === "dark" ? "light" : "dark", b = $("themeBtn");
    themeWant = t;
    try { localStorage.setItem(THEME_KEY, t); } catch (err) { /* 저장 못 해도 이 화면은 바뀐다 */ }
    clearTimeout(themeTimer);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setTheme(t); return; }
    b.classList.remove("flipping"); void b.offsetWidth; b.classList.add("flipping");
    themeTimer = setTimeout(() => setTheme(themeWant), 100); // 효과 0.2초의 가운데, 버튼이 옆면일 때 바꾼다
  });
  $("themeBtn").addEventListener("animationend", () => $("themeBtn").classList.remove("flipping"));
  window.addEventListener("storage", (e) => { if (e.key === THEME_KEY) { clearTimeout(themeTimer); setTheme(e.newValue === "dark" || e.newValue === "light" ? e.newValue : window.THEME_DEFAULT); } });
  // 화면 언어(261103-misc-14). 화면 모드와 같은 방식이다. 첫 그리기 전 적용은 index.html 머리에서 하고, 여기서는 KOR/ENG 단추와 다른 탭의 변경을 맞춘 뒤 화면을 다시 그린다
  const LANG_KEY = "jipsa.lang";
  const setLang = (l, redraw) => {
    document.documentElement.setAttribute("lang", l);
    const b = $("langBtn"), now = l === "en" ? "ENG" : "KOR", next = l === "en" ? "KOR" : "ENG", say = T("화면 언어 {now}. 누르면 {next}로 바뀐다", { now, next });
    b.textContent = now; b.dataset.lang = l; b.title = say; b.setAttribute("aria-label", say);
    window.applyStatic();
    $("drLangNote").hidden = l !== "en";
    if (!redraw) return;
    setTheme(themeWant || document.documentElement.getAttribute("data-theme") || window.THEME_DEFAULT); // 화면 모드 단추의 툴팁도 언어를 따른다
    tfTodoSig = ""; tfBandSig = ""; memoSig = ""; tfPlaceSig = ""; // 같은 값이면 다시 그리지 않는 칸도 글자를 바꾼다
    render();
    if (state.open && !$("drawer").hidden) { if (String(state.open).startsWith("report:")) openReport(); else openResult(state.open, true); }
  };
  setLang(document.documentElement.getAttribute("lang") === "en" ? "en" : "ko", false);
  $("langBtn").addEventListener("click", () => {
    const l = document.documentElement.getAttribute("lang") === "en" ? "ko" : "en";
    try { localStorage.setItem(LANG_KEY, l); } catch (err) { /* 저장 못 해도 이 화면은 바뀐다 */ }
    if (/[?&]lang=/.test(location.search)) history.replaceState(null, "", location.pathname + location.search.replace(/([?&])lang=[^&]*&?/, "$1").replace(/[?&]$/, "") + location.hash); // 주소의 언어가 단추보다 앞서지 않게 뗀다
    setLang(l, true);
  });
  window.addEventListener("storage", (e) => { if (e.key === LANG_KEY) setLang(e.newValue === "en" || e.newValue === "ko" ? e.newValue : window.LANG_DEFAULT, true); });
  // 주기는 5, 15, 30, 60초와 멈춤이다. 고른 값은 브라우저에 기억한다. 멈춤이어도 조작 뒤에는 한 번 새로 받는다
  try { const v = localStorage.getItem("jipsa.pollSec"); if (v !== null && [...$("pollSel").options].some((o) => o.value === v)) state.pollSec = +v; } catch (e) { /* 비공개 창 */ }
  $("pollSel").value = String(state.pollSec);
  $("pollSel").addEventListener("change", () => {
    state.pollSec = +$("pollSel").value;
    try { localStorage.setItem("jipsa.pollSec", String(state.pollSec)); } catch (e) { /* 저장 못 해도 된다 */ }
    clearTimeout(state.pollTimer); if (state.view === "live") pollLive();
  });
  const refreshNow = () => { if (state.view !== "live") return; clearTimeout(state.pollTimer); return pollLive(); };
  async function loadDay(date) {
    const r = await fetch(`/api/day?date=${encodeURIComponent(date)}`); const data = await r.json();
    state.data = data;
    const ts = (data.runs || []).flatMap((run) => run.events.map((e) => parse(e.ts).getTime()));
    if (data.cutoff) ts.push(parse(data.cutoff).getTime());
    state.tmin = ts.length ? Math.min(...ts) : Date.now(); state.tmax = ts.length ? Math.max(...ts) + 60000 : Date.now();
    $("scrub").value = 1000; state.vnow = new Date(state.tmax);
    $("replayNote").textContent = (data.runs || []).length ? T("작업 {n}개", { n: data.runs.length }) : T("그 날짜의 기록이 없다");
    render();
  }

  // ----- 조작 -----
  // 지난 날짜 선택과 실시간 단추, 큰 시계는 머리 줄에서 없앴다(261023-jipsa-42 사용자 지적). 지난 날짜 값(/api/day)은 서버에 남아 있다
  function switchView(v) {
    clearTimeout(state.pollTimer); stopPlay();
    $("pollSeg").hidden = v !== "live";
    state.view = v === "live" ? "live" : "day";
    $("replay").hidden = state.view === "live";
    if (state.view === "live") { if (state.data?.date) state.data = null; pollLive(); }
    else { if (state.tab !== "timeline") setTab("timeline", { noFetch: true }); loadDay(v); }
  }
  $("tlWindow").addEventListener("change", () => { try { localStorage.setItem("jipsa.tlWindow", $("tlWindow").value); } catch (e) { /* 저장 못 해도 된다 */ } render(); });
  try { const w = localStorage.getItem("jipsa.tlWindow"); if (w) $("tlWindow").value = w; } catch (e) { /* 비공개 창 */ }
  $("scrub").addEventListener("input", (e) => { stopPlay(); state.vnow = new Date(state.tmin + (state.tmax - state.tmin) * (e.target.value / 1000)); render(); });
  $("play").addEventListener("click", () => (state.playing ? stopPlay() : startPlay()));
  function startPlay() {
    state.playing = true; $("play").textContent = T("멈춤||play");
    if (+$("scrub").value >= 1000) { $("scrub").value = 0; state.vnow = new Date(state.tmin); }
    state.timer = setInterval(() => {
      const step = (+$("speed").value) * 1000 / 4;
      state.vnow = new Date(Math.min(state.tmax, state.vnow.getTime() + step));
      $("scrub").value = Math.round(((state.vnow.getTime() - state.tmin) / (state.tmax - state.tmin)) * 1000);
      render(); if (state.vnow.getTime() >= state.tmax) stopPlay();
    }, 250);
  }
  function stopPlay() { state.playing = false; $("play").textContent = T("재생"); clearInterval(state.timer); }
  window.addEventListener("resize", () => render());

  state.tab = tabOfHash(); showTab();
  if (!location.hash || /^#(env|cue)(&|$)/.test(location.hash)) history.replaceState(null, "", `#${[state.tab, ...(location.hash || "").replace(/^#/, "").split("&").filter((p) => p && !OLD_TABS.includes(p))].join("&")}`);
  pollLive();
  // 주소의 결과지는 첫 상태를 받은 뒤 연다. 먼저 열면 확인 상태가 없어 확인 단추와 답 칸 판정이 빠진다
  const hash = /run=([^&]+)/.exec(location.hash || "");
  if (hash) (async () => { for (let i = 0; i < 300 && !state.data; i++) await new Promise((r) => setTimeout(r, 100)); openResult(decodeURIComponent(hash[1])); })();
})();
