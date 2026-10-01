# -*- coding: utf-8 -*-
"""web_launcher 검증.

확인:
  1) 메뉴 배너에 3개 메뉴가 있다
  2) 주소 검증(_valid_host) 이 IPv4/호스트명을 정확히 판정
  3) [1] 혼자 해보기 — relay+웹서버가 실제로 뜨고 /api/state 가 응답
  4) [3] 참가하기 — 밖에서 띄운 relay 에 붙어 /api/state 가 응답
  5) exe 자산 경로 — web_server 의 HERE 가 frozen 일 때 _MEIPASS 를 쓰는지
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import testutil          # noqa: E402
import web_launcher as W  # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + name +
          ("  (" + str(extra) + ")" if extra else ""))
    if not cond:
        fails.append(name)


def _http(port, path="/"):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=6) as r:
        return r.read().decode("utf-8", "replace")


def _fake_web(kwargs, holder):
    """_open_web 대체 — 브라우저 자동실행을 끄고 스레드로 띄운다."""
    orig = holder["orig"]

    def run():
        orig(kwargs["host"], kwargs["port"], kwargs["web_port"],
             name=kwargs.get("name"), web_host=kwargs.get("web_host", "127.0.0.1"),
             open_browser=False)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return 0


def main():
    # ---------------------------------------------------------- 1)
    print("== 1) 메뉴 ==")
    for label in ("[1] 혼자 해보기", "[2] 방 만들기", "[3] 참가하기", "[0] 종료"):
        chk(f"배너에 {label}", label in W.BANNER)

    # ---------------------------------------------------------- 2)
    print("\n== 2) 주소 검증 ==")
    oks = ["127.0.0.1", "192.168.0.49", "0.tcp.ngrok.io", "my-host.local"]
    bads = ["", "abc", "1.2.3", "999.1.1.1", "1.2.3.4 5", "-a.b", "a..b", "..."]
    for s in oks:
        chk(f"허용: {s!r}", W._valid_host(s) is True)
    for s in bads:
        chk(f"거부: {s!r}", W._valid_host(s) is False)

    # ---------------------------------------------------------- 3)
    print("\n== 3) [1] 혼자 해보기 (relay + 웹서버) ==")
    testutil.free_port(W.DEFAULT_PORT)
    testutil.free_port(8101)
    holder = {"orig": W._open_web}
    W._open_web = lambda host, port, web_port, name=None, web_host="127.0.0.1", \
        open_browser=True: _fake_web(
            dict(host=host, port=port, web_port=web_port, name=name,
                 web_host=web_host), holder)
    answers = iter(["2", "8101"])       # 인원 2, 브라우저 포트 8101
    W.input = lambda prompt="", *a, **k: next(answers, "")
    rc = W.run_solo([])
    time.sleep(2.5)
    try:
        html = _http(8101, "/")
        st = _http(8101, "/api/state")
        chk("[1] rc == 0", rc == 0, rc)
        chk("[1] HTML 응답", "다빈치" in html, len(html))
        chk("[1] /api/state 응답", st.startswith("{"), len(st))
    except Exception as e:
        chk("[1] 웹서버 응답", False, f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------- 4)
    print("\n== 4) [3] 참가하기 (밖의 relay 에 접속) ==")
    testutil.free_port(8766)
    testutil.free_port(8102)
    env = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0")
    for k in ("PYTHONHOME", "PYTHONPATH", "AUTOHUMAN"):
        env.pop(k, None)
    relay = subprocess.Popen(
        [sys.executable, "-E", "-u", "relay.py", "2", "--cpu", "1",
         "--port", "8766"],
        cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(2.5)
    try:
        answers = iter(["127.0.0.1", "8766", "8102"])
        W.input = lambda prompt="", *a, **k: next(answers, "")
        rc = W.run_join([])
        time.sleep(2.5)
        st = _http(8102, "/api/state")
        chk("[3] rc == 0", rc == 0, rc)
        chk("[3] /api/state 응답", st.startswith("{"), len(st))
    except Exception as e:
        chk("[3] 접속", False, f"{type(e).__name__}: {e}")
    finally:
        relay.terminate()

    # ---------------------------------------------------------- 5)
    print("\n== 5) exe 자산 경로 처리 ==")
    src = open(os.path.join(HERE, "web_server.py"), encoding="utf-8").read()
    chk("web_server 가 _MEIPASS 폴백을 쓴다", "_MEIPASS" in src)
    chk("web_server 가 --web-host 옵션을 받는다", "--web-host" in src)
    print()

    print("=" * 50)
    print("ALL PASS ✅" if not fails else f"FAIL ({len(fails)}개)")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
