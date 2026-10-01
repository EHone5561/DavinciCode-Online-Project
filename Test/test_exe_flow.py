"""빌드된 exe 검증 — exe 가 뜨고, 게임이 시작되고, 다시하기까지 도는지.

exe 는 zip 아카이브를 품고 있어서 코드 추출이 안 되므로,
**실제로 실행해서 HTTP 로 확인**한다.

실행: python -E -X utf8 test_exe_flow.py
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "다빈치코드_웹.exe")
WEB_PORT = 8850


def _drain(pipe, sink):
    for line in iter(pipe.readline, b""):
        sink.append(line.decode("utf-8", "replace").rstrip())


def wait_http(port, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
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
        if not os.path.isfile(EXE):
            print(f"FAIL  exe 없음: {EXE}")
            return 1
        size = os.path.getsize(EXE) / (1024 * 1024)
        print(f"[test] exe 크기: {size:.1f} MB")

        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # ★ exe 는 solo 모드로 띄운다 (브라우저 자동 실행은 --no-browser 로 끔)
        proc = subprocess.Popen(
            [EXE, "solo", "3", "--no-browser", "--web-port", str(WEB_PORT)],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True).start()

        chk("exe 가 웹서버를 띄운다", wait_http(WEB_PORT))
        joined = "\n".join(out)
        chk("exe 가 solo 3 인자를 적용",
            ("인원 3" in joined) or ("인원 3, CPU 2" in joined),
            next((l for l in out if "인원" in l), ""))

        post("/api/name", {"text": "테스터"})
        time.sleep(2.5)
        st = get_p("/api/state?since=0&chat_since=0")
        chk("좌석 배정됨", st.get("seat") is not None, f"seat={st.get('seat')}")
        chk("snapshot 에 restart 키", "restart" in st)
        chk("snapshot 에 game_id 키", "game_id" in st)

        # 게임 시작
        for _ in range(12):
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

        # 게임 끝까지
        deadline = time.time() + 150
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

        rst = None
        for _ in range(50):
            st = get_p("/api/state?since=0&chat_since=0")
            if st.get("restart"):
                rst = st["restart"]
                break
            time.sleep(0.1)
        chk("다시하기 버튼 현황 수신", rst is not None, f"{rst}")

        gid0 = get_p("/api/state?since=0&chat_since=0").get("game_id")
        post("/api/restart")
        time.sleep(4.0)
        st = get_p("/api/state?since=0&chat_since=0")
        chk("★ exe 에서도 다시하기 동작 (game_id 증가)",
            st.get("game_id", 0) > (gid0 or 0), f"{gid0} → {st.get('game_id')}")
        chk("재시작 후 ended 해제", not st.get("ended"))

        print()
        npass = sum(1 for _, ok, _ in results if ok)
        for name, ok, extra in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({extra})" if extra else ""))
        print(f"\n{npass}/{len(results)} PASS")
        if npass != len(results):
            print("\n---- exe 출력 ----")
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
