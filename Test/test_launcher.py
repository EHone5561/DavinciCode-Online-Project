# -*- coding: utf-8 -*-
"""launcher.py E2E — 통합 런처로 서버+참가를 띄우고 게임 완주 확인.

전략: 사람 좌석 대신 **CPU 를 섞어** 게임이 반드시 끝나게 한다.
      (전원 사람 + q 만 보내면 규칙상 안 끝난다 — 스킬 '전원 사람' 절)
사람 클라이언트 1명 + CPU 1명 (2인), 사람은 계속 q(멈춤)만 보낸다.
"""

import os
import subprocess
import sys
import threading
import time

PORT = 8867
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0")
ENV.pop("AUTOHUMAN", None)


class Runner:
    def __init__(self, args, script):
        self.p = subprocess.Popen(
            [PY, "-E", "-u", "launcher.py"] + args,
            cwd=HERE, env=ENV,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.t = threading.Thread(target=self._feed, args=(script,), daemon=True)
        self.t.start()

    def _feed(self, script):
        for line in script:
            if self.p.poll() is not None:
                break
            try:
                self.p.stdin.write(line + "\n")
                self.p.stdin.flush()
            except (BrokenPipeError, ValueError):
                break
            time.sleep(0.2)
        try:
            self.p.stdin.close()
        except Exception:
            pass

    def out(self):
        try:
            return self.p.stdout.read() or ""
        except Exception:
            return ""


def main():
    import testutil
    testutil.free_port(PORT)

    # 사람 1명 + CPU 1명 = 2인. 인원2, cpu1, 포트
    srv = Runner(["server"], ["2", "1", str(PORT)])
    time.sleep(2.0)

    # 사람 클라이언트: 설정(host,port,name) + 게임 내내 q(멈춤)
    cli = Runner(["client"],
                 ["127.0.0.1", str(PORT), "사람A"] + ["q"] * 60)

    deadline = time.time() + 18
    while time.time() < deadline:
        if srv.p.poll() is not None and cli.p.poll() is not None:
            break
        time.sleep(0.5)

    sid = srv.p.poll()
    for r in (srv, cli):
        if r.p.poll() is None:
            r.p.kill()
    s = srv.out()
    c = cli.out()
    testutil.free_port(PORT)

    print("===== SERVER (tail) =====")
    print("\n".join(s.splitlines()[-8:]))
    print("===== CLIENT (tail) =====")
    print("\n".join(c.splitlines()[-18:]))

    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("===== 판정 =====")
    chk("서버 대기 화면 출력", "대기 중" in s)
    chk("서버가 게임 시작", "게임을 시작" in s)
    chk("서버가 IP 안내(다른 기기 접속용)", "내 IP" in s)
    chk("클라이언트 접속 인식", "사람A" in s)
    chk("클라이언트 게임 화면 수신", "다빈치 코드" in c)
    chk("클라이언트 이름 반영", "사람A" in c)
    chk("CPU 턴 진행(게임 로직 동작)",
        "CPU1" in c and ("정답" in c or "오답" in c))

    print("RESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
