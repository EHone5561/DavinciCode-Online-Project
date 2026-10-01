"""통합본 실행 검증 — web_launcher 로 띄우고 실제 플레이 + 다시하기.

실행: python -E -X utf8 test_launcher_flow.py
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
PORT = 8765          # web_launcher 는 이 포트 고정
WEB_PORT = 8840


def _drain(pipe, sink):
    for line in iter(pipe.readline, b""):
        sink.append(line.decode("utf-8", "replace").rstrip())


def wait_http(port, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def get_p(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}{path}", timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{WEB_PORT}{path}",
        data=json.dumps(obj or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    proc = None
    out = []
    results = []

    def chk(name, cond, extra=""):
        results.append((name, bool(cond), extra))

    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(
            [PY, "-E", "-u", "web_launcher.py", "solo", "3",
             "--no-browser", "--web-port", str(WEB_PORT)],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True).start()

        chk("web_launcher 로 웹서버가 뜬다", wait_http(WEB_PORT))

        joined = "\n".join(out)
        chk("인원 3 / CPU 2 로 시작 (인자 적용)",
            "인원 3, CPU 2" in joined)
        chk("좀비 접속 로그 없음 ('접속 직후 끊김' 없음)",
            "접속 직후 끊김" not in joined)

        post("/api/name", {"text": "나"})
        time.sleep(2.0)
        st = get_p("/api/state?since=0&chat_since=0")
        chk("좌석 배정됨", st.get("seat") is not None, f"seat={st.get('seat')}")
        chk("snapshot 에 restart 키", "restart" in st)
        chk("snapshot 에 game_id 키", "game_id" in st)

        # 게임 시작 (검은 카드 0장)
        for _ in range(10):
            ask = (get_p("/api/state?since=0&chat_since=0").get("ask") or {})
            if ask.get("mode"):
                post("/api/reply", {"text": "0"})
                break
            time.sleep(0.3)
        time.sleep(3.0)
        st = get_p("/api/state?since=0&chat_since=0")
        chk("게임 시작됨 (round >= 1)",
            (st.get("state") or {}).get("round", 0) >= 1,
            f"round={(st.get('state') or {}).get('round')}")

        # 게임 끝까지 (그만 입력)
        deadline = time.time() + 120
        ended = False
        while time.time() < deadline:
            st = get_p("/api/state?since=0&chat_since=0")
            if st.get("ended"):
                ended = True
                break
            ask = st.get("ask") or {}
            if ask.get("mode"):
                post("/api/reply", {"text": "q" if ask["mode"] == "guess" else "1"})
            time.sleep(0.25)
        chk("게임 종료 (ended)", ended)

        # 다시하기 현황
        rst = None
        for _ in range(50):
            st = get_p("/api/state?since=0&chat_since=0")
            if st.get("restart"):
                rst = st["restart"]
                break
            time.sleep(0.1)
        chk("다시하기 버튼 현황 수신", rst is not None, f"{rst}")

        # 투표 (사람 1명 + CPU 자동 동의)
        gid0 = get_p("/api/state?since=0&chat_since=0").get("game_id")
        post("/api/restart")
        time.sleep(3.5)
        st = get_p("/api/state?since=0&chat_since=0")
        chk("★ 다시하기 → game_id 증가 (새 판)", st.get("game_id", 0) > (gid0 or 0),
            f"{gid0} → {st.get('game_id')}")
        chk("재시작 후 ended 해제", not st.get("ended"))

        print()
        npass = sum(1 for _, ok, _ in results if ok)
        for name, ok, extra in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({extra})" if extra else ""))
        print(f"\n{npass}/{len(results)} PASS")
        if npass != len(results):
            print("\n---- 출력 ----")
            for ln in out[-25:]:
                print("  |", ln)
        return 0 if npass == len(results) else 1
    finally:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
