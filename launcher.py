# -*- coding: utf-8 -*-
"""다빈치 코드 — 통합 런처 (exe 진입점).

하나의 실행 파일로 서버/참가/시연을 모두 고를 수 있게 해주는 메뉴.

    [1] 서버 열기      → relay.py  (게임 상태 보유, 참가자 대기)
    [2] 참가하기       → client.py (서버에 접속해 플레이)
    [3] 혼자 해보기    → run_game.py (CPU와 1인 플레이, 연습용)
    [0] 종료

명령줄 인자로 바로 실행할 수도 있다 (서버 자동화/스크립트용):

    launcher.py server 3 --cpu 1     ← [1] 서버, 인원 3, CPU 1
    launcher.py client --host 1.2.3.4
    launcher.py demo

※ exe 로 묶으면(더블클릭) 인자가 없으므로 메뉴가 뜬다.
"""

import os
import sys

# PyInstaller onefile 로 묶으면 모듈 파일들이 임시 폴더에 풀린다.
# 같은 폴더의 relay/client/run_game 을 임포트하려면 그 경로가 sys.path 에 있어야 한다.
if getattr(sys, "frozen", False):
    _BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)

# ★ exe 는 stdout 이 파이프/리다이렉트되면 완전 버퍼링(8KB)이 되어
#   프롬프트/배너가 화면에 안 나온다. line buffering 강제로 즉시 출력.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass


BANNER = """\
====================================================
   다빈치 코드 (Davinci Code) — 통합 런처
====================================================
   [1] 서버 열기      (내가 방장 — 참가자 기다림)
   [2] 참가하기       (방장 서버에 접속해 플레이)
   [3] 혼자 해보기    (CPU와 1인 연습)
   [0] 종료
----------------------------------------------------"""


# ---------------------------------------------------------------------------
# ★ 입력 헬퍼 (launcher.py 와 web_launcher.py 에 동일하게 복제돼 있다)
#   - 두 런처가 각각 독립 exe 로 빌드되므로 의도적으로 중복을 유지한다.
#   - ★ 수정 시 반드시 양쪽을 같이 고칠 것! (한쪽만 고치면 동작이 어긋난다)
#     대상: _ask_int, _ask_text, _valid_host, _ask_host, _pause_before_exit
# ---------------------------------------------------------------------------
def _ask_int(prompt, default, lo, hi, tries=10):
    """정수 하나를 안전하게 입력받는다. 실패하면 기본값."""
    for _ in range(tries):
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if raw == "":
            return default
        try:
            v = int(raw)
        except ValueError:
            print(f"   [!] 숫자를 입력하세요 ({lo}~{hi}).")
            continue
        if not (lo <= v <= hi):
            print(f"   [!] {lo}~{hi} 사이로 입력하세요.")
            continue
        return v
    print(f"   [!] 입력이 계속 잘못되어 기본값 {default} 을(를) 사용합니다.")
    return default


def _ask_text(prompt, default=""):
    """문자열 하나를 입력받는다 (빈 입력이면 기본값)."""
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return raw if raw else default


def _valid_host(s):
    """접속 주소 검증 — IPv4(192.168.0.10) 또는 호스트명(예: 0.tcp.ngrok.io).

    거부: 빈 값, 공백 포함, 허용되지 않은 문자, 잘못된 IPv4 옥텟.
    """
    s = s.strip()
    if not s or any(ch.isspace() for ch in s):
        return False
    # 허용 문자: 영숫자, 점, 하이픈 (호스트명/IPv4 규칙)
    if not all(ch.isalnum() or ch in ".-" for ch in s):
        return False
    # 점으로만 이루어졌거나 하이픈이 양끝이면 거부
    if set(s) <= {".", "-"}:
        return False
    if s.startswith("-") or s.endswith("-"):
        return False
    # 숫자+점으로만 되어 있으면 IPv4 로 검사
    if all(ch.isdigit() or ch == "." for ch in s):
        parts = s.split(".")
        if len(parts) != 4:
            return False
        for p in parts:
            if not p.isdigit() or not (0 <= int(p) <= 255):
                return False
        return True
    # 호스트명 검사 — 각 라벨이 영숫자로 시작/끝나야 하고 '-.' 만 사이에 허용
    for label in s.split("."):
        if not label:
            return False                       # 빈 라벨(예: a..b 는 허용하되 아래 조정)
        if not (label[0].isalnum() and label[-1].isalnum()):
            return False
    # 호스트명이면 점이 최소 1개 있어야 (예: ngrok.io)
    return "." in s


