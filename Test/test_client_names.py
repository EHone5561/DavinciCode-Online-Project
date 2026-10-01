# -*- coding: utf-8 -*-
"""E2E: 이름 입력 + 중복 출력 검증.

서버(relay 3인, cpu 1) 를 subprocess 로 띄우고
사람 클라이언트 2대를 stdin 스크립트로 구동한다.
이름이 실제로 반영되는지 / [공개] 가 2연속 나오지 않는지 판정.
"""
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0", PYTHONIOENCODING="utf-8")


def main():
    # 이전 실행에서 남은 좀비 서버가 포트를 점유하면 접속이 실패한다 → 정리.
    import testutil
    testutil.free_port(8791)
    srv = subprocess.Popen(
        [PY, "-E", "relay.py", "3", "--cpu", "1", "--port", "8791"],
        cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", bufsize=1,
    )
    time.sleep(1.5)

    # 클라이언트1: 이름 "알파" 입력 후 계속 q(멈춤) → 게임은 CPU가 진행
    c1 = subprocess.Popen(
        [PY, "-E", "client.py", "--host", "127.0.0.1", "--port", "8791"],
        cwd=ROOT, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
    )
    c1.stdin.write("알파\n" + "2\n" + ("q\n0\n0\n1\n" * 300))
    c1.stdin.flush()

    time.sleep(0.8)
    # 클라이언트2: --name 옵션으로 "베타"
    c2 = subprocess.Popen(
        [PY, "-E", "client.py", "--host", "127.0.0.1", "--port", "8791",
         "--name", "베타"],
        cwd=ROOT, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
    )
    c2.stdin.write("2\n" + ("q\n0\n0\n1\n" * 300))
    c2.stdin.flush()

    out1, out2 = "", ""
    deadline = time.time() + 25
    try:
        while time.time() < deadline:
            time.sleep(0.5)
            c1.poll(); c2.poll()
            if c1.returncode is not None and c2.returncode is not None:
                break
    finally:
        for c in (c1, c2):
            if c.poll() is None:
                c.kill()
        if srv.poll() is None:
            srv.kill()
    try:
        out1 = c1.stdout.read() or ""
        out2 = c2.stdout.read() or ""
    except Exception:
        pass
    srv_out = srv.stdout.read() or ""
    (c1.stdout, c2.stdout)

    print("=" * 60)
    print("[C1 stdout]")
    print(out1)
    print("=" * 60)
    print("[C2 stdout]")
    print(out2)
    print("=" * 60)
    print("[SERVER stdout]")
    print(srv_out)
    print("=" * 60)

    # 판정
    checks = []
    checks.append(("C1 이름 '알파' 반영", "이름 알파" in out1))
    checks.append(("C2 이름 '베타' 반영 (--name)", "이름 베타" in out2))
    checks.append(("C1 P1 고정 아님", "이름 P1" not in out1))
    # [공개] 2연속 중복 없음
    dup1 = re.search(r"\[공개\][^\n]*\n\s*\[공개\]", out1)
    dup2 = re.search(r"\[공개\][^\n]*\n\s*\[공개\]", out2)
    checks.append(("C1 [공개] 2연속 없음", dup1 is None))
    checks.append(("C2 [공개] 2연속 없음", dup2 is None))
    # 턴 화면(내 턴)에도 [공개] 표시 — "내 패" 뒤에 [공개] 등장
    turn_block = re.search(
        r"차례: \S+ ────[\s\S]{0,900}?내 패[\s\S]{0,400}?\[공개\]", out2)
    checks.append(("C2 턴 화면에 [공개] 표시", turn_block is not None))
    # '선택중' 줄 들여쓰기(앞 3칸) + 위 줄과 빈 줄 간격
    indent_ok = ("   ⏳ 알파 님이 선택중" in out2
                 or "   ⏳ 베타 님이 선택중" in out2)
    checks.append(("C2 '선택중' 줄 들여쓰기", indent_ok))
    gap_ok = re.search(r"\n\n   ⏳ \S+ 님이 선택중", out2) is not None
    checks.append(("C2 '선택중' 위 빈 줄 간격", gap_ok))

    print("[판정]")
    allok = True
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print("=" * 60)
    print("ALL PASS" if allok else "SOME FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
