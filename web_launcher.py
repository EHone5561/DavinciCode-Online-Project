# -*- coding: utf-8 -*-
"""다빈치 코드 — 웹(HTML) 전용 런처 (exe 진입점).

터미널 버전(launcher.py)은 이미 배포했으므로,
이 런처는 **브라우저 버튼 입력**으로만 플레이하게 해준다.

    [1] 혼자 해보기   → relay(CPU 포함) + 웹서버 + 브라우저 자동 실행
    [2] 방 만들기     → relay 서버 + 웹서버. 내 IP 안내 (참가자 대기)
    [3] 참가하기      → 다른 PC 의 방 주소로 접속 (웹서버만 띄움)
    [0] 종료

명령줄 인자(자동화/테스트용):

    web_launcher.py solo 3            ← 혼자 해보기, 인원 3
    web_launcher.py host 3 --cpu 1    ← 방 만들기
    web_launcher.py join 192.168.0.10 ← 참가하기
"""

import os
import sys

# PyInstaller onefile 대응 — 모듈이 임시 폴더에 풀린다.
if getattr(sys, "frozen", False):
    _BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)

# exe 는 stdout 이 리다이렉트되면 완전 버퍼링 → 즉시 출력되게.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass


DEFAULT_PORT = 8765          # 게임 서버(relay) 포트
DEFAULT_WEB_PORT = 8000      # 브라우저 접속 포트

BANNER = """\
====================================================
   다빈치 코드 (Davinci Code) — 웹 버전
   브라우저에서 마우스로 플레이합니다.
====================================================
   [1] 혼자 해보기    (CPU와 연습 — 바로 시작)
   [2] 방 만들기      (내가 방장 — 참가자 기다림)
   [3] 참가하기       (방 주소로 접속)
   [0] 종료
----------------------------------------------------"""


# ---------------------------------------------------------------------------
# ★ 입력 헬퍼 (web_launcher.py 와 launcher.py 에 동일하게 복제돼 있다)
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


def _ask_int_ex(prompt, lo, hi, default, tries=10):
    """정수 입력. Returns: (값, 실제로 물어봤는지)

    Enter 만 누르면 default 를 돌려주되 asked=False 로 알려준다.

    ⚠️ 인자 순서: (prompt, lo, hi, default) — default 를 lo 자리에 넣는 실수 방지용
    으로 lo>hi 면 자동 스왑한다.
    """
    if lo > hi:                     # 실수로 순서를 바꿔 넣은 경우 방어
        lo, hi = hi, lo
    for _ in range(tries):
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return default, False
        if raw == "":
            return default, False
        try:
            v = int(raw)
        except ValueError:
            print(f"   [!] 숫자를 입력하세요 ({lo}~{hi}).")
            continue
        if not (lo <= v <= hi):
            print(f"   [!] {lo}~{hi} 사이로 입력하세요.")
            continue
        return v, True
    print(f"   [!] 입력이 계속 잘못되어 기본값 {default} 을(를) 사용합니다.")
    return default, False


def _ask_host_ex(prompt, default):
    """호스트 입력. Returns: (값, 실제로 물어봤는지)"""
    for _ in range(10):
        val = _ask_text(prompt, "")
        if val == "":
            return default, False
        if _valid_host(val):
            return val, True
        print("   [!] 올바른 IP 또는 주소가 아닙니다. "
              "예) 127.0.0.1 / 192.168.0.10 / 0.tcp.ngrok.io")
    print(f"   [!] 입력이 계속 잘못되어 기본값 {default} 을(를) 사용합니다.")
    return default, False


