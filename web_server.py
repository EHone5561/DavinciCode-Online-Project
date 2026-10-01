# -*- coding: utf-8 -*-
"""다빈치 코드 — 브라우저(HTML) GUI 를 위한 로컬 웹서버.

구조
----
    [브라우저]  ←HTTP→  [web_server.py]  ←소켓→  [relay.py]
     시안 HTML            이 파일                게임 서버

이 파일은 **게임 규칙을 모른다.** relay 와 브라우저 사이의 얇은 다리다.
  - relay 에 접속해 STATE(JSON)/SHOW/ASK 를 받아 보관
  - 브라우저가 폴링(/api/state)하면 최신 상태를 돌려준다
  - 브라우저가 입력(/api/reply)하면 relay 로 REPLY 를 보낸다

실행
----
    python -E web_server.py                       # 서버(localhost:8765)에 접속
    python -E web_server.py --host 192.168.0.10
    python -E web_server.py --name 태원 --web-port 8000

★ 입력 원칙은 터미널 클라이언트와 같다: 소켓 수신 스레드는 큐에 넣기만 하고,
  HTTP 핸들러(메인 계층)가 그걸 읽어 응답한다. input() 을 쓰지 않는다.
"""

import argparse
import json
import posixpath
import queue
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import protocol as P

DEFAULT_PORT = 8765
DEFAULT_WEB_PORT = 8000
HERE = None


