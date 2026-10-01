# -*- coding: utf-8 -*-
"""참가하기(run_join)가 방 주소를 실제로 물어보는지 검증 (재빌드 전 확인용)."""
import io
import sys
import contextlib

sys.path.insert(0, r"C:\Suzuha\DavinciOnline")
import web_launcher as wl

FAIL = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  (" + str(extra) + ")") if extra else ""))
    if not cond:
        FAIL.append(name)

# ---- 1) 인자 없는 run_join: 주소/포트/브라우저포트를 물어봐야 한다 -----------
calls = []
def fake_input(prompt=""):
    calls.append(prompt)
    if "방 주소" in prompt:
        return "192.168.0.49"
    if "게임 포트" in prompt:
        return ""
    if "브라우저 포트" in prompt:
        return ""
    return ""

captured = {}
def fake_open_web(host, port, web_port, name=None, web_host="127.0.0.1", open_browser=True):
    captured.update(host=host, port=port, web_port=web_port,
                    web_host=web_host, open_browser=open_browser)
    return 0

real_input = wl.input if hasattr(wl, "input") else None
wl.input = fake_input
wl._open_web = fake_open_web
wl._pause_before_exit = lambda: None

out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = wl.run_join([])

check("run_join 이 방 주소를 물어봄", any("방 주소" in p for p in calls), calls[:1])
check("입력한 주소가 그대로 반영됨 (192.168.0.49)", captured.get("host") == "192.168.0.49", captured.get("host"))
check("127.0.0.1 로 덮어쓰지 않음", captured.get("host") != "127.0.0.1")
check("게임 포트도 물어봄", any("게임 포트" in p for p in calls))
check("접속 안내가 입력 주소로 출력", "192.168.0.49" in out.getvalue(), out.getvalue().strip().splitlines()[-2:])

# ---- 2) 인자로 준 주소는 물어보지 않고 그대로 써야 한다 ---------------------
calls.clear(); captured.clear()
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_join(["10.0.0.7", "--port", "9001", "--web-port", "8123", "--no-browser"])

check("인자 주소면 질문 생략", not any("방 주소" in p for p in calls), calls)
check("인자 주소 반영 (10.0.0.7)", captured.get("host") == "10.0.0.7", captured.get("host"))
check("--port 반영 (9001)", captured.get("port") == 9001, captured.get("port"))
check("--web-port 반영 (8123)", captured.get("web_port") == 8123, captured.get("web_port"))
check("--no-browser 반영", captured.get("open_browser") is False, captured.get("open_browser"))

# ---- 3) 기본값(Enter) 이면 127.0.0.1 로 폴백 ---------------------------------
calls.clear(); captured.clear()
def blank_input(prompt=""):
    calls.append(prompt)
    return ""            # 전부 Enter 만 누른 상황
wl.input = blank_input
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_join([])
check("Enter 만 누르면 기본 127.0.0.1", captured.get("host") == "127.0.0.1", captured.get("host"))

wl.input = real_input

print()
print(("=" * 46))
print("RESULT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAIL -> {FAIL}")
print("=" * 46)
sys.exit(1 if FAIL else 0)