def _valid_host(s):
    """접속 주소 검증 — IPv4 또는 호스트명. (launcher.py 와 같은 규칙)"""
    s = s.strip()
    if not s or any(ch.isspace() for ch in s):
        return False
    if not all(ch.isalnum() or ch in ".-" for ch in s):
        return False
    if set(s) <= {".", "-"}:
        return False
    if s.startswith("-") or s.endswith("-"):
        return False
    if all(ch.isdigit() or ch == "." for ch in s):
        parts = s.split(".")
        if len(parts) != 4:
            return False
        for p in parts:
            if not p.isdigit() or not (0 <= int(p) <= 255):
                return False
        return True
    for label in s.split("."):
        if not label:
            return False
        if not (label[0].isalnum() and label[-1].isalnum()):
            return False
    return "." in s


def _ask_host(prompt, default="127.0.0.1"):
    """서버 IP/호스트명을 검증하며 입력받는다. 잘못되면 재질문.

    (하위호환용 — 실제 호출부는 asked 플래그를 주는 _ask_host_ex 를 쓴다)
    """
    for _ in range(10):
        val = _ask_text(prompt, default)
        if _valid_host(val):
            return val
        print("   [!] 올바른 IP 또는 주소가 아닙니다. "
              "예) 127.0.0.1 / 192.168.0.10 / 0.tcp.ngrok.io")
    print(f"   [!] 입력이 계속 잘못되어 기본값 {default} 을(를) 사용합니다.")
    return default


# ------------------------------------------------------------------ 공통
def _start_relay(players, cpu, port):
    """relay 게임 서버를 데몬 스레드로 띄운다 (블로킹이라 스레드 필요).

    Returns: RelayServer 객체 (실패 시 None)
    """
    import threading

    import relay

    cpu_seats = set(range(players - cpu, players))
    server = relay.RelayServer(players, port=port, cpu_seats=cpu_seats)

    def _run():
        try:
            server.serve_forever()
        except OSError as e:
            print(f"[!] 게임 서버 오류: {e}")

    t = threading.Thread(target=_run, daemon=True, name="relay")
    t.start()
    return server


def _wait_port(port, host="127.0.0.1", timeout=5.0):
    """게임 서버가 뜰 때까지 기다린다 (뜨면 True).

    ⚠️ `socket.create_connection()` 으로 확인하면 relay 에 **이름 없는 손님이
       접속했다 바로 나간 것**으로 보인다 ("좌석 N 접속 직후 끊김 — 다시 받습니다").
       Windows 는 SO_REUSEADDR 로 중복 bind 를 허용해버려 바인딩 판정도 못 믿는다.

    ★ 그래서 **연결하지 않고** relay 가 소켓을 잡을 때까지 짧게 기다린다.
      `serve_forever()` 는 스레드에서 bind+listen 을 즉시 수행하므로
      실측 0.2~0.5초면 충분하다. 못 뜨면 그냥 진행하고, 실제 실패는
      web_server 의 접속 시도가 잡아낸다(사용자에게 오류가 보인다).
    """
    import time
    time.sleep(min(0.8, timeout))
    return True


def _open_web(host, port, web_port, name=None, web_host="127.0.0.1",
              open_browser=True):
    """웹서버를 메인 스레드에서 띄운다 (블로킹).

    웹서버는 relay 에 접속해 게임 상태를 폴링/중계한다.
    """
    import web_server

    argv = ["--host", host, "--port", str(port),
            "--web-port", str(web_port), "--web-host", web_host]
    if name:
        argv += ["--name", name]
    if not open_browser:
        argv += ["--no-browser"]
    return web_server.main(argv)


