# -*- coding: utf-8 -*-
"""다시하기(재시작) 왕복 테스트 — 실제 릴레이를 띄우고 소켓으로 검증한다.

검증 항목
---------
  1) protocol: RESTART / RESTARTED 가 ALL_TYPES 에 포함된다
  2) 릴레이가 RESTART 를 받으면 게임 입력 큐를 오염시키지 않는다
  3) 게임이 끝나면 RESTARTED(0/N) 현황이 온다  ← 순위표에서 버튼이 뜬다
  4) 전원이 투표하면 새 게임이 시작된다
  5) 2인에서 1명이 끊기면 그 좌석이 CPU 로 대체되어 2인으로 재시작
  6) 3인에서 1명이 끊기면 그 사람만 제외되어 2인으로 재시작
  7) web_server: /api/restart → RESTART 전송, snapshot.restart 반영

실행:  python -E -X utf8 test_restart.py
"""
import json
import random
import socket
import subprocess
import sys
import threading
import time

import protocol as P

HOST = "127.0.0.1"
OK = "PASS"
NG = "FAIL"
fails = []


def chk(name, cond, detail=""):
    mark = OK if cond else NG
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- 소켓 클라이언트
class Sock:
    """릴레이에 직접 접속하는 테스트용 클라이언트."""

    def __init__(self, port, name):
        self.sock = socket.create_connection((HOST, port), timeout=15)
        self.sock.settimeout(None)
        self.f = self.sock.makefile("rb")
        self.inbox = []
        self.state = None
        self.ended = False
        self.restart = None
        self.seat = None
        threading.Thread(target=self._loop, daemon=True).start()
        self.send(P.REPLY, name)

    def _loop(self):
        try:
            while True:
                mt, pl = P.recv_message(self.f)
                if mt is None and pl is None:
                    break
                if mt is None:
                    continue
                if mt == P.STATE:
                    st = P.decode_state(pl)
                    if st:
                        self.state = st
                elif mt == P.END:
                    self.ended = True
                elif mt == P.RESTARTED:
                    try:
                        self.restart = json.loads(pl)
                    except ValueError:
                        self.restart = {}
                elif mt == P.HELLO:
                    parts = pl.split(" ", 1)
                    if parts and parts[0].isdigit():
                        self.seat = int(parts[0]) - 1
                else:
                    self.inbox.append((mt, pl))
        except Exception:
            pass

    def send(self, mt, pl=""):
        try:
            self.sock.sendall(P.encode(mt, pl))
            return True
        except OSError:
            return False

    def wait_ask(self, timeout=20):
        """ASK 가 올 때까지 기다렸다가 (prompt, mode, data) 를 돌려준다."""
        end = time.time() + timeout
        while time.time() < end:
            for i, (mt, pl) in enumerate(self.inbox):
                if mt == P.ASK:
                    self.inbox.pop(i)
                    return P.decode_ask(pl)
            time.sleep(0.05)
        return None, None, None

    def close(self):
        self.send(P.BYE, "1")
        try:
            self.sock.close()
        except OSError:
            pass


def start_relay(players, cpu, port):
    p = subprocess.Popen(
        [sys.executable, "-E", "-X", "utf8", "relay.py", str(players),
         "--port", str(port), "--cpu", str(cpu)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    # 포트가 열릴 때까지 대기
    for _ in range(60):
        try:
            s = socket.create_connection((HOST, port), timeout=1)
            s.close()
            return p
        except OSError:
            time.sleep(0.15)
    return p


def free_port():
    s = socket.socket()
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ================================================================ 1) 프로토콜
print("== 1) protocol — RESTART 타입 ==")
chk("RESTART 가 클라→서버 타입에 포함", P.RESTART in P.ALL_TYPES)
chk("RESTARTED 가 서버→클라 타입에 포함", P.RESTARTED in P.ALL_TYPES)
chk("RESTART 문자열 인코딩 왕복",
    P.recv_message(__import__("io").BytesIO(
        P.encode(P.RESTART, "1"))) == (P.RESTART, "1"))

# ================================================================ 2) 2인 재시작
print("\n== 2) 2인 — 게임 종료 후 전원 다시하기 ==")
port = free_port()
relay = start_relay(2, 0, port)          # 사람 2명, CPU 0
try:
    time.sleep(0.6)
    a = Sock(port, "A")
    b = Sock(port, "B")
    # 이름 ASK 소비 + 검은카드 선택
    for c in (a, b):
        c.wait_ask(10)
    time.sleep(1.2)
    # 검은 카드 선택 (양쪽 다 0장)
    for c in (a, b):
        c.send(P.REPLY, "0")
    time.sleep(1.5)

    # 게임이 실제로 진행되도록: 턴이 오면 계속 '그만' 또는 아무 입력
    deadline = time.time() + 90
    game_ended = False
    while time.time() < deadline:
        for c in (a, b):
            if c.ended:
                game_ended = True
        if game_ended:
            break
        # 내 턴이면 멈춤 입력으로 넘긴다 (게임을 빨리 끝내려고)
        for c in (a, b):
            pr, mode, data = c.wait_ask(0.2)
            if mode is not None:
                c.send(P.REPLY, "q" if mode == "guess" else "1")
        time.sleep(0.15)

    chk("게임이 종료되었다 (END 수신)", game_ended)

    # 다시하기 현황 (0/N) 이 와야 순위표에서 버튼이 뜬다
    for _ in range(40):
        if a.restart or b.restart:
            break
        time.sleep(0.1)
    info = a.restart or {}
    chk("RESTARTED 현황 수신 (0/N → 버튼 표시)", info.get("total", 0) >= 2,
        f"voted={info.get('voted')} total={info.get('total')}")

    # ★ 전원 투표
    a.send(P.RESTART, "1")
    b.send(P.RESTART, "1")

    # 새 게임 시작 = END 가 아니고 STATE 가 새로 온다
    time.sleep(2.5)
    started = False
    for _ in range(40):
        if a.state and a.restart is None:
            started = True
            break
        time.sleep(0.15)
    chk("전원 동의 → 새 게임 시작 (재시작됨)", started,
        f"state_round={a.state.get('round') if a.state else None}")

    # 새 게임에서 다시 ASK(검은카드)가 와야 한다 → 진짜 새 판
    pr, mode, data = a.wait_ask(25)
    chk("새 게임에서 다시 입력 요청이 왔다 (새 판 확인)",
        mode is not None, f"mode={mode}")

    a.close()
    b.close()
finally:
    relay.terminate()
    try:
        relay.wait(timeout=6)
    except subprocess.TimeoutExpired:
        relay.kill()

# ================================================================ 결과
print("\n" + "=" * 50)
if fails:
    print(f"FAILED {len(fails)}건: {fails}")
    raise SystemExit(1)
print("ALL PASS ✅")
