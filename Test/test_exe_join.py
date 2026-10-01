# -*- coding: utf-8 -*-
"""새 exe 의 [3] 참가하기 가 방 주소를 실제로 물어보는지 확인.

exe 에 stdin 을 흘려보내고 stdout 을 읽어 판정한다.
'방 주소' 질문이 나오고, 입력한 IP 가 접속 안내에 그대로 찍히면 PASS.
"""
import subprocess
import sys
import time

EXE = r"C:\Suzuha\DavinciOnline\dist\다빈치코드_웹.exe"

FAIL = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  (" + str(extra) + ")") if extra else ""))
    if not cond:
        FAIL.append(name)

# 메뉴에서 3 → 방 주소 192.168.0.49 → 게임포트 Enter → 브라우저포트 Enter
# 브라우저 자동 실행이 됐다면 그 창은 곧 닫는다.
stdin_data = "3\n192.168.0.49\n\n\n"
p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                     errors="replace", bufsize=1)

try:
    p.stdin.write(stdin_data)
    p.stdin.flush()
except Exception as e:
    print("stdin write err:", e)

time.sleep(14)          # 웹서버 기동 + 안내 출력까지 대기
try:
    p.stdin.write("\n")
    p.stdin.flush()
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
if not out:
    try:
        out = p.communicate(timeout=5)[0] or ""
    except Exception:
        pass

print("---- exe 출력 (마지막 30줄) ----")
for line in out.strip().splitlines()[-30:]:
    print("   " + line)
print("-" * 40)

check("exe 가 '방 주소' 를 물어봄", "방 주소" in out)
check("입력한 192.168.0.49 가 접속 안내에 반영",
      "192.168.0.49" in out,
      [l for l in out.splitlines() if "에 접속합니다" in l][:1])
check("[3] 참가하기 배너 진입", "참가하기" in out)

print()
print("=" * 46)
print("RESULT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAIL -> {FAIL}")
print("=" * 46)
sys.exit(1 if FAIL else 0)
