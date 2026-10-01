# -*- coding: utf-8 -*-
"""exe 결과창 유지 검증 — 게임이 끝난 뒤 exe 창이 즉시 닫히지 않는지.

서버 exe(2인, CPU1) + 클라이언트 exe(사람1).
사람이 계속 q(멈춤)면 게임이 안 끝나므로, 사람은 추측도 섞는다.
게임 종료 후 'Enter 를 누르면 종료합니다' 문구가 뜨면 성공.
"""

import os
import re
import subprocess
import sys
import threading
import time

PORT = 8891
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "다빈치코드.exe")
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0")
for k in ("PYTHONHOME", "PYTHONPATH", "AUTOHUMAN"):
    ENV.pop(k, None)


class Runner:
    def __init__(self, args, script):
        self.p = subprocess.Popen(
            [EXE] + args, cwd=HERE, env=ENV,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._feed, args=(script,), daemon=True).start()

    def _feed(self, script):
        """프롬프트를 못 읽으니 일정 간격으로 입력을 계속 공급 (여유분 포함)."""
        for line in script:
            if self.p.poll() is not None:
                break
            try:
                self.p.stdin.write(line + "\n")
                self.p.stdin.flush()
            except Exception:
                break
            time.sleep(0.35)
        # 이후에도 input() 이 계속 요구할 수 있으니 Enter 를 조금 더 공급
        for _ in range(30):
            if self.p.poll() is not None:
                break
            try:
                self.p.stdin.write("\n")
                self.p.stdin.flush()
            except Exception:
                break
            time.sleep(0.3)

    def out(self):
        try:
            return self.p.stdout.read() or ""
        except Exception:
            return ""


def main():
    import testutil
    testutil.free_port(PORT)

    srv = Runner(["server"], ["2", "1", str(PORT)])
    time.sleep(4.0)
    # 사람: 설정 + 게임 내내 'q'(멈춤) 반복 (안전하게 많이)
    cli = Runner(["client"],
                 ["127.0.0.1", str(PORT), "결과테스터"] + ["q"] * 40)

    deadline = time.time() + 70
    while time.time() < deadline:
        if srv.p.poll() is not None and cli.p.poll() is not None:
            break
        time.sleep(0.5)

    for r in (srv, cli):
        if r.p.poll() is None:
            r.p.kill()
    c = cli.out()
    testutil.free_port(PORT)
    try:
        subprocess.run(["taskkill", "/F", "/IM", "다빈치코드.exe"],
                       capture_output=True)
    except Exception:
        pass

    print("===== CLIENT (tail) =====")
    print("\n".join(c.splitlines()[-20:]))

    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("===== 판정 =====")
    chk("게임 화면 수신", "다빈치 코드" in c)
    chk("게임 진행(정답/오답 발생)", "정답" in c or "오답" in c)
    chk("★ 종료 대기 문구 표시(결과창 유지)",
        "누르면 종료" in c or "Enter" in c and "종료" in c)

    print("RESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
