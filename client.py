# -*- coding: utf-8 -*-
"""다빈치 코드 멀티플레이 — 참가자 클라이언트.

서버(relay.py)에 접속해 터미널로 게임을 보여준다.
클라이언트는 게임 규칙을 모른다. 문자열을 받아 출력하고,
입력을 받아 올려보내기만 한다.

    python -E client.py                       # localhost:8765
    python -E client.py --host 192.168.0.10   # 다른 기기
    python -E client.py --host 192.168.0.10 --port 9000
    python -E client.py --name 홍길동

★ 입력 원칙 (중요)
-------------------
input() 은 **오직 메인 스레드에서만** 호출한다. 수신 스레드는 소켓에서
읽은 메시지를 큐에 넣기만 하고, ASK 는 '입력 요청 큐'에 적재한 뒤
메인 스레드가 꺼내서 처리한다.

이유: 수신 스레드(daemon)에서 input() 을 부르면 Windows 에서 stdin 이
반쯤 열린 상태로 빈 문자열(EOF)을 즉시 반환해, 이름이나 추측이 빈 값으로
먼저 전송되고 사용자가 실제로 친 입력은 다음 질문에 한 칸씩 밀리는
현상이 있었다. (이름이 P2 로 고정되던 버그, 재질문 도배의 원인.)
"""

import argparse
import queue
import socket
import sys
import threading

import protocol as P

DEFAULT_PORT = 8765


class Client:
    def __init__(self, host, port, name=None):
        self.host = host
        self.port = port
        self.name = name
        self.seat = None
        self._sock = None
        self._file = None
        self._send_lock = threading.Lock()
        self._out_lock = threading.Lock()      # print 원자화 (수신/메인 동시 출력)
        self._ask_queue = queue.Queue()        # 입력 요청 (프롬프트) — 메인 스레드가 소비
        self._running = True
        self._connected = threading.Event()    # 이름 입력 완료(HELLO 수신) 신호

    # ---------------- 연결 ----------------
    def connect(self):
        self._sock = socket.create_connection((self.host, self.port))
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._file = self._sock.makefile("rb")

    def send(self, mtype, payload=""):
        with self._send_lock:
            try:
                self._sock.sendall(P.encode(mtype, payload))
                return True
            except OSError:
                return False

    # ---------------- 출력 ----------------
    def _print(self, text):
        with self._out_lock:
            print(text, flush=True)

    # ---------------- 수신 ----------------
    def _recv_loop(self):
        while self._running:
            mtype, payload = P.recv_message(self._file)
            # ★ EOF 는 (None, None) 일 때만. (None, "텍스트") = 알 수 없는 타입.
            if mtype is None and payload is None:
                self._running = False
                # 대기 중인 입력이 있으면 깨운다 (None = 끊김)
                self._ask_queue.put(None)
                break
            if mtype is None:
                continue        # 알 수 없는 메시지는 무시
            if mtype == P.SHOW:
                self._print(payload)
            elif mtype == P.SHOWME:
                self._print(payload)
            elif mtype == P.ASK:
                # 입력은 메인 스레드가 처리한다 — 여기서는 큐에 넣기만.
                # ★ payload 는 JSON(prompt+mode+data)일 수 있다.
                #   터미널 클라이언트는 prompt 문자열만 쓰면 된다.
                prompt, _mode, _data = P.decode_ask(payload)
                self._ask_queue.put(prompt)
            elif mtype == P.WAIT:
                # 남이 선택 중 — 대기 화면(자기 패 + 상대 현황)일 수도,
                # 짧은 '선택중...' 안내일 수도 있다. 둘 다 그대로 보여준다.
                self._print(payload)
            elif mtype == P.HELLO:
                parts = payload.split(" ", 1)
                self.seat = int(parts[0])
                nm = parts[1] if len(parts) > 1 else "?"
                self._print(f"\n[접속됨] 좌석 {self.seat} · 이름 {nm}")
                self._print("  (게임 시작을 기다리는 중...)\n")
                self._connected.set()
            elif mtype == P.END:
                self._print("\n" + payload)
                self._running = False
                break

    # ---------------- 입력 (메인 스레드 전용) ----------------
    def _answer_asks(self):
        """입력 요청 큐를 소비해 input() 후 REPLY 전송. 메인 스레드에서만 호출."""
        while self._running:
            try:
                prompt = self._ask_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if prompt is None:          # 연결 끊김 신호
                self._running = False
                return
            try:
                answer = input(prompt)
            except (EOFError, KeyboardInterrupt):
                self.send(P.BYE)
                self._running = False
                return
            self.send(P.REPLY, answer.strip())

    # ---------------- 실행 ----------------
    def run(self):
        self.connect()
        t = threading.Thread(target=self._recv_loop, daemon=True)
        t.start()

        # 1) 접속 직후 서버가 이름을 물어봄 → 메인 스레드가 직접 받는다.
        #    (--name 이 있으면 그 값을 그대로 보낸다.)
        try:
            prompt = self._ask_queue.get(timeout=10.0)
        except queue.Empty:
            prompt = "이름을 입력하세요 (Enter=기본): "
        if prompt is None:
            print("[!] 서버가 연결을 닫았습니다.")
            return
        if self.name:
            self.send(P.REPLY, self.name.strip()[:12])
        else:
            try:
                answer = input(prompt)
            except (EOFError, KeyboardInterrupt):
                answer = ""
            self.send(P.REPLY, answer.strip()[:12])

        # 2) HELLO(좌석 배정) 를 기다린 뒤 본격 입력 루프로.
        self._connected.wait(timeout=10.0)

        try:
            self._answer_asks()
        except KeyboardInterrupt:
            self.send(P.BYE)
        finally:
            self._running = False
            try:
                self._file.close()
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass


def parse_args(argv):
    ap = argparse.ArgumentParser(description="다빈치 코드 클라이언트")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--name", default=None, help="표시 이름 (생략 시 서버가 물어봄)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    c = Client(args.host, args.port, args.name)
    try:
        c.run()
    except ConnectionRefusedError:
        print(f"[!] 서버에 연결할 수 없습니다: {args.host}:{args.port}")
        print("    relay.py 가 켜져 있는지, 주소/포트가 맞는지 확인하세요.")
        return 1
    except OSError as e:
        print(f"[!] 연결 오류: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
