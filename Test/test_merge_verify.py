"""합친 버전 통합 검증 — 브라우저처럼 두 명이 접속해 다시하기까지.

검증 항목
---------
1. 웹 페이지가 뜬다
2. 두 명이 이름을 보내고 좌석을 받는다
3. snapshot 에 restart / game_id 키가 있다
4. /api/restart 로 투표가 전달된다
5. 전원 동의 시 game_id 가 증가한다 (브라우저 커서 리셋)

실행: python -E -X utf8 test_merge_verify.py
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
GAME_PORT = 8821
WEB_A = 8822
WEB_B = 8823


def _drain(pipe, sink):
    for line in iter(pipe.readline, b""):
        sink.append(line.decode("utf-8", "replace").rstrip())


def wait_http(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def post(port, path, obj):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    relay = wa = wb = None
    rl, wal, wbl = [], [], []
    results = []

    def chk(name, cond, extra=""):
        results.append((name, bool(cond), extra))

    try:
        # relay: 사람 2 + CPU 1
        relay = subprocess.Popen(
            [PY, "-E", "-u", "relay.py", "3", "--cpu", "1", "--port", str(GAME_PORT)],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=_drain, args=(relay.stdout, rl), daemon=True).start()
        time.sleep(1.8)

        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        for port, sink in ((WEB_A, wal), (WEB_B, wbl)):
            p = subprocess.Popen(
                [PY, "-E", "-u", "web_server.py", "--port", str(GAME_PORT),
                 "--web-port", str(port), "--no-browser"],
                cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            threading.Thread(target=_drain, args=(p.stdout, sink), daemon=True).start()
            if port == WEB_A:
                wa = p
            else:
                wb = p

        chk("웹 페이지 두 개가 뜬다", wait_http(WEB_A) and wait_http(WEB_B))

        post(WEB_A, "/api/name", {"text": "A"})
        post(WEB_B, "/api/name", {"text": "B"})
        time.sleep(2.0)

        sa, sb = get(WEB_A, "/api/state?since=0&chat_since=0"), \
                 get(WEB_B, "/api/state?since=0&chat_since=0")
        chk("A 좌석 배정 (seat 0)", sa.get("seat") == 0, f"seat={sa.get('seat')}")
        chk("B 좌석 배정 (seat 1)", sb.get("seat") == 1, f"seat={sb.get('seat')}")
        chk("snapshot 에 restart 키 존재", "restart" in sa)
        chk("snapshot 에 game_id 키 존재", "game_id" in sa)
        chk("초기 game_id = 0", sa.get("game_id") == 0, f"game_id={sa.get('game_id')}")

        # 게임 시작: 검은 카드 선택
        time.sleep(0.5)
        post(WEB_A, "/api/reply", {"text": "0"})
        post(WEB_B, "/api/reply", {"text": "0"})
        time.sleep(3.0)

        st = get(WEB_A, "/api/state?since=0&chat_since=0")
        chk("게임이 시작됨 (state 에 round 있음)",
            (st.get("state") or {}).get("round", 0) >= 1,
            f"round={(st.get('state') or {}).get('round')}")

        # ---- 게임을 빨리 끝내기: 계속 '그만'(q)으로 넘긴다 ----
        gid0 = st.get("game_id")
        deadline = time.time() + 120
        ended = False
        while time.time() < deadline:
            sa = get(WEB_A, "/api/state?since=0&chat_since=0")
            if sa.get("ended"):
                ended = True
                break
            ask = sa.get("ask") or {}
            if ask.get("mode"):
                post(WEB_A, "/api/reply", {"text": "q" if ask["mode"] == "guess" else "1"})
            sb = get(WEB_B, "/api/state?since=0&chat_since=0")
            askb = sb.get("ask") or {}
            if askb.get("mode"):
                post(WEB_B, "/api/reply", {"text": "q" if askb["mode"] == "guess" else "1"})
            time.sleep(0.25)

        chk("게임이 종료됨 (ended)", ended)

        # ---- 다시하기 현황 수신 ----
        got_restart = None
        for _ in range(50):
            sa = get(WEB_A, "/api/state?since=0&chat_since=0")
            if sa.get("restart"):
                got_restart = sa["restart"]
                break
            time.sleep(0.1)
        chk("RESTARTED 현황 수신", got_restart is not None,
            f"{got_restart}")
        chk("현황에 total >= 2", (got_restart or {}).get("total", 0) >= 2,
            f"total={(got_restart or {}).get('total')}")

        # ---- 전원 투표 ----
        post(WEB_A, "/api/restart", {})
        post(WEB_B, "/api/restart", {})
        time.sleep(3.0)

        sa = get(WEB_A, "/api/state?since=0&chat_since=0")
        chk("★ 전원 동의 → game_id 증가 (커서 리셋)",
            sa.get("game_id", 0) > (gid0 or 0),
            f"{gid0} → {sa.get('game_id')}")
        chk("재시작 후 ended 해제", not sa.get("ended"))
        # 새 판은 검은 카드 선택부터다 → 선택 후 라운드가 올라간다.
        post(WEB_A, "/api/reply", {"text": "0"})
        post(WEB_B, "/api/reply", {"text": "0"})
        time.sleep(3.0)
        sa = get(WEB_A, "/api/state?since=0&chat_since=0")
        chk("재시작 후 새 라운드 시작 (검은카드 선택 후)",
            (sa.get("state") or {}).get("round", 0) >= 1,
            f"round={(sa.get('state') or {}).get('round')}")

        # ---- 결과 ----
        print()
        npass = sum(1 for _, ok, _ in results if ok)
        for name, ok, extra in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({extra})" if extra else ""))
        print(f"\n{npass}/{len(results)} PASS")
        if npass != len(results):
            print("\n---- relay 로그 ----")
            for ln in rl[-15:]:
                print("  R|", ln)
        return 0
    finally:
        for p in (wa, wb, relay):
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