def _ask_host(prompt, default="127.0.0.1"):
    """서버 IP/호스트명을 검증하며 입력받는다. 잘못되면 재질문."""
    for _ in range(10):
        val = _ask_text(prompt, default)
        if _valid_host(val):
            return val
        print("   [!] 올바른 IP 또는 주소가 아닙니다. "
              "예) 127.0.0.1 / 192.168.0.10 / 0.tcp.ngrok.io")
    print(f"   [!] 입력이 계속 잘못되어 기본값 {default} 을(를) 사용합니다.")
    return default


# ---------------------------------------------------------------- 서버
def run_server(argv):
    print("\n---- 서버 설정 ----")
    players = _ask_int("인원 (2~4, Enter=2) : ", 2, 2, 4)
    max_cpu = players - 1
    cpu = _ask_int(
        f"CPU(자동) 좌석 수 (0~{max_cpu}, Enter=0) : ", 0, 0, max_cpu
    )
    port = _ask_int("포트 (Enter=8765) : ", 8765, 1, 65535)

    args = [str(players), "--cpu", str(cpu), "--port", str(port)]
    import relay
    return relay.main(args)


# ---------------------------------------------------------------- 참가
def run_client(argv):
    print("\n---- 참가 설정 ----")
    host = _ask_host("서버 IP (Enter=127.0.0.1, 같은 PC) : ", "127.0.0.1")
    port = _ask_int("포트 (Enter=8765) : ", 8765, 1, 65535)
    name = _ask_text("내 이름 (Enter=기본) : ", "")

    args = ["--host", host, "--port", str(port)]
    if name:
        args += ["--name", name]
    import client
    return client.main(args)


# ---------------------------------------------------------------- 시연
def run_demo(argv):
    """[3] 혼자 해보기 — CPU와 1인 연습 (인원만 물어봄)."""
    print("\n---- 혼자 해보기 ----")
    players = _ask_int("인원 (2~4, Enter=2) : ", 2, 2, 4)
    import run_game
    return run_game.main(players)


# ---------------------------------------------------------------- 메뉴
def _pause_before_exit():
    """exe(더블클릭) 실행 시 결과를 읽을 수 있게 Enter 를 기다린다.

    ★ 이유: exe 는 창이 곧 프로세스라, 게임/서버가 끝나면 콘솔이 그대로 닫혀
    결과 화면을 볼 수 없다. python 실행(개발/테스트)에서는 대기하지 않는다.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        input("\n[Enter] 를 누르면 종료합니다... ")
    except (EOFError, KeyboardInterrupt):
        pass


def menu():
    print(BANNER)
    for _ in range(10):
        try:
            choice = input("선택 [1/2/3/0] : ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0                                                     # noqa: E501
        if choice == "":
            continue
        if choice == "1":
            rc = run_server([])
            _pause_before_exit()
            return rc
        if choice == "2":
            rc = run_client([])
            _pause_before_exit()
            return rc
        if choice == "3":
            rc = run_demo([])
            _pause_before_exit()
            return rc
        if choice == "0":
            return 0
        print("   [!] 1 / 2 / 3 / 0 중에서 고르세요.")
    print("   [!] 입력이 계속 잘못되어 종료합니다.")
    _pause_before_exit()
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        return menu()
    cmd = argv[0].lower()
    rest = argv[1:]
    if cmd in ("server", "s", "1"):
        rc = run_server(rest)
        _pause_before_exit()
        return rc
    if cmd in ("client", "c", "join", "2"):
        rc = run_client(rest)
        _pause_before_exit()
        return rc
    if cmd in ("demo", "d", "play", "3"):
        rc = run_demo(rest)
        _pause_before_exit()
        return rc
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    # 알 수 없는 인자면 도움말
    print(f"[!] 알 수 없는 명령: {argv[0]}")
    print(__doc__)
    _pause_before_exit()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