class GameBridge:
    """relay 접속 + 최신 상태 보관 + 입력 전달."""

    def __init__(self, host, port, name=None):
        self.host = host
        self.port = port
        self.name = name
        self.inbox = queue.Queue()          # 수신 메시지
        self.latest_state = None            # 최신 STATE dict
        self.messages = []                  # SHOW/SHOWME 로그 (최근 것만)
        self.chats = []                     # ★ CHAT 대화 로그 (게임 로그와 분리)
        self.pending_ask = None             # 현재 입력 대기 프롬프트
        self.ended = False
        self.end_text = ""
        self.restart = None                 # ★ 최신 다시하기 현황 (voted/total/names)
        self.send_restart = False           # ★ 브라우저가 '다시하기'를 눌렀음
        self.game_id = 0                    # ★ 게임 세대 (재시작마다 +1) → 브라우저 커서 리셋
        self.seat = None
        self.hello_name = None
        self.lock = threading.Lock()
        self.sock = None
        self._send_lock = threading.Lock()
        self._connected = threading.Event()
        self._name_sent = False
        # ★ 브라우저 생존 감지 — 마지막 폴링 시각. 브라우저가 사라지면
        #   PING 전송이 멈추고 relay 가 '기권'으로 판정한다.
        self.last_poll = 0.0
        self._ping_stop = threading.Event()

    # ---------------- relay 연결 ----------------
    def connect(self):
        # ★ timeout=10 을 남겨두면 makefile 읽기가 10초마다 socket.timeout 을
        #   던지고, recv_message 가 그걸 (None, None)=EOF 로 오판해
        #   게임 중 '연결이 끊겼습니다' 가 된다. 접속 후 timeout 을 해제한다.
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=self._recv_loop, daemon=True).start()
        # ★ 브라우저 생존 감지 — PING 전송 스레드
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def _ping_loop(self):
        """브라우저가 살아있는 동안 relay 에 PING 을 보낸다.

        ★ 브라우저 탭을 닫아도 이 프로세스의 소켓은 살아있어 relay 가
          '연결됨'으로 본다(기존 버그: 기권 처리가 안 됨). 브라우저는
          0.28초마다 `/api/state` 를 폴링하므로, **폴링이 끊기면 PING 도
          멈춘다** → relay 가 PING 공백(10초)으로 진짜 종료를 감지한다.

        ⚠️ F5 새로고침은 1~2초 안에 폴링이 재개되므로 `POLL_GRACE` 안에
           복귀해 구제된다 — 즉시 기권되지 않는다.
        """
        POLL_GRACE = 5.0        # 폴링이 이 시간 안에 오면 '살아있음'
        while not self._ping_stop.is_set():
            self._ping_stop.wait(2.0)
            if self._ping_stop.is_set():
                break
            with self.lock:
                alive = self.last_poll > 0 and \
                    (time.time() - self.last_poll) <= POLL_GRACE
            if not alive:
                continue        # 브라우저 없음 → PING 중단 (relay 가 끊김 판정)
            try:
                with self._send_lock:
                    self.sock.sendall(P.encode(P.PING, "1"))
            except OSError:
                return

    def _recv_loop(self):
        f = self.sock.makefile("rb")
        try:
            while True:
                mtype, payload = P.recv_message(f)
                # ★ EOF 는 (None, None) 일 때만이다.
                #   (None, "텍스트") 는 '알 수 없는 타입' — EOF 로 오판하면
                #   게임 중 연결이 끊긴 것처럼 보인다 (실측 버그).
                if mtype is None and payload is None:
                    break               # 진짜 EOF
                if mtype is None:
                    continue            # 알 수 없는 메시지 무시
                self._handle(mtype, payload)
        except Exception as e:
            import traceback
            print(f"[web] 수신 루프 오류: {e!r}", flush=True)
            traceback.print_exc()
        with self.lock:
            self.ended = True
            if not self.end_text:
                self.end_text = "서버와의 연결이 끊겼습니다."

    def _handle(self, mtype, payload):
        with self.lock:
            if mtype == P.STATE:
                st = P.decode_state(payload)
                if st is not None:
                    self.latest_state = st
            elif mtype in (P.SHOW, P.SHOWME):
                if payload.strip():
                    self.messages.append(payload)
                    self.messages = self.messages[-200:]
            elif mtype == P.CHAT:
                # ★ 채팅은 게임 로그와 섞지 않고 별도 목록으로 둔다.
                #   (로그는 게임 진행 기록, 채팅은 사람 대화 — 표시 스타일도 다르다.)
                if payload.strip():
                    self.chats.append(payload)
                    self.chats = self.chats[-200:]
            elif mtype == P.ASK:
                # 터미널 모드와 달리 웹은 STATE.ask 로 입력 UI 를 그린다.
                # 다만 폴링 사이에 ASK 가 먼저 올 수 있으므로 prompt 를 보관한다.
                prompt, _mode, _data = P.decode_ask(payload)
                self.pending_ask = prompt
                # ★ --name 이 주어졌고 아직 이름을 안 보냈으면 여기서 자동응답한다.
                #   (브라우저를 여는 시간 때문에 relay 의 이름 대기(60초)가
                #    먼저 끝나 버리는 문제를 피한다.)
                if self.name and not self._name_sent:
                    self._name_sent = True
                    try:
                        self.sock.sendall(P.encode(P.REPLY, self.name.strip()[:12]))
                        # ★ --name 으로 자동응답했으니 이름 ASK 는 '처리됨'.
                        #   pending_ask 를 비우지 않으면 브라우저가 계속
                        #   "이름을 입력하세요" 를 띄운다 (실측 버그).
                        self.pending_ask = None
                    except OSError:
                        pass
            elif mtype == P.HELLO:
                parts = payload.split(" ", 1)
                if parts and parts[0].isdigit():
                    # ★ HELLO 는 1-based(사람에게 보여주는 좌석번호)로 온다.
                    #   STATE 의 viewer 는 0-based 이므로 여기서 맞춰 둔다.
                    self.seat = int(parts[0]) - 1
                self.hello_name = parts[1] if len(parts) > 1 else "?"
                self._connected.set()
            elif mtype == P.END:
                self.ended = True
                self.end_text = payload
                self.pending_ask = None
            elif mtype == P.RESTARTED:
                # ★ '다시하기' 현황 — 게임이 끝난 뒤 전원 동의를 기다린다.
                #   아직 게임 종료 상태(ended=True)이고, 여기에 투표 수가 실린다.
                try:
                    info = json.loads(payload)
                except ValueError:
                    info = {}
                self.restart = info
                # ★ 전원 동의(voted==total>0)면 새 게임이 곧 시작된다.
                #   이전 게임의 로그/종료화면을 지워 새 판이 깨끗하게 뜨게 한다.
                if info.get("voted", 0) > 0 and \
                        info.get("voted") == info.get("total"):
                    self._reset_for_new_game()
                elif info.get("voted", 0) == 0:
                    # 투표 시작(0/N) — 게임 종료 화면 유지
                    pass

    def send_reply(self, text):
        with self._send_lock:
            if self.sock is None:           # 아직 연결 전
                return False
            try:
                self.sock.sendall(P.encode(P.REPLY, text))
                # 서버가 응답하면 새 ASK 가 온다. 여기선 대기 상태를 비운다.
                with self.lock:
                    self.pending_ask = None
                return True
            except OSError:
                return False

    def send_chat(self, text):
        """★ 채팅 전송 — 게임 입력(REPLY)과 완전히 분리된 경로.

        relay 가 CHAT 을 받아 모든 사람에게 '[이름] 내용' 으로 브로드캐스트한다.
        자기 자신에게도 돌아오므로 화면 표시는 서버 응답만 기다리면 된다.
        """
        body = " ".join(str(text).split())[:200]
        if not body:
            return False
        with self._send_lock:
            if self.sock is None:           # 아직 연결 전
                return False
            try:
                self.sock.sendall(P.encode(P.CHAT, body))
                return True
            except OSError:
                return False

    def send_restart_vote(self):
        """★ '다시하기' 투표를 relay 로 보낸다 (게임 종료 후에만 의미가 있다)."""
        with self._send_lock:
            if self.sock is None:           # 아직 연결 전
                return False
            try:
                self.sock.sendall(P.encode(P.RESTART, "1"))
                return True
            except OSError:
                return False

    def _reset_for_new_game(self):
        """★ 새 게임이 시작될 때 이전 판의 잔재를 지운다.

        게임 로그·채팅·종료 화면·투표 현황을 모두 비워, 순위표가 사라지고
        새 판이 깨끗하게 그려지도록 한다.

        ★★ game_id 를 올리는 게 핵심이다.
           브라우저는 `since`(로그 커서)로 "이미 본 로그"를 표시한다. 서버가
           로그를 비우면 커서(200) > 새 로그 길이(1) 가 되어 브라우저가
           **영원히 빈 배열만 받는다** — 로그가 안 늘고, 로그에서 정답/오답을
           감지하는 O/X 도 안 뜬다. (실측 버그)
           game_id 가 바뀌면 브라우저가 커서를 0 으로 되돌린다.
        """
        self.messages = []
        self.chats = []
        self.latest_state = None
        self.pending_ask = None
        self.ended = False
        self.end_text = ""
        self.restart = None
        self.send_restart = False
        self.game_id += 1               # ★ 세대 카운터 (브라우저 커서 리셋 신호)

    def snapshot(self, since=0, chat_since=0):
        """브라우저 폴링용 상태 묶음."""
        with self.lock:
            self.last_poll = time.time()    # ★ 브라우저 생존 신호 (PING 판단 근거)
            st = self.latest_state or {}
            return {
                "connected": self._connected.is_set(),
                "seat": self.seat,
                "name": self.hello_name,
                "state": self.latest_state,
                "messages": self.messages[since:],
                "msg_total": len(self.messages),
                "chats": self.chats[chat_since:],       # ★ 채팅(게임 로그와 별개 커서)
                "chat_total": len(self.chats),
                "ask": st.get("ask"),          # ★ STATE 에 실린 입력 정보(모드/데이터)
                "ask_prompt": self.pending_ask,  # ASK 로 온 원문 프롬프트(이름 입력 등)
                "ended": self.ended,
                "end_text": self.end_text,
                "restart": self.restart,        # ★ 다시하기 투표 현황 (voted/total/names)
                "game_id": self.game_id,        # ★ 세대 — 바뀌면 브라우저가 커서를 리셋
            }


