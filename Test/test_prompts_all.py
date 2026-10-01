# -*- coding: utf-8 -*-
"""터미널 환경이 아니어도 빠진 값은 반드시 물어보는지 검증.

핵심: argv 가 있어도 **넘기지 않은 값은 질문**해야 한다.
특히 [2] 방 만들기에서 CPU 수를 반드시 물어봐야 한다.
"""
import io
import sys
import contextlib

sys.path.insert(0, r"C:\Suzuha\DavinciOnline")
import web_launcher as wl

FAIL = []
def check(name, cond, extra=""):
    extra = str(extra)
    if len(extra) > 120:
        extra = extra[:120] + "..."
    print(("PASS  " if cond else "FAIL  ") + name + (("  (" + extra + ")") if extra else ""))
    if not cond:
        FAIL.append(name)

captured = {}
def fake_open_web(host, port, web_port, name=None, web_host="127.0.0.1", open_browser=True):
    captured.update(host=host, port=port, web_port=web_port,
                    web_host=web_host, open_browser=open_browser)
    return 0

def fake_relay(players, cpu, port):
    captured.update(players=players, cpu=cpu)
    return object()

wl._open_web = fake_open_web
wl._start_relay = fake_relay
wl._wait_port = lambda *a, **k: True
wl._pause_before_exit = lambda: None


class Recorder:
    """프롬프트 키워드 -> 응답 매핑. 프롬프트를 정확한 순서로 기록."""
    def __init__(self, mapping):
        self.mapping = mapping
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        # 가장 구체적인(긴) 키워드 우선 매칭
        for key in sorted(self.mapping, key=len, reverse=True):
            if key in prompt:
                return self.mapping[key]
        return ""

    def asked(self, key):
        return any(key in p for p in self.prompts)


# ============ 1) host, 인자 없음 → 인원·CPU·포트 전부 질문 ============
rec = Recorder({"인원": "4", "CPU": "2", "브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_host([])

check("★ 방 만들기에서 CPU 수를 물어봄", rec.asked("CPU"), rec.prompts)
check("인원도 물어봄", rec.asked("인원"))
check("브라우저 포트도 물어봄", rec.asked("브라우저"))
check("입력한 인원 4 반영", captured.get("players") == 4, captured.get("players"))
check("입력한 CPU 2 반영", captured.get("cpu") == 2, captured.get("cpu"))

# ====== 2) host, 인원만 인자 → CPU 는 여전히 질문 ======
rec = Recorder({"CPU": "1", "브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_host(["4"])

check("★ 인자로 인원을 줘도 CPU 는 질문함", rec.asked("CPU"), rec.prompts)
check("질문에 0~3 범위 표시", any("0~3" in p for p in rec.prompts), rec.prompts)
check("CPU 1 반영", captured.get("cpu") == 1, captured.get("cpu"))

# ====== 3) host, CPU 까지 인자 → 질문 없이 진행 ======
rec = Recorder({"브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_host(["3", "--cpu", "2"])

check("인자로 다 주면 CPU 질문 생략", not rec.asked("CPU"), rec.prompts)
check("CPU 2 반영", captured.get("cpu") == 2, captured.get("cpu"))

# ====== 4) host, Enter 로만 → 기본값 0 ======
rec = Recorder({"브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_host([])
check("CPU Enter 만 → 기본 0", captured.get("cpu") == 0, captured.get("cpu"))

# ====== 5) solo, 인자 없음 → 인원 질문, CPU = 인원-1 ======
rec = Recorder({"인원": "3", "브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_solo([])
check("solo 도 인원을 물어봄", rec.asked("인원"), rec.prompts)
check("solo 인원 3 → CPU 2", captured.get("cpu") == 2, captured.get("cpu"))

# ====== 6) join, 인자 없음 → 주소·게임포트·브라우저포트 질문 ======
rec = Recorder({"방 주소": "192.168.0.49", "게임 포트": "", "브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_join([])
check("join 이 방 주소를 물어봄", rec.asked("방 주소"), rec.prompts)
check("join 이 게임 포트도 물어봄", rec.asked("게임 포트"), rec.prompts)
check("join 주소 반영", captured.get("host") == "192.168.0.49", captured.get("host"))

# ====== 7) join, 주소만 인자 → 포트는 질문 ======
rec = Recorder({"게임 포트": "9001", "브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_join(["10.0.0.7"])
check("인자 주소면 주소는 안 물어봄", not rec.asked("방 주소"), rec.prompts)
check("게임 포트는 물어봄", rec.asked("게임 포트"), rec.prompts)
check("게임 포트 9001 반영", captured.get("port") == 9001, captured.get("port"))

# ====== 8) join, --port 인자 → 질문 생략 ======
rec = Recorder({"브라우저": ""})
captured.clear()
wl.input = rec
with contextlib.redirect_stdout(io.StringIO()):
    wl.run_join(["10.0.0.7", "--port", "9001"])
check("--port 주면 게임포트 질문 생략", not rec.asked("게임 포트"), rec.prompts)
check("--port 9001 반영", captured.get("port") == 9001, captured.get("port"))

print()
print("=" * 50)
print("RESULT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAIL -> {FAIL}")
print("=" * 50)
sys.exit(1 if FAIL else 0)
