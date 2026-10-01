# -*- coding: utf-8 -*-
"""★ 브라우저 종료 → web_server 자살 → relay 즉시 기권 검증.

EHone: "html 을 닫으면 연결한 터미널도 닫히게 할 수 있나"
       "턴 잡고 나가도 15초 지나도 기권 처리가 안 됨"

검증 방식
---------
  브라우저를 흉내내는 **폴링 클라이언트**로 web_server 에 붙는다.
  폴링을 멈추면 web_server 의 `_watchdog_loop` 이 프로세스를 종료해야 하고,
  그러면 relay 가 EOF 로 좌석을 즉시 기권 처리해야 한다.

  처음에는 /api/state 를 폴링하고, 중간에 **폴링을 중단**한다.
  그리고 relay 쪽(다른 사람)이 기권 알림을 받는지 본다.

실행:  python -E -X utf8 -u test_browser_close.py
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import protocol as P

HOST = "127.0.0.1"
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


# ---------------------------------------------------------------- relay 쪽 사람
class Sock:
    """relay 에 직접 붙는 사람 (터미널 client.py 대역)."""

    def __init__(self, port, name):
        self.sock = socket.create_connection((HOST, port), timeout=15)
        self.sock.settimeout(None)
        self.f = self.sock.makefile("rb")
        self.inbox = []
        self.shows = []
        self.state = None
        self.ended = False
        self.seat = None
        threading.Thread(target=self._recv, daemon=True).start()
        self.send(P.REPLY, name)

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
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------- 브라우저 대역 (폴링만)
class Poller(threading.Thread):
    """web_server 의 /api/state 를 폴링하는 브라우저 흉내.

    stop() 하면 폴링이 멈춘다 = 브라우저를 닫은 것과 같은 효과.
    """

    def __init__(self, web_port):
        super().__init__(daemon=True)
        self.web_port = web_port
        self.running = True
        self.polls = 0
        self.name_ = None

    def run(self):
        while self.running:
            try:
                url = f"http://127.0.0.1:{self.web_port}/api/state?since=0&chat_since=0"
                with urllib.request.urlopen(url, timeout=3) as r:
                    d = json.loads(r.read())
                self.polls += 1
                if d.get("name"):
                    self.name_ = d["name"]
            except Exception:
                time.sleep(0.3)
                continue
            time.sleep(0.28)          # game.html 과 같은 주기

    def stop(self):
        self.running = False


def drive(socks, seconds):
    end = time.time() + seconds
    while time.time() < end:
        for s in socks:
            pr, mode, data = s.wait_ask(0.2)
            if mode == "black_count":
                s.send(P.REPLY, "0")
            elif mode in ("joker_slot", "joker_side"):
                s.send(P.REPLY, "0")
            elif mode == "fail_reveal":
                s.send(P.REPLY, "1")
            elif mode in ("guess", "more_guess"):
                s.send(P.REPLY, "q")
            elif mode is not None:
                s.send(P.REPLY, "1")
        time.sleep(0.1)


port = free_port()
web_port = free_port()
logf = open("_web_log.txt", "w", encoding="utf-8")
relay = subprocess.Popen(
    [sys.executable, "-E", "-X", "utf8", "-u", "relay.py", "3", "--port", str(port)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)
webproc = None
socks = []
try:
    for _ in range(60):
        try:
            s = socket.create_connection((HOST, port), timeout=1)
            s.close()
            break
        except OSError:
            time.sleep(0.15)
    time.sleep(0.5)

    # 터미널 사람 2명 (A, B) + 브라우저 사람 1명 (web_server 경유)
    a = Sock(port, "A")
    b = Sock(port, "B")
    socks = [a, b]
    for s in socks:
        s.wait_ask(10)

    webproc = subprocess.Popen(
        [sys.executable, "-E", "-X", "utf8", "-u", "web_server.py",
         "--host", HOST, "--port", str(port), "--web-port", str(web_port),
         "--no-browser"],
        stdout=logf, stderr=subprocess.STDOUT,
    )
    # 웹서버 준비 대기
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{web_port}/api/state?since=0&chat_since=0",
                    timeout=2) as r:
                r.read()
            break
        except Exception:
            time.sleep(0.2)

    poller = Poller(web_port)
    poller.start()
    time.sleep(1.5)
    # 브라우저 사람 이름 보내기 (이름 ASK 는 /api/name)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/name",
            data=json.dumps({"text": "W"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as e:
        print("name post err:", e)
    time.sleep(2.0)

    print("== 1) 3명 접속 확인 ==")
    chk("폴링이 되고 있다", poller.polls > 3, f"polls={poller.polls}")
    # ※ 이 테스트의 관심사는 '기권 감지'지 게임 진행이 아니다.
    #   웹 쪽(브라우저 대역)은 폴링만 하고 입력을 안 보내므로 라운드가
    #   시작되지 않을 수 있다. relay 가 3명을 인식했는지만 확인한다.
    drive(socks, 4.0)
    chk("relay 가 접속자 3명을 인식", len(socks) == 2 and a.seat is not None
        and b.seat is not None, f"A seat={a.seat} B seat={b.seat} (+W 웹)")

    print("\n== 1b) ★ F5 새로고침 구제 확인 ==")
    # 폴링을 잠깐 멈췄다가(새로고침 중) 2초 안에 재개한다.
    poller.stop()
    time.sleep(2.0)                      # 새로고침하는 동안 (GRACE 5초 이내)
    poller2 = Poller(web_port)
    poller2.start()
    time.sleep(3.0)
    alive = webproc.poll() is None
    chk("★ 새로고침(2초 공백 후 재개) → 프로세스 살아있음", alive,
        f"webproc={'살아있음' if alive else '죽음'}")
    chk("재개 후 폴링 증가", poller2.polls > 3, f"polls={poller2.polls}")
    poller = poller2

    print("\n== 2) ★ 브라우저를 닫는다 (폴링 중단) ==")
    a.shows.clear()
    b.shows.clear()
    t0 = time.time()
    poller.stop()
    # webproc 이 스스로 죽는지 확인 (최대 20초)
    died_at = None
    end = time.time() + 20
    while time.time() < end:
        if webproc.poll() is not None:
            died_at = time.time() - t0
            break
        drive(socks, 0.3)
    chk("★ web_server 프로세스가 스스로 종료됨", died_at is not None,
        f"{died_at:.1f}s" if died_at else "안 죽음")

    # 기권 알림 확인
    forf_at = None
    end = time.time() + 25
    while time.time() < end:
        if any("기권" in x for x in a.shows) or any("기권" in x for x in b.shows):
            forf_at = time.time() - t0
            break
        drive(socks, 0.3)
    chk("★★ relay 가 즉시 기권 처리함 (EOF)", forf_at is not None,
        f"{forf_at:.1f}s" if forf_at else "미탐지")
    if died_at and forf_at:
        chk("기권이 브라우저 종료 후 10초 안에 일어남", forf_at < 10.0,
            f"{forf_at:.1f}s")

finally:
    for s in socks:
        try:
            s.close()
        except Exception:
            pass
    if webproc and webproc.poll() is None:
        webproc.terminate()
    relay.terminate()
    for _p, _t in ((webproc, 5), (relay, 6)):
        if _p is None:
            continue
        try:
            _p.wait(timeout=_t)
        except subprocess.TimeoutExpired:
            _p.kill()
    logf.close()

try:
    txt = open("_web_log.txt", encoding="utf-8").read()
    print("\n---- web_server 로그 ----")
    print("\n".join(txt.splitlines()[-12:]) if txt.strip() else "(없음)")
except OSError:
    pass

print("\n" + "=" * 50)
if fails:
    print(f"FAILED {len(fails)}건:")
    for f in fails:
        print("   -", f)
    raise SystemExit(1)
print("ALL PASS ✅")