BRIDGE = None      # 전역 (핸들러가 접근)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass          # 콘솔 조용히

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path, ctype):
        """★ 사운드 등 정적 파일 서빙 (sfx/ 전용)."""
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html", "/game.html"):
            import os
            self._html(os.path.join(HERE, "web", "game.html"))
        elif u.path == "/api/state":
            q = parse_qs(u.query)
            since = int(q.get("since", ["0"])[0] or 0)
            chat_since = int(q.get("chat_since", ["0"])[0] or 0)
            self._json(BRIDGE.snapshot(since, chat_since))
        elif u.path.startswith("/sfx/"):
            # ★ 사운드 파일 서빙. 경로 이탈(..) 차단.
            import os
            rel = posixpath.normpath(unquote(u.path[len("/sfx/"):]))
            if rel.startswith("..") or rel.startswith("/") or "\\" in rel:
                self.send_error(403)
                return
            ext = os.path.splitext(rel)[1].lower()
            ctype = {"ogg": "audio/ogg", "wav": "audio/wav",
                     "mp3": "audio/mpeg", "m4a": "audio/mp4"}.get(ext[1:])
            if ctype is None:
                self.send_error(403)
                return
            self._static(os.path.join(HERE, "sfx", rel), ctype)
        else:
            self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/reply":
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln).decode("utf-8") if ln else "{}"
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            text = str(data.get("text", ""))
            ok = BRIDGE.send_reply(text)
            self._json({"ok": ok})
        elif u.path == "/api/name":
            # --name 없이 브라우저에서 이름을 보낼 때
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln).decode("utf-8") if ln else "{}"
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            self._json({"ok": BRIDGE.send_reply(str(data.get("text", "")))})
        elif u.path == "/api/chat":
            # ★ 채팅 — 게임 입력과 무관한 별도 경로
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln).decode("utf-8") if ln else "{}"
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            self._json({"ok": BRIDGE.send_chat(str(data.get("text", "")))})
        elif u.path == "/api/restart":
            # ★ '다시하기' 투표 — 게임이 끝난 뒤 전원이 누르면 새 판을 시작한다.
            self._json({"ok": BRIDGE.send_restart_vote()})
        else:
            self.send_error(404)


