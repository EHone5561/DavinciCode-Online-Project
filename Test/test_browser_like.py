"""★★ 브라우저처럼 동작(폴링 + SSE) → 창 닫기 → relay 즉시 기권 검증.

실제 game.html 과 같은 방식으로 움직인다.
  1) /api/state 를 0.3초마다 폴링한다 (web_server 가 PING 을 보내게 함)
  2) /api/alive 생존 스트림을 연다
  3) 이름을 보낸다
그리고 **둘 다 끊는다** (= 브라우저 창 닫기).

실행: python -E -X utf8 test_browser_like.py
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
WEB_PORT = 8801
GAME_PORT = 8802


def _drain(pipe, sink):
    for line in iter(pipe.readline, b""):
        sink.append(line.decode("utf-8", "replace").rstrip())


def main():
    relay_lines, web_lines = [], []
    relay = web = None
    stop_poll = threading.Event()
    try:
        relay = subprocess.Popen(
            [PY, "-E", "-u", "relay.py", "3", "--cpu", "2", "--port", str(GAME_PORT)],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=dict(os.environ, FORFEIT_DEBUG="1"))
        threading.Thread(target=_drain, args=(relay.stdout, relay_lines), daemon=True).start()
        time.sleep(1.5)

        web = subprocess.Popen(
            [PY, "-E", "-u", "web_server.py", "--port", str(GAME_PORT),
             "--web-port", str(WEB_PORT), "--no-browser"],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        threading.Thread(target=_drain, args=(web.stdout, web_lines), daemon=True).start()

        base = f"http://127.0.0.1:{WEB_PORT}"
        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.2)

        def post(path, obj):
            req = urllib.request.Request(base + path,
                                         data=json.dumps(obj).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))

        # ★ 1) 폴링 스레드 (game.html 과 동일하게 0.3초 간격)
        def poller():
            while not stop_poll.is_set():
                try:
                    urllib.request.urlopen(
                        base + "/api/state?since=0&chat_since=0", timeout=2).read()
                except Exception:
                    pass
                time.sleep(0.3)
        threading.Thread(target=poller, daemon=True).start()
        time.sleep(0.8)                       # PING 이 나가게

        # ★ 2) 생존 스트림
        s = socket.create_connection(("127.0.0.1", WEB_PORT), timeout=5)
        s.sendall(b"GET /api/alive HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        s.settimeout(3.0)
        s.recv(64)
        print("[test] 폴링 + 생존 스트림 연결됨")

        # ★ 3) 이름
        post("/api/name", {"text": "P1"})
        time.sleep(0.8)
        post("/api/reply", {"text": "0"})
        time.sleep(2.5)

        # PING 이 실제로 나갔는지 확인
        dbg = [l for l in relay_lines if "has_pinged" in l]
        print("[test] relay PING 상태:", dbg[-1] if dbg else "(없음)")

        # ★ 브라우저 창 닫기 = 폴링 중단 + 스트림 끊기
        print("[test] 브라우저 닫기 (폴링 중단 + 스트림 끊기)")
        t_kill = time.time()
        stop_poll.set()
        s.close()

        while time.time() - t_kill < 10 and web.poll() is None:
            time.sleep(0.1)
        web_t = time.time() - t_kill
        print(f"[test] web_server 종료: {web_t:.1f}s  (exit={web.poll()})")
        print("[test] ---- web_server 출력 ----")
        for ln in web_lines[-15:]:
            print("  W|", ln)

        time.sleep(8.0)
        joined = "\n".join(relay_lines)
        print("\n---- relay 출력 (뒷부분) ----")
        for ln in relay_lines[-18:]:
            print(ln)

        forfeit = "기권" in joined
        print("\n---- 판정 ----")
        print("web_server 자살:", "PASS" if web_t < 8 else "FAIL")
        print("relay 기권 처리:", "PASS" if forfeit else "FAIL")
        print("총 소요:", f"{time.time()-t_kill:.1f}s")
        return 0
    finally:
        stop_poll.set()
        for p in (web, relay):
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
