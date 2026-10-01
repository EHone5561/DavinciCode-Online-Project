# -*- coding: utf-8 -*-
"""★ 재시작 후 기권 처리 — 로그를 남기며 정밀 재현.

EHone 실측: "재시작 후 턴 잡고 브라우저를 닫아도 기권 처리가 안 됨"

이 테스트는 릴레이 출력을 **파일로** 남겨서 어디서 막히는지 본다.
(PIPE 버퍼링 때문에 지금까지 로그가 안 보였다.)

시나리오
--------
  1) 인간 3명 접속 → 첫 게임
  2) C 가 자기 턴에 PING 중단 → 기권 처리 확인
  3) A, B 가 다시하기 → 사람 2명으로 재시작 (좌석 재배치)
  4) B 가 자기 턴에 PING 중단 → 기권 처리되는가  ← 핵심

실행:  python -E -X utf8 -u test_restart_forfeit.py
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

import protocol as P

HOST = "127.0.0.1"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_relay_log.txt")
fails = []


def chk(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def free_port():
    s = socket.socket()
    s.bind((HOST, 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Sock:
    def __init__(self, port, name, ping=True):
        self.sock = socket.create_connection((HOST, port), timeout=15)
        self.sock.settimeout(None)
        self.f = self.sock.makefile("rb")
        self.inbox = []
        self.shows = []
        self.state = None
        self.ended = False
        self.restart = None
        self.seat = None
        self._stop = threading.Event()
        threading.Thread(target=self._recv, daemon=True).start()
        if ping:
            threading.Thread(target=self._ping, daemon=True).start()
        self.send(P.REPLY, name)

    def _ping(self):
        while not self._stop.is_set():
            self._stop.wait(1.5)
            if self._stop.is_set():
                break
            try:
                self.sock.sendall(P.encode(P.PING, "1"))
            except OSError:
                return

    def stop_ping(self):
        self._stop.set()

    def _recv(self):
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
                elif mt == P.SHOW:
                    self.shows.append(pl)
                elif mt == P.END:
                    self.ended = True
                elif mt == P.RESTARTED:
                    try:
                        self.restart = json.loads(pl)
                    except ValueError:
                        pass
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

    def wait_ask(self, timeout=0.3):
        end = time.time() + timeout
        while time.time() < end:
            for i, (mt, pl) in enumerate(self.inbox):
                if mt == P.ASK:
                    self.inbox.pop(i)
                    return P.decode_ask(pl)
            time.sleep(0.04)
        return None, None, None

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def my_turn(s):
    st = s.state or {}
    return (st.get("round", 0) >= 1 and st.get("waiting_name") is None
            and not st.get("spectating"))


def _guess_reply(data):
    targets = (data or {}).get("targets") or []
    values = (data or {}).get("values") or []
    if not targets or not values:
        return "q"
    seat, pos = targets[0]
    return f"{seat + 1} {pos + 1} {values[0]}"


def drain(socks, seconds):
    """모든 ASK 에 응답해 게임을 진행시킨다 (추측은 실제로 시도)."""
    end = time.time() + seconds
    while time.time() < end:
        for s in socks:
            pr, mode, data = s.wait_ask(0.2)
            if mode == "guess":
                s.send(P.REPLY, _guess_reply(data))
            elif mode == "more_guess":
                s.send(P.REPLY, "q")
            elif mode == "black_count":
                s.send(P.REPLY, "0")
            elif mode == "fail_reveal":
                s.send(P.REPLY, "1")
            elif mode in ("joker_slot", "joker_side"):
                s.send(P.REPLY, "0")
            elif mode is not None:
                s.send(P.REPLY, "1")
        time.sleep(0.1)


def wait_for(cond, socks, timeout, label=""):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        drain(socks, 0.25)
    return False


port = free_port()
logf = open(LOG, "w", encoding="utf-8")
relay = subprocess.Popen(
    [sys.executable, "-E", "-X", "utf8", "-u", "relay.py", "3", "--port", str(port)],
    stdout=logf, stderr=subprocess.STDOUT,
)
socks = []
try:
    for _ in range(60):
        try:
            s = socket.create_connection((HOST, port), timeout=1)
            s.close()
            break
        except OSError:
            time.sleep(0.15)

    time.sleep(0.6)
    a, b, c = (Sock(port, n) for n in ("A", "B", "C"))
    socks = [a, b, c]
    for s in socks:
        s.wait_ask(10)
    time.sleep(1.5)

    print("== 1) 첫 게임 시작 ==")
    drain(socks, 2.5)
    wait_for(lambda: any(my_turn(s) for s in socks), socks, 30)
    chk("게임 진행 중 (누군가 턴)", any(my_turn(s) for s in socks) or
        any((s.state or {}).get("round", 0) >= 1 for s in socks),
        f"round={a.state.get('round') if a.state else None}")

    print("\n== 2) C 가 자기 턴에 나감 ==")
    victim = next((s for s in socks if my_turn(s)), c)
    others = [s for s in socks if s is not victim]
    print(f"    victim seat={victim.seat}, others={[s.seat for s in others]}")
    observer = others[0]
    observer.shows.clear()
    victim.stop_ping()
    got = wait_for(lambda: any("기권" in x for x in observer.shows), others, 40)
    chk("첫 게임: 기권 처리됨", got, f"shows={len(observer.shows)}")

    wait_for(lambda: victim.ended or observer.ended, others, 90)
    chk("게임 종료 (END)", victim.ended or observer.ended)

    print("\n== 3) 다시하기 → 사람 2명으로 재시작 ==")
    wait_for(lambda: observer.restart, others, 30)
    info = observer.restart or {}
    chk("RESTARTED 수신", info.get("total", 0) >= 2,
        f"voted={info.get('voted')} total={info.get('total')}")
    for s in others:
        s.send(P.RESTART, "1")
    ok = wait_for(lambda: observer.restart is None and observer.state is not None
                  and not observer.ended, others, 60)
    chk("재시작됨", ok, f"round={observer.state.get('round') if observer.state else None}")
    n = len((observer.state or {}).get("players", []))
    chk("재시작 후 인원 2", n == 2, f"players={n}")
    print(f"    재시작 후 A seat={others[0].seat}, B seat={others[1].seat}")

    print("\n== 4) ★ 새 게임에서 턴 잡고 나감 ==")
    # 남은 둘 중 하나가 턴을 잡을 때까지
    got_turn = wait_for(lambda: any(my_turn(s) for s in others), others, 40)
    chk("새 게임에서 턴이 돌아감", got_turn,
        f"a={my_turn(others[0])} b={my_turn(others[1])}")
    victim2 = next((s for s in others if my_turn(s)), others[0])
    observer2 = others[1] if victim2 is others[0] else others[0]
    print(f"    victim2 seat={victim2.seat} (my_turn), "
          f"observer2 seat={observer2.seat}")
    observer2.shows.clear()
    victim2.stop_ping()
    got2 = wait_for(lambda: any("기권" in x for x in observer2.shows),
                    [observer2], 50)
    chk("★★ 새 게임: 기권 처리됨 (EHone 버그)", got2,
        f"기권={len([x for x in observer2.shows if '기권' in x])}건, "
        f"전체SHOW={len(observer2.shows)}")

finally:
    for s in socks:
        try:
            s.close()
        except Exception:
            pass
    relay.terminate()
    try:
        relay.wait(timeout=6)
    except subprocess.TimeoutExpired:
        relay.kill()
    logf.close()

print(f"\n(릴레이 로그: {LOG})")
try:
    txt = open(LOG, encoding="utf-8").read()
    lines = [x for x in txt.splitlines()
             if any(k in x for k in ("[Sys]", "기권", "다시하기", "재배치", "구성"))]
    print("\n---- 릴레이 주요 로그 ----")
    print("\n".join(lines[-30:]) if lines else "(해당 로그 없음)")
except OSError:
    pass

print("\n" + "=" * 50)
if fails:
    print(f"FAILED {len(fails)}건:")
    for f in fails:
        print("   -", f)
    raise SystemExit(1)
print("ALL PASS ✅")
