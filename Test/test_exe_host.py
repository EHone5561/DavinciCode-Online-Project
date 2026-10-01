# -*- coding: utf-8 -*-
"""새 exe 에서 [2] 방 만들기가 CPU 수를 실제로 물어보는지 확인."""
import subprocess
import sys
import time

EXE = r"C:\Suzuha\DavinciOnline\dist\다빈치코드_웹.exe"

FAIL = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  (" + str(extra) + ")") if extra else ""))
    if not cond:
        FAIL.append(name)

# 메뉴 2 → 인원 4 → CPU 2 → 브라우저포트 Enter
p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                     errors="replace", bufsize=1)
try:
    p.stdin.write("2\n4\n2\n\n")
    p.stdin.flush()
except Exception as e:
    print("stdin err:", e)

time.sleep(16)
try:
    p.stdin.write("\n"); p.stdin.flush()
except Exception:
    pass
time.sleep(2)
try:
    p.kill()
except Exception:
    pass

out = ""
try:
    out = p.stdout.read() or ""
except Exception:
    pass

print("---- exe 출력 (마지막 32줄) ----")
for line in out.strip().splitlines()[-32:]:
    print("   " + line)
print("-" * 44)

check("★ exe [2] 에서 'CPU' 를 물어봄", "CPU" in out)
check("CPU 범위 0~3 표시 (인원 4 입력 후)", "0~3" in out)
check("인원도 물어봄", "인원" in out)
check("브라우저 포트도 물어봄", "브라우저 포트" in out)
check("CPU 2 반영 (인원 4, CPU 2)", "인원 4, CPU 2" in out,
      [l for l in out.splitlines() if "게임 서버를 시작" in l][:1])

print()
print("=" * 46)
print("RESULT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAIL -> {FAIL}")
print("=" * 46)
sys.exit(1 if FAIL else 0)