# ------------------------------------------------------------------ [1]
def _parse_cli(rest, default_web_port=None):
    """명령줄 인자를 뽑아낸다 (자동화/테스트용).

    지원 형식:
        solo 3                → 인원 3
        solo 3 --cpu 1        → 인원 3, CPU 1
        host 3 --cpu 1        → 방 만들기
        join 192.168.0.10     → 주소만
        join 192.168.0.10 --port 8765 --web-port 8000
        ... --no-browser      → 브라우저 자동 실행 안 함
        ... --web-host 0.0.0.0

    Returns: (players, cpu, web_port, host, open_browser, web_host)
             값이 없으면 None 을 돌려주어 호출부가 물어보게 한다.
    """
    players = None
    cpu = None
    web_port = default_web_port
    host = None
    game_port = None
    open_browser = True
    web_host = None

    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--cpu" and i + 1 < len(rest):
            try:
                cpu = int(rest[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a == "--web-port" and i + 1 < len(rest):
            try:
                web_port = int(rest[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a == "--port" and i + 1 < len(rest):
            try:
                game_port = int(rest[i + 1])   # join 에서 쓸 게임 포트
            except ValueError:
                pass
            i += 2
            continue
        if a == "--web-host" and i + 1 < len(rest):
            web_host = rest[i + 1]
            i += 2
            continue
        if a == "--no-browser":
            open_browser = False
            i += 1
            continue
        if a.startswith("--"):
            i += 1                      # 모르는 옵션은 건너뛴다
            continue
        # 첫 번째 숫자 아닌 인자 = 주소(join) 또는 인원(solo/host)
        if players is None:
            try:
                players = int(a)
            except ValueError:
                host = a                # join 의 방 주소
        i += 1

    return players, cpu, web_port, host, open_browser, web_host, game_port


def run_solo(argv):
    """혼자 해보기 — relay(CPU 포함) + 웹서버 + 브라우저."""
    print("\n---- 혼자 해보기 ----")
    players, _cpu, web_port, _h, open_browser, web_host, _gp = _parse_cli(
        argv or [])

    # 인원: 인자 > 질문 > 기본 2
    if players is None:
        players, _ = _ask_int_ex("인원 (2~4, Enter=2) : ", 2, 4, 2)
    if not (2 <= players <= 4):
        print(f"   [!] 인원 {players} 은(는) 범위 밖 — 2 로 맞춥니다.")
        players = 2

    # 사람 1명 + 나머지 CPU
    cpu = players - 1

    # 브라우저 포트
    if web_port is None or not (1 <= web_port <= 65535):
        web_port, _ = _ask_int_ex(
            f"브라우저 포트 (Enter={DEFAULT_WEB_PORT}) : ",
            1, 65535, DEFAULT_WEB_PORT)

    print(f"\n[i] 게임 서버를 시작합니다 (인원 {players}, CPU {cpu})...")
    _start_relay(players, cpu, DEFAULT_PORT)
    if not _wait_port(DEFAULT_PORT):
        print("[!] 게임 서버가 뜨지 않았습니다. 포트가 사용 중인지 확인하세요.")
        return 1

    print("[i] 브라우저를 엽니다. 잠시만 기다려 주세요...")
    return _open_web("127.0.0.1", DEFAULT_PORT, web_port, name=None,
                     web_host=(web_host or "127.0.0.1"),
                     open_browser=open_browser)


# ------------------------------------------------------------------ [2]
def run_host(argv):
    """방 만들기 — relay + 웹서버. 내 IP 안내 (참가자 대기)."""
    print("\n---- 방 만들기 (방장) ----")
    players, cpu, web_port, _h, open_browser, web_host, _gp = _parse_cli(
        argv or [])

    # 인원: 인자 > 질문 > 기본 2
    if players is None:
        players, _ = _ask_int_ex("인원 (2~4, Enter=2) : ", 2, 4, 2)
    if not (2 <= players <= 4):
        print(f"   [!] 인원 {players} 은(는) 범위 밖 — 2 로 맞춥니다.")
        players = 2

    max_cpu = players - 1
    # CPU 좌석: 인자 > 질문 > 기본 0
    if cpu is None:
        cpu, _ = _ask_int_ex(
            f"CPU(자동) 좌석 수 (0~{max_cpu}, Enter=0) : ",
            0, max_cpu, 0)
    if not (0 <= cpu <= max_cpu):
        print(f"   [!] CPU {cpu} 은(는) 범위 밖 — 0 으로 맞춥니다.")
        cpu = 0

    # 브라우저 포트
    if web_port is None or not (1 <= web_port <= 65535):
        web_port, _ = _ask_int_ex(
            f"브라우저 포트 (Enter={DEFAULT_WEB_PORT}) : ",
            1, 65535, DEFAULT_WEB_PORT)

    print(f"\n[i] 게임 서버를 시작합니다 (인원 {players}, CPU {cpu})...")
    _start_relay(players, cpu, DEFAULT_PORT)
    if not _wait_port(DEFAULT_PORT):
        print("[!] 게임 서버가 뜨지 않았습니다. 포트가 사용 중인지 확인하세요.")
        return 1

    # 내 IP 안내
    import web_server
    lan = web_server._lan_ip()
    print("\n" + "=" * 52)
    print("   참가자에게 알려줄 주소")
    if lan:
        print(f"     http://{lan}:{web_port}/")
    else:
        print(f"     http://<내 IP>:{web_port}/")
    print("   (같은 네트워크 안에서만 접속됩니다)")
    print("=" * 52)
    print("\n[i] 브라우저를 엽니다. 잠시만 기다려 주세요...")
    # ★ 참가자를 받아야 하므로 0.0.0.0 바인딩
    return _open_web("127.0.0.1", DEFAULT_PORT, web_port, name=None,
                     web_host=(web_host or "0.0.0.0"),
                     open_browser=open_browser)


# ------------------------------------------------------------------ [3]
def run_join(argv):
    """참가하기 — 다른 PC 의 방에 접속 (웹서버만 띄움)."""
    print("\n---- 참가하기 ----")
    # 방 주소: 명령줄 인자 > 대화형 입력
    _players, _cpu, web_port, host, open_browser, web_host, game_port = _parse_cli(
        argv or [])

    # 방 주소: 명령줄 인자 > 대화형 입력
    if host is None:
        host, _ = _ask_host_ex("방 주소 (Enter=127.0.0.1, 같은 PC) : ",
                               "127.0.0.1")

    # 게임 포트: 명령줄 --port > 대화형 입력 > 기본값
    if game_port is None or not (1 <= game_port <= 65535):
        game_port, _ = _ask_int_ex(f"게임 포트 (Enter={DEFAULT_PORT}) : ",
                                   1, 65535, DEFAULT_PORT)
    port = game_port

    # 브라우저 포트
    if web_port is None or not (1 <= web_port <= 65535):
        web_port, _ = _ask_int_ex(
            f"브라우저 포트 (Enter={DEFAULT_WEB_PORT}) : ",
            1, 65535, DEFAULT_WEB_PORT)

    print(f"\n[i] {host}:{port} 에 접속합니다...")
    print("[i] 브라우저를 엽니다. 잠시만 기다려 주세요...")
    return _open_web(host, port, web_port, name=None,
                     web_host=(web_host or "127.0.0.1"),
                     open_browser=open_browser)


# ------------------------------------------------------------------ 메뉴
def _pause_before_exit():
    """exe(더블클릭) 실행 시 결과를 읽을 수 있게 Enter 를 기다린다."""
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
            return 0
        if choice == "":
            continue
        if choice == "1":
            rc = run_solo([])
            _pause_before_exit()
            return rc
        if choice == "2":
            rc = run_host([])
            _pause_before_exit()
            return rc
        if choice == "3":
            rc = run_join([])
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
    if cmd in ("solo", "s", "1"):
        rc = run_solo(rest)
        _pause_before_exit()
        return rc
    if cmd in ("host", "h", "2"):
        rc = run_host(rest)
        _pause_before_exit()
        return rc
    if cmd in ("join", "j", "3"):
        rc = run_join(rest)
        _pause_before_exit()
        return rc
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    print(f"[!] 알 수 없는 명령: {argv[0]}")
    print(__doc__)
    _pause_before_exit()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