def _lan_ip():
    """이 PC 의 LAN IP 를 알아낸다 (다른 PC 접속 안내용). 실패하면 None.

    ★ UDP 소켓으로 라우팅 조회만 한다(실제 패킷은 안 보낸다).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def serve(bridge, web_port, open_browser=True, name=None, web_host="127.0.0.1"):
    global BRIDGE
    BRIDGE = bridge
    bridge.connect()
    # ※ 이름은 브라우저에서 입력받는다(입력창에 이름 질문이 뜬다).
    #   --name 으로 자동 응답하려 하면 relay 의 이름 대기(60초)와 타이밍이
    #   어긋나 좌석이 비워질 수 있어 쓰지 않는다.

    httpd = ThreadingHTTPServer((web_host, web_port), Handler)
    url = f"http://127.0.0.1:{web_port}/"
    # ★ 다른 PC 에서 접속할 주소도 알려준다 (web_host=0.0.0.0 일 때).
    lan_ip = _lan_ip()
    print(f"[web] 브라우저에서 열기: {url}")
    if web_host == "0.0.0.0" and lan_ip:
        print(f"[web] 같은 네트워크의 다른 PC 주소: http://{lan_ip}:{web_port}/")
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] 종료합니다.")
    finally:
        httpd.server_close()


def parse_args(argv):
    ap = argparse.ArgumentParser(description="다빈치 코드 웹(브라우저) 클라이언트")
    ap.add_argument("--host", default="127.0.0.1", help="게임 서버(relay) 주소")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="게임 서버 포트")
    ap.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT,
                    help="브라우저용 로컬 포트")
    ap.add_argument("--name", default=None, help="표시 이름")
    ap.add_argument("--no-browser", action="store_true", help="브라우저 자동 실행 안 함")
    ap.add_argument("--web-host", default="127.0.0.1",
                    help="웹 서버 바인딩 주소 (0.0.0.0 = 같은 네트워크의 다른 PC 허용)")
    return ap.parse_args(argv)


def main(argv=None):
    global HERE
    import os
    # ★ exe(onefile)로 묶으면 __file__ 은 임시 폴더의 스크립트를 가리키고,
    #   web/game.html·sfx/ 같은 자원은 sys._MEIPASS 에 풀린다.
    #   그래서 frozen 이면 _MEIPASS 를, 아니면 이 파일 폴더를 쓴다.
    if getattr(sys, "frozen", False):
        HERE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        HERE = os.path.dirname(os.path.abspath(__file__))
    args = parse_args(argv or sys.argv[1:])
    bridge = GameBridge(args.host, args.port, args.name)
    try:
        serve(bridge, args.web_port, open_browser=not args.no_browser,
              name=args.name, web_host=args.web_host)
    except ConnectionRefusedError:
        print(f"[!] 게임 서버에 연결할 수 없습니다: {args.host}:{args.port}")
        print("    relay.py(또는 런처의 [1] 서버 열기)가 켜져 있는지 확인하세요.")
        return 1
    except OSError as e:
        print(f"[!] 오류: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
