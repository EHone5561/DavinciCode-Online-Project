"""★★ 브라우저(SSE) 종료 → relay 즉시 기권 — relay 출력까지 확인.

실행: python -E -X utf8 test_alive_kill2.py
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
WEB_PORT = 8793
GAME_PORT = 8794


def _drain(pipe, sink):
    for line in iter(pipe.readline, b""):
        sink.append(line.decode("utf-8", "replace").rstrip())
    pipe.close()


def main():
    lines = []
    relay = web = None
    try:
        relay = subprocess.Popen(
            [PY, "-E", "-u", "relay.py", "3", "--cpu", "2", "--port", str(GAME_PORT)],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=_drain, args=(relay.stdout, lines), daemon=True).start()
        time.sleep(1.5)

        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        web = subprocess.Popen(
            [PY, "-E", "-u", "web_server.py", "--port", str(GAME_PORT),
             "--web-port", str(WEB_PORT), "--no-browser"],
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

        def post(path, obj):
            req = urllib.request.Request(
                f"http://127.0.0.1:{WEB_PORT}{path}",
                data=json.dumps(obj).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))

        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=1)
                break
            except Exception:
                time.sleep(0.2)

        post("/api/name", {"text": "P1"})
        time.sleep(0.6)
        post("/api/reply", {"text": "0"})     # 검은 카드 0장
        time.sleep(2.0)

        # ★ 생존 스트림 연결 (브라우저가 페이지 연 것)
        s = socket.create_connection(("127.0.0.1", WEB_PORT), timeout=5)
        s.sendall(b"GET /api/alive HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        s.settimeout(3.0)
        s.recv(64)
        print("[test] 생존 스트림 연결됨")
        time.sleep(2.0)

        # ★ 브라우저 종료
        print("[test] 생존 스트림 끊음 (= 브라우저 닫기)")
        t_kill = time.time()
        s.close()

        # web_server 자살 대기
        while time.time() - t_kill < 10 and web.poll() is None:
            time.sleep(0.1)
        print(f"[test] web_server 종료: {time.time()-t_kill:.1f}s")

        # relay 가 기권을 감지할 시간
        time.sleep(2.5)

        print("\n---- relay 출력 (뒷부분) ----")
        for ln in lines[-30:]:
            print(ln)

        joined = "\n".join(lines)
        print("\n---- 판정 ----")
        print("기권 언급:", "기권" in joined)
        return 0
    finally:
        for p in (web, relay):
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
