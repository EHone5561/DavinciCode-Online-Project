# -*- coding: utf-8 -*-
"""다시하기(재시작) 로직 테스트.

게임을 실제로 끝까지 돌리지 않고 **재시작 결정 로직만** 검증한다
(게임 진행은 이미 다른 테스트가 덮는다).

검증
----
  1) protocol — RESTART / RESTARTED 타입
  2) 2인에서 1명 끊김 → 그 좌석이 CPU 로 대체되어 2인 유지
  3) 3인에서 1명 끊김 → 그 사람 제외, 2인으로 시작
  4) 4인에서 2명 끊김 → 2인으로 시작
  5) 살아있는 사람이 전원 투표해야 재시작 (한 명이라도 안 누르면 대기)
  6) 남은 사람이 1명뿐이면 재시작하지 않는다 (새 접속 대기)
  7) web_server /api/restart → RESTART 전송 + snapshot.restart 반영
  8) game.html — 순위표 아래 다시하기 버튼 + 전원 동의 처리 코드

실행:  python -E -X utf8 test_restart_logic.py
"""
import json
import sys
import threading
import time

import protocol as P

OK, NG = "PASS", "FAIL"
fails = []


def chk(name, cond, detail=""):
    print(f"  {OK if cond else NG} {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


# ================================================================ 1) 프로토콜
print("== 1) protocol — RESTART 타입 ==")
import io
chk("RESTART 가 클라→서버 타입에 포함", P.RESTART in P.ALL_TYPES)
chk("RESTARTED 가 서버→클라 타입에 포함", P.RESTARTED in P.ALL_TYPES)
chk("RESTART 인코딩 왕복",
    P.recv_message(io.BytesIO(P.encode(P.RESTART, "1"))) == (P.RESTART, "1"))


# ================================================================ 가짜 릴레이
class FakeConn:
    def __init__(self, alive=True):
        self.alive = alive
        self.voted_restart = False
        self.sent = []

    def send(self, mt, pl=""):
        self.sent.append((mt, pl))
        return True

    def close(self):
        self.alive = False


class FakeRelay:
    """RelayServer 의 재시작 로직만 실제 코드에서 가져다 쓴다."""

    def __init__(self, players, names, human_seats, cpu_seats, conns):
        self.player_count = players
        self.names = names
        self.human_seats = set(human_seats)
        self.cpu_seats = set(cpu_seats)
        self.conns = conns
        self.broadcast_log = []

    def broadcast(self, mt, pl=""):
        self.broadcast_log.append((mt, pl))


# ★ 실제 relay.py 의 메서드를 FakeRelay 에 붙인다 (복사본이 아니라 진짜 코드).
import relay as R

for meth in ("_restart_wait", "_apply_restart_roster",
             "_broadcast_restart", "_wait_for_more_players"):
    setattr(FakeRelay, meth, getattr(R.RelayServer, meth))


def make(players, human, dead=()):
    """좌석 구성 헬퍼. dead = 끊긴 좌석 집합.

    ★ 이름 규칙은 relay.RelayServer.__init__ 과 **동일**하게 만든다
      (사람 = P{i+1}, CPU = CPU{순번}). 테스트 기대값이 실제와 어긋나지 않도록.
    """
    human = set(human)
    cpu = set(range(players)) - human
    names, cpu_no = [], 0
    for i in range(players):
        if i in cpu:
            cpu_no += 1
            names.append(f"CPU{cpu_no}")
        else:
            names.append(f"P{i+1}")
    conns = [FakeConn(alive=(i not in dead)) for i in range(players)]
    for s in cpu:                       # CPU 좌석은 소켓이 없다
        conns[s] = None
    return FakeRelay(players, names, human, cpu, conns)


# ================================================================ 2~6) 좌석 규칙
print("\n== 2) 2인 — 1명 끊김 → CPU 대체 (2인 유지) ==")
r = make(2, human=[0, 1], dead=[1])
# 살아있는 사람만 0번. _apply_restart_roster 직접 검증
r._apply_restart_roster([0])
chk("human_seats = {0}", r.human_seats == {0}, str(sorted(r.human_seats)))
chk("cpu_seats = {1} (CPU 대체)", r.cpu_seats == {1}, str(sorted(r.cpu_seats)))
chk("player_count 2 유지", r.player_count == 2, str(r.player_count))
chk("끊긴 소켓 정리 (conns[1]=None)", r.conns[1] is None)
chk("CPU 이름 자동 부여", r.names[1].startswith("CPU"), r.names[1])

print("\n== 3) 3인 — 1명 끊김 → 그 사람 제외 + 좌석 재배치 ==")
# ★ EHone 실측 시나리오: P2(좌석1)가 먼저 탈락·퇴장 → 살아있는 {0,2}
r = make(3, human=[0, 1, 2], dead=[1])
r.conns[1].alive = False          # 탈락자가 끊긴 상태
c0, c2 = r.conns[0], r.conns[2]
r._apply_restart_roster([0, 2])
chk("human_seats = {0,1} (재배치됨)", r.human_seats == {0, 1}, str(sorted(r.human_seats)))
chk("player_count 2 로 축소", r.player_count == 2, str(r.player_count))
chk("CPU 좌석 없음", r.cpu_seats == set(), str(sorted(r.cpu_seats)))
chk("conns 길이 = 2 (Session 좌석수와 일치)", len(r.conns) == 2, str(len(r.conns)))
chk("좌석0 소켓 유지", r.conns[0] is c0)
chk("옛 좌석2 소켓이 새 좌석1 로 이동", r.conns[1] is c2)
chk("이동한 소켓의 .seat 이 1 로 갱신", c2.seat == 1, str(c2.seat))
chk("이름도 함께 이동", r.names == ["P1", "P3"], str(r.names))
chk("★ 모든 좌석이 0..k-1 범위 (Session 제약)",
    sorted(range(r.player_count)) == sorted(r.human_seats | r.cpu_seats),
    f"human={sorted(r.human_seats)} cpu={sorted(r.cpu_seats)} n={r.player_count}")

print("\n== 3b) 4인 — 앞쪽 사람이 나감 → 재배치 ==")
r = make(4, human=[0, 1, 2, 3], dead=[0])
r.conns[0].alive = False
c1, c2, c3 = r.conns[1], r.conns[2], r.conns[3]
r._apply_restart_roster([1, 2, 3])
chk("human_seats = {0,1,2}", r.human_seats == {0, 1, 2}, str(sorted(r.human_seats)))
chk("conns 순서 유지 (1→0, 2→1, 3→2)",
    r.conns[0] is c1 and r.conns[1] is c2 and r.conns[2] is c3)
chk("이름 순서 유지", r.names == ["P2", "P3", "P4"], str(r.names))
chk("★ 모든 좌석이 0..k-1 범위",
    sorted(range(r.player_count)) == sorted(r.human_seats | r.cpu_seats))

print("\n== 3c) 4인 — 뒤쪽 둘이 나감 → 재배치 불필요 ==")
r = make(4, human=[0, 1, 2, 3], dead=[2, 3])
r.conns[2].alive = False
r.conns[3].alive = False
c0, c1 = r.conns[0], r.conns[1]
r._apply_restart_roster([0, 1])
chk("human_seats = {0,1}", r.human_seats == {0, 1}, str(sorted(r.human_seats)))
chk("conns 그대로 (remap 없이 통과)", r.conns[0] is c0 and r.conns[1] is c1)
chk("이름 그대로", r.names == ["P1", "P2"], str(r.names))

print("\n== 4) CPU 좌석은 재시작해도 유지된다 ==")
# ★ EHone 실측: 인간 2 + CPU1 → 다시하기 눌렀는데 CPU 가 빠짐
r = make(3, human=[0, 1], dead=[])          # cpu_seats={2}
c0, c1 = r.conns[0], r.conns[1]
r._apply_restart_roster([0, 1])             # 아무도 안 나감
chk("player_count 3 유지", r.player_count == 3, str(r.player_count))
chk("human_seats = {0,1}", r.human_seats == {0, 1}, str(sorted(r.human_seats)))
chk("★ cpu_seats = {2} 유지", r.cpu_seats == {2}, str(sorted(r.cpu_seats)))
chk("names 그대로 (CPU 살아있음)", r.names == ["P1", "P2", "CPU1"], str(r.names))
chk("conns 길이 3", len(r.conns) == 3, str(len(r.conns)))

print("\n== 4b) 인간 3 + CPU1 — 사람 1명 나감 → CPU 유지 + 좌석 재배치 ==")
r = make(4, human=[0, 1, 2])                # cpu_seats={3}, 좌석1 이 나감
r.conns[1].alive = False
c0, c2, c3 = r.conns[0], r.conns[2], r.conns[3]
r._apply_restart_roster([0, 2])
chk("player_count 3 (사람2 + CPU1)", r.player_count == 3, str(r.player_count))
chk("human_seats = {0,1}", r.human_seats == {0, 1}, str(sorted(r.human_seats)))
chk("★ cpu_seats = {2} (CPU 유지)", r.cpu_seats == {2}, str(sorted(r.cpu_seats)))
chk("names = ['P1','P3','CPU1']", r.names == ["P1", "P3", "CPU1"], str(r.names))
chk("conns: 0→0, 2→1, 3(CPU)→2",
    r.conns[0] is c0 and r.conns[1] is c2 and r.conns[2] is c3)
chk("★ 모든 좌석이 0..k-1 범위",
    sorted(range(r.player_count)) == sorted(r.human_seats | r.cpu_seats))

print("\n== 4c) 인간 3 + CPU1 — 사람 2명 나감 → CPU 유지 + 재배치 ==")
r = make(4, human=[0, 1, 2])                # cpu_seats={3}, 좌석 0,1 이 나감
r.conns[0].alive = False
r.conns[1].alive = False
c2, c3 = r.conns[2], r.conns[3]
r._apply_restart_roster([2])
chk("player_count 2 (사람1 + CPU1)", r.player_count == 2, str(r.player_count))
chk("human_seats = {0}", r.human_seats == {0}, str(sorted(r.human_seats)))
chk("★ cpu_seats = {1} (CPU 유지)", r.cpu_seats == {1}, str(sorted(r.cpu_seats)))
chk("names = ['P3','CPU1']", r.names == ["P3", "CPU1"], str(r.names))
chk("conns: 2→0, 3(CPU)→1", r.conns[0] is c2 and r.conns[1] is c3)

print("\n== 5) 전원 투표해야 재시작 ==")
r = make(3, human=[0, 1, 2])
# 한 명만 투표한 상태로 _restart_wait 를 스레드로 돌린다
th = threading.Thread(target=r._restart_wait, daemon=True)
th.start()
time.sleep(0.8)
r.conns[0].voted_restart = True
time.sleep(0.8)
chk("한 명만 동의 → 아직 재시작 안 함 (스레드 살아있음)", th.is_alive())
r.conns[1].voted_restart = True
time.sleep(0.8)
chk("둘만 동의 (셋째 미동의) → 여전히 대기", th.is_alive())
r.conns[2].voted_restart = True
th.join(timeout=3)
chk("전원 동의 → 재시작 결정 (스레드 종료)", not th.is_alive())
chk("재시작 현황 브로드캐스트 발생",
    any(mt == P.RESTARTED for mt, _ in r.broadcast_log),
    f"{len(r.broadcast_log)}건")

print("\n== 6) 남은 사람 1명 → 재시작 안 함 ==")
r = make(3, human=[0, 1, 2], dead=[1, 2])
# conns[1], conns[2] 는 alive=False → 남은 사람 1명
# _wait_for_more_players 는 5분 대기라 즉시 결과를 볼 수 없으므로
# 판정만 확인: alive_humans 계산 결과가 1명이어야 한다.
alive = [s for s in sorted(r.human_seats)
         if r.conns[s] is not None and r.conns[s].alive]
chk("살아있는 사람이 1명", len(alive) == 1, str(alive))


# ================================================================ 7) web_server
print("\n== 7) web_server — /api/restart + snapshot.restart ==")
import web_server as W

bridge = W.GameBridge("127.0.0.1", 1)
chk("GameBridge 에 send_restart_vote 존재", hasattr(bridge, "send_restart_vote"))
chk("GameBridge 에 restart 필드 존재", hasattr(bridge, "restart"))

# RESTARTED 수신 → restart 반영 + 전원동의 시 초기화
bridge.messages = ["예전 로그"]
bridge.chats = ["예전 채팅"]
bridge.ended = True
bridge._handle(P.RESTARTED, json.dumps(
    {"voted": 0, "total": 2, "names": ["A", "B"], "voted_names": []}))
chk("RESTARTED(0/2) → restart 현황 저장",
    bridge.restart and bridge.restart["total"] == 2, str(bridge.restart))
chk("0/N 단계에서는 로그 유지 (종료화면 유지)",
    bridge.messages == ["예전 로그"] and bridge.ended)

bridge._handle(P.RESTARTED, json.dumps(
    {"voted": 2, "total": 2, "names": ["A", "B"], "voted_names": ["A", "B"]}))
chk("전원 동의 → 이전 판 로그/채팅 초기화",
    bridge.messages == [] and bridge.chats == [])
chk("전원 동의 → ended 해제 (새 게임 화면)",
    bridge.ended is False and bridge.restart is None)

snap = bridge.snapshot()
chk("snapshot 에 restart 키 포함", "restart" in snap)

# ★★ game_id — 재시작 시 로그 커서 리셋 신호 (실측 버그: 로그가 안 늘고 O/X 안 뜸)
chk("snapshot 에 game_id 포함", "game_id" in snap)
g0 = snap["game_id"]
bridge.messages = ["전판 로그1", "전판 로그2"]
bridge.ended = True
bridge._handle(P.RESTARTED, json.dumps(
    {"voted": 2, "total": 2, "names": ["A", "B"], "voted_names": ["A", "B"]}))
chk("★ 재시작 시 game_id 증가 (브라우저 커서 리셋 신호)",
    bridge.snapshot()["game_id"] == g0 + 1,
    f"{g0} → {bridge.snapshot()['game_id']}")
chk("재시작 후 로그/채팅 비어 있음",
    bridge.messages == [] and bridge.chats == [])
chk("재시작 후 msg_total = 0 (커서 무효화)",
    bridge.snapshot()["msg_total"] == 0)
bridge.sock = None
g1 = bridge.snapshot()["game_id"]
bridge._handle(P.RESTARTED, json.dumps(
    {"voted": 0, "total": 2, "names": ["A"], "voted_names": []}))
chk("0/N 단계에서는 game_id 증가하지 않음",
    bridge.snapshot()["game_id"] == g1, str(bridge.snapshot()["game_id"]))

# 전송 실패해도 예외가 나지 않아야 한다 (소켓 None)
bridge.sock = None
ok = bridge.send_restart_vote()
chk("소켓 없을 때 send_restart_vote 는 False (예외 없음)", ok is False)


# ================================================================ 8) game.html
print("\n== 8) game.html — 다시하기 버튼 ==")
html = open("web/game.html", encoding="utf-8").read()
chk("순위표 안에 다시하기 버튼 존재", 'id="btn-restart"' in html)
chk("버튼이 rankboard 안에 있다",
    html.index('id="rankboard"') < html.index('id="btn-restart"'))
chk("버튼이 순위표 목록보다 뒤에 온다",
    html.index('id="rb-list"') < html.index('id="btn-restart"'))
chk("/api/restart 로 POST 한다", "/api/restart" in html)
chk("전원 동의(voted==total) 시 화면 초기화 코드 존재",
    "resetForNewGame" in html and "updateRestart" in html)
chk("restartVoted 중복 클릭 방지 존재", "restartVoted" in html)
chk("STATE viewer 로 좌석 갱신 (재시작 대비)",
    "d.state.viewer" in html)
# ★★ 실측 버그: 재시작 후 로그가 안 늘고 O/X 안 뜸 → game_id 커서 리셋
chk("★ game_id 로 커서 리셋 코드 존재", "d.game_id" in html)
chk("★ 커서 리셋 시 since/chatSince 를 0 으로",
    "since = 0; chatSince = 0;" in html)
chk("★ 새 게임 시 이전 판 로그 화면 제거",
    "logEl.innerHTML = ''" in html and "chatlogEl.innerHTML = ''" in html)


print("\n" + "=" * 50)
if fails:
    print(f"FAILED {len(fails)}건:")
    for f in fails:
        print("   -", f)
    raise SystemExit(1)
print("ALL PASS ✅")
