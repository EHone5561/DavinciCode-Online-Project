# -*- coding: utf-8 -*-
"""relay 이름 입력이 다음 참가자를 막지 않는지 검증.

핵심: 이름 ASK 에 응답하지 않는 클라이언트(A)가 있어도, 서버가 그 좌석에서
무한 블록되지 않고 처리를 끝내(타임아웃/끊김) 다음 참가자(B)를 받는지.

방법: A 를 접속 직후 끊는다(None 반환 경로) → 서버는 좌석을 비우고 B 를 받아야.
      (60초 타임아웃까지 기다리지 않도록 '끊김' 경로를 태운다.)
"""
import os
import socket
import subprocess
import sys
import time

import protocol as P

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0",
           PYTHONIOENCODING="utf-8")


def main():
    import testutil
    testutil.free_port(8841)

    srv = subprocess.Popen(
        [PY, "-E", "relay.py", "2", "--cpu", "1", "--port", "8841"],
        cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", bufsize=1)
    time.sleep(1.5)

    # A: 접속 후 이름 ASK 를 받고 바로 강제 종료 (응답 없음 → 끊김 경로)
    a = socket.create_connection(("127.0.0.1", 8841), timeout=5)
    a.settimeout(2)
    try:
        a.recv(4096)            # 이름 ASK 수신
    except socket.timeout:
        pass
    a.close()
    print("[test] A 접속 후 즉시 끊음")

    # B: 정상 접속 → 좌석을 받아야 한다
    time.sleep(1.0)
    b = socket.create_connection(("127.0.0.1", 8841), timeout=5)
    b.settimeout(2)
    got_hello = False
    for _ in range(8):
        try:
            data = b.recv(4096).decode("utf-8", "replace")
        except socket.timeout:
            continue
        if not data:
            break
        if "ASK" in data and "이름" in data:
            b.sendall(P.encode(P.REPLY, "정상B"))
        if "HELLO" in data:
            got_hello = True
            break
    print("[test] B HELLO 수신:", got_hello)

    # 서버가 게임을 시작할 때까지 잠깐
    time.sleep(2.0)
    try:
        b.close()
    except OSError:
        pass
    time.sleep(1.0)
    if srv.poll() is None:
        srv.kill()
    out = srv.stdout.read() or ""

    print("=== 서버 출력 ===")
    for line in out.splitlines():
        if "좌석" in line or "게임을 시작" in line or "끊김" in line:
            print("   " + line)

    checks = [
        ("B 가 좌석(HELLO) 수신 — 서버가 A 에서 블록 안 됨", got_hello),
        ("서버가 A 끊김 처리 후 계속 진행",
         "다시 받습니다" in out or "좌석 1 접속: 정상B" in out),
    ]
    print("[판정]")
    allok = True
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print("=" * 50)
    print("ALL PASS" if allok else "SOME FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
