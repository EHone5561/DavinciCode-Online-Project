# -*- coding: utf-8 -*-
"""exe E2E — dist/다빈치코드.exe 로 서버+참가가 실제로 되는지 확인.

exe server 로 서버를 띄우고, exe client 로 접속해 게임 시작까지 확인.
(사람 클라이언트는 q 만 보내므로 '게임 시작 + 화면 중계'까지 판정.)
"""

import os
import subprocess
import sys
import threading
import time

PORT = 8877
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "다빈치코드.exe")
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0")
ENV.pop("PYTHONHOME", None)
ENV.pop("PYTHONPATH", None)
ENV.pop("AUTOHUMAN", None)


class Runner:
    def __init__(self, args, script):
        self.p = subprocess.Popen(
            [EXE] + args,
            cwd=HERE, env=ENV,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._feed, args=(script,), daemon=True).start()

    def _feed(self, script):
        for line in script:
            if self.p.poll() is not None:
                break
            try:
                self.p.stdin.write(line + "\n")
                self.p.stdin.flush()
            except Exception:
                break
            time.sleep(0.25)
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

    if not os.path.isfile(EXE):
        print("[!] exe 없음:", EXE)
        return 1

    srv = Runner(["server"], ["2", "1", str(PORT)])   # 2인, CPU1
    time.sleep(4.0)                                    # exe 부팅은 좀 느림
    cli = Runner(["client"], ["127.0.0.1", str(PORT), "exeA"] + ["q"] * 40)

    deadline = time.time() + 20
    while time.time() < deadline:
        if srv.p.poll() is not None and cli.p.poll() is not None:
            break
        time.sleep(0.5)

    for r in (srv, cli):
        if r.p.poll() is None:
            r.p.kill()
    s = srv.out()
    c = cli.out()
    testutil.free_port(PORT)

    print("===== EXE SERVER (tail) =====")
    print("\n".join(s.splitlines()[-10:]))
    print("===== EXE CLIENT (tail) =====")
    print("\n".join(c.splitlines()[-10:]))

    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("===== 판정 =====")
    chk("exe 서버가 대기 화면 출력", "대기 중" in s)
    chk("exe 서버가 IP 안내", "내 IP" in s)
    chk("exe 클라이언트가 접속", "exeA" in s)
    chk("exe 서버가 게임 시작", "게임을 시작" in s)
    chk("exe 클라이언트가 게임 화면 수신", "다빈치 코드" in c)
    chk("exe 클라이언트 이름 반영", "exeA" in c)
    chk("게임 로직 진행(CPU 턴)", "CPU1" in c)

    print("RESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
