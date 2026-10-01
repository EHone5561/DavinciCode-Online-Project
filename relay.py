# -*- coding: utf-8 -*-
"""다빈치 코드 멀티플레이 — 중계 서버 (relay).

게임 상태를 혼자 보유하고, 클라이언트들의 터미널로
출력/입력을 중계한다.

    relay.py (이 파일 — 게임 상태 보유)
       ↑        ↑        ↑
    client    client    client     ← 각자 터미널

역할 분담
---------
  - 서버: 게임 진행(session.Session), 진짜 상태 보유, 입력 검증
  - 클라이언트: SHOW 는 출력, ASK 는 입력, WAIT 는 대기 표시

출력 중계 규칙
--------------
  show(text)       → 전원에게 SHOW
  show_me(seat,t)  → seat 에게만 SHOWME
  ask(seat,p)      → seat 에게만 ASK, 그 응답을 받을 때까지 **서버 스레드가 대기**
  wait(seat,t)     → seat 에게만 WAIT
  finish(text)     → 전원에게 END

동시성
------
  클라이언트마다 수신 스레드 1개. 수신 스레드는 메시지를 큐에 넣는다.
  게임 진행은 메인 스레드가 하고, ask() 는 큐에서 REPLY 를 꺼낼 때까지
  Event 로 대기한다. 즉 **게임 로직은 한 번에 한 명씩** 순차 진행.

실행
----
  python -E relay.py 3                # 3인 (접속 3명 대기)
  python -E relay.py 3 --cpu 1        # 좌석2 만 CPU (사람 2명 접속)
  python -E relay.py 2 --port 9000
"""

import argparse
import json
import queue
import random
import socket
import sys
import threading
import time

import protocol as P
from session import Output, Session

DEFAULT_PORT = 8765


def _local_ip():
    """다른 기기가 접속할 때 쓸 이 컴퓨터의 랜 IP (실패 시 '확인 불가')."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # 실제 전송은 없음 (경로만 조회)
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "확인 불가"


# =============================================================================
class ClientConn:
    """접속한 클라이언트 하나 (소켓 + 수신 스레드 + 메시지 큐)."""

    def __init__(self, sock, addr, seat):
        self.sock = sock
        self.addr = addr
        self.seat = seat
        self.server = None              # ★ 서버 참조 (CHAT 브로드캐스트용, accept 후 주입)
        self.inbox = queue.Queue()      # 수신 메시지 (타입, 텍스트)
        self.alive = True
        self.last_ping = time.time()    # ★ 마지막 PING 수신 시각 (브라우저 생존 판단)
        self.has_pinged = False         # ★ PING 을 한 번이라도 받았는가
                                        #   (터미널 client.py 는 PING 을 안 보내므로
                                        #    이 플래그로 검사 대상에서 제외한다)
        self.voted_restart = False      # ★ '다시하기' 투표 (게임 종료 후에만 유효)
        self._file = sock.makefile("rb")
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _recv_loop(self):
        while self.alive:
            mtype, payload = P.recv_message(self._file)
            # ★ EOF 는 (None, None) 일 때만. (None, "텍스트") = 알 수 없는 타입.
            if mtype is None and payload is None:
                self.alive = False
                self.inbox.put((None, None))
                break
            if mtype is None:
                continue        # 알 수 없는 메시지는 무시
            if mtype == P.PING:
                # ★ 생존 신호 — 큐에 넣지 않고 시각만 갱신한다.
                #   (큐에 넣으면 게임 입력 큐가 PING 으로 오염된다.)
                self.last_ping = time.time()
                self.has_pinged = True
                continue
            if mtype == P.RESTART:
                # ★ '다시하기' 투표 — 게임 루프(session) 밖에서 집계해야 하므로
                #   큐에 넣지 않는다. (큐에 넣으면 session.recv 가 게임 입력으로
                #   오해해 게임이 엉킨다.) 릴레이가 이 플래그를 직접 폴링한다.
                self.voted_restart = True
                continue
            self.inbox.put((mtype, payload))

    def send(self, mtype, payload=""):
        if not self.alive:
            return False
        ok = P.send_message(self.sock, mtype, payload)
        if not ok:
            self.alive = False
        return ok

    def read_reply(self, timeout=None):
        """REPLY 한 줄을 기다린다. 연결 끊기면 None.

        ★ 큐에는 REPLY 외에 서버가 보낸 것이 섞여 들어올 수 있다
          (예: 다른 클라이언트 때문에 WAIT 을 받는 경우는 없지만,
           SHOW/WAIT 를 늦게 처리하는 타이밍 이슈).
          REPLY 가 나올 때까지 건너뛴다 — 그렇지 않으면 응답이 한 칸씩
          밀려서 게임이 엉뚱하게 진행된다.

        ★ CHAT 은 게임 입력이 아니다 — 브로드캐스트하고 계속 기다린다.
          (게임 입력 대기 중에도 채팅이 가능해야 한다.)

        ★★ PING 감시 — 브라우저를 닫으면 응답이 영영 안 온다. 이때
           `inbox.get()` 이 무한 블록되면 세션이 기권 처리를 못 한다.
           그래서 **주기적으로 깨어나 PING 공백을 확인**하고, 끊겼으면
           빈 응답("")을 리턴해 세션이 기권으로 넘어가게 한다.

           ⚠️ **다른 좌석의 끊김도 확인**해야 한다. 한 사람이 입력을 안 보내
              이 `read_reply` 가 블록된 동안, 다른 사람이 브라우저를 닫으면
              세션 루프가 돌지 않아 `check_forfeit` 가 영영 안 불린다.
              (실측: 내 턴 대기 중 상대 PING 이 끊겼는데 기권 감지가 안 됐다.)
              → 어느 좌석이든 끊겼으면 빈 응답을 리턴해 세션을 깨운다.
        """
        deadline = None if timeout is None else (time.time() + timeout)
        while True:
            # ★ PING 공백이면 즉시 빈 응답 (브라우저 종료 감지)
            if self.has_pinged and self.server is not None and \
                    (time.time() - self.last_ping) > self.server.ping_timeout:
                return ""
            # ★ 다른 좌석이 끊겼어도 깨워서 세션이 기권 처리를 하게 한다.
            #   (내 턴 대기 중 상대가 나가면 세션이 영영 안 도는 것을 막는다)
            if self.server is not None and self.server.any_peer_lost(self.seat):
                return ""
            # 남은 시간을 계산하되, PING 확인 주기(1초)보다 길게 기다리지 않는다.
            wait = 1.0
            if deadline is not None:
                remain = deadline - time.time()
                if remain <= 0:
                    return ""
                wait = min(wait, remain)
            try:
                mtype, payload = self.inbox.get(timeout=wait)
            except queue.Empty:
                if deadline is not None and time.time() >= deadline:
                    return ""
                continue            # ★ PING 재확인을 위해 계속 루프
            if mtype is None:
                return None
            if mtype == P.REPLY:
                return payload
            if mtype == P.CHAT:
                self._relay_chat(payload)
                continue
            # REPLY 가 아니면 무시하고 계속 기다린다
            if deadline is not None and time.time() >= deadline:
                return ""

    def _relay_chat(self, text):
        """받은 채팅을 모든 사람에게 '[이름] 내용' 으로 뿌린다."""
        srv = self.server
        if srv is None:
            return
        nm = ""
        try:
            nm = srv.names[self.seat]
        except (IndexError, TypeError):
            nm = f"P{self.seat + 1}"
        body = " ".join(str(text).split())[:200]      # 제어문자/과길이 정리
        if not body:
            return
        srv.broadcast(P.CHAT, f"[{nm}] {body}")

    def close(self):
        self.alive = False
        try:
            self._file.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# =============================================================================
class RelayOutput(Output):
    """Session 의 Output 을 소켓 중계로 구현.

    WAIT 안내는 '새 입력 요청'일 때만 보낸다.
    검증 실패로 인한 재질문(SHOWME 오류)에는 WAIT 을 다시 보내지 않는다
    — 남의 화면에 '선택중...'이 도배되는 것을 막는다.

    ★ 기권 판정: is_connected(seat) 가 False 면 그 좌석은 끊긴 것으로
      보고 세션이 기권패 처리한다. CPU 좌석(None)은 항상 연결로 본다.
    """

    def __init__(self, server):
        self.server = server
        self._asking_seat = None      # 현재 입력 대기 중인 좌석
        self.current_ask = None       # {"seat","prompt","mode","data"} — GUI 용

    def show(self, text):
        self.server.broadcast(P.SHOW, text)

    def show_me(self, seat, text):
        c = self.server.conn_of(seat)
        if c:
            c.send(P.SHOWME, text)

    def ask(self, seat, prompt, mode=None, data=None):
        # ★ GUI(웹) 클라이언트가 '무엇을 입력 중인가'를 알 수 있게 보관한다.
        #   relay 는 이걸 STATE 에 실어 보낸다(GUI 는 클릭 UI 를 그린다).
        self.current_ask = {"seat": seat, "prompt": prompt,
                            "mode": mode, "data": data}
        c = self.server.conn_of(seat)
        if c is None:
            # CPU 좌석이거나 연결 객체가 없음 → 연결 판단은 is_connected 가 한다.
            self.current_ask = None
            return ""
        if not c.alive:
            self.current_ask = None
            return ""            # 이미 끊김 → 빈 응답 (세션이 기권 처리)
        # 터미널 클라이언트는 prompt 문자열만 쓴다 → ASK 는 JSON 으로 보내되
        # decode_ask 가 prompt 를 뽑아 쓰면 되고, 모르면 원문 그대로 쓴다.
        if not c.send(P.ASK, P.encode_ask(prompt, mode, data)):
            self.current_ask = None
            return ""
        # 새 좌석의 입력이 시작될 때만 남들에게 대기 안내를 뿌린다.
        if self._asking_seat != seat:
            self._asking_seat = seat
            name = self.server.names[seat]
            for i, other in enumerate(self.server.conns):
                if other is not None and other is not c:
                    other.send(P.WAIT, f"\n   ⏳ {name} 님이 선택중...")
        reply = c.read_reply()
        if reply is None:
            self.current_ask = None
            return ""
        return reply

    def clear_ask(self):
        """입력이 끝났음을 표시 — GUI 가 클릭 UI 를 닫게 한다."""
        self.current_ask = None

    def wait(self, seat, text):
        """대기 화면을 이 좌석에게 보낸다.

        여러 줄 텍스트(자기 패 + 상대 현황 + 공개 목록)를 그대로 전달한다.
        """
        c = self.server.conn_of(seat)
        if c:
            c.send(P.WAIT, text)

    def _drain_chats(self):
        """★ 쌓인 CHAT 을 꺼내 브로드캐스트한다 — 실제 로직은 서버에 있다.

        `read_reply` 는 ask 응답을 기다릴 때만 큐를 비운다. CPU 턴이나
        다른 사람 차례에는 아무도 큐를 안 비우므로 채팅이 쌓여 늦게 뜬다.
        전용 스레드(`RelayServer._chat_loop`)가 이걸 주기적으로 호출해
        **턴과 무관하게** 채팅이 즉시 뜨게 한다.
        """
        self.server._drain_chats()

    def update_state(self, seat, state):
        """구조화 상태(JSON)를 이 좌석에게 보낸다 — GUI 클라이언트용.

        텍스트 클라이언트는 이 메시지를 무시하면 된다(모르는 타입).
        ★ 지금 이 좌석이 입력 대기 중이면 ask(mode/data)를 상태에 실어 보낸다.
          (GUI 는 이걸로 패 클릭·화살표 같은 클릭 UI 를 띄운다.)
        """
        self._drain_chats()          # ★ 턴이 돌 때마다 쌓인 채팅을 흘려보낸다
        c = self.server.conn_of(seat)
        if not c:
            return
        if isinstance(state, dict):
            # ★ 세션(_state_dict)이 ask 를 실어 보냈으면 그게 최우선이다
            #   (targets/values 같은 클릭 UI 정보는 세션만 만들 수 있다).
            #   없을 때만 relay 가 보관한 current_ask 로 채운다.
            if "ask" not in state:
                a = self.current_ask
                state = dict(state)
                if a and a.get("seat") == seat:
                    state["ask"] = {"mode": a.get("mode"), "data": a.get("data"),
                                    "prompt": a.get("prompt")}
                else:
                    state["ask"] = None
        c.send(P.STATE, P.encode_state(state))

    def push_ask_state(self, seat, state):
        """입력이 '시작될 때' 상태를 한 번 밀어 넣는다 (클릭 UI 즉시 표시).

        ask() 는 응답을 기다리며 블록되므로, 호출 전에 이걸 불러
        브라우저가 입력창을 바로 띄우게 한다.
        """
        self.update_state(seat, state)

    def is_connected(self, seat):
        """이 좌석이 아직 연결돼 있는가.

        - CPU 좌석(conn 이 None): 항상 True (서버가 직접 플레이)
        - 사람 좌석: 소켓이 살아있고 **PING 이 끊기지 않았어야** 한다.

        ★ 브라우저 탭을 닫아도 web_server 의 소켓은 살아있다. 그래서
          `c.alive` 만 보면 '브라우저 종료'를 못 잡는다. web_server 가
          브라우저 폴링이 끊기면 PING 을 멈추므로, **PING 공백**으로 판단한다.
          (유예 10초 — F5 새로고침은 이 안에 복귀하므로 구제된다.)

        ★ 판정 기준은 서버의 `seat_alive` 한 곳에 모아 두었다 —
          재시작 투표권 판정과 **반드시 같은 기준**이어야 한다.
        """
        return self.server.seat_alive(seat)

    def on_forfeit(self, seat, text):
        """기권을 모두에게 알린다. 해당 클라이언트는 이미 끊겼으므로 제외."""
        for i, c in enumerate(self.server.conns):
            if c is not None and i != seat:
                c.send(P.SHOW, text)

    def finish(self, text):
        self._asking_seat = None
        self.server.broadcast(P.END, text)


# =============================================================================
class RelayServer:
    """클라이언트 접속을 받아 세션을 시작하는 중계 서버."""

    def __init__(self, player_count, port=DEFAULT_PORT, cpu_seats=(), host="0.0.0.0"):
        self.player_count = player_count
        self.port = port
        self.host = host
        self.cpu_seats = set(cpu_seats)
        self.conns = [None] * player_count      # 좌석별 ClientConn (CPU 좌석은 None)
        self.human_seats = set(i for i in range(player_count) if i not in self.cpu_seats)
        # 기본 이름: 사람 좌석은 'P숫자', CPU 좌석은 'CPU숫자'(1부터 순차).
        # 사람 좌석은 접속 시 입력한 이름으로 덮인다.
        self.names = []
        cpu_no = 0
        for i in range(player_count):
            if i in self.cpu_seats:
                cpu_no += 1
                self.names.append(f"CPU{cpu_no}")
            else:
                self.names.append(f"P{i+1}")
        self.ready = threading.Event()
        # ★ 브라우저 생존 판단 유예시간 (PING 공백 허용치).
        #   F5 새로고침은 이 안에 복귀하므로 구제되고, 진짜 종료만 기권된다.
        self.ping_timeout = 10.0
        # ★ 채팅 전담 스레드용 (턴과 무관한 실시간 채팅)
        self._drain_lock = threading.Lock()   # 게임 루프와 채팅 스레드의 큐 접근 배제
        self._closed = threading.Event()      # 서버 종료 신호

    # ---------------- 접속 처리 ----------------
    def conn_of(self, seat):
        return self.conns[seat] if 0 <= seat < len(self.conns) else None

    def seat_alive(self, seat):
        """★ 이 좌석이 '실제로 살아있는가' — 재시작 투표권 판정에 쓴다.

        ⚠️ `c.alive` 만 보면 **브라우저를 닫은 사람을 못 잡는다.**
           브라우저 탭을 닫아도 web_server 의 소켓은 살아있어 `alive=True` 다.
           web_server 가 폴링이 끊기면 PING 을 멈추므로, **PING 공백**까지
           확인해야 진짜 이탈을 판정할 수 있다.
           (기존 버그: 이미 나간 사람을 '살아있음'으로 세서 다시하기가
            영원히 대기했다. 세션의 is_connected 와 같은 기준을 쓴다.)

        - CPU 좌석: True (서버가 직접 플레이)
        - 사람 좌석: 소켓 살아있고 + PING 공백이 유예시간 안이어야 함
        """
        if seat in self.cpu_seats:
            return True
        c = self.conn_of(seat)
        if c is None or not c.alive:
            return False
        # ★ PING 을 한 번도 안 보낸 좌석(터미널 client.py)은 공백 검사 제외
        if c.has_pinged and (time.time() - c.last_ping) > self.ping_timeout:
            return False
        return True

    def alive_human_seats(self):
        """살아있는 사람 좌석 목록 (PING 공백까지 반영)."""
        return [s for s in sorted(self.human_seats) if self.seat_alive(s)]

    def broadcast(self, mtype, payload=""):
        for c in self.conns:
            if c is not None:
                c.send(mtype, payload)

    def _chat_loop(self):
        """★ 채팅 전담 스레드 — 게임 턴과 무관하게 CHAT 을 즉시 흘려보낸다.

        기존에는 `update_state`(= 턴이 돌 때만) 에서만 채팅을 배출해
        **다른 사람이 채팅을 쳐도 자기 턴/다음 턴까지 안 보이는** 문제가 있었다.
        여기서 0.15초마다 큐를 훑어 턴과 무관하게 실시간으로 브로드캐스트한다.
        """
        while not self._closed.is_set():
            try:
                self._drain_chats()
            except Exception:
                pass                    # 한 번 실패해도 스레드는 계속 돈다
            self._closed.wait(0.15)     # 이벤트가 서면 즉시 종료

    def _drain_chats(self):
        """★ 모든 좌석 큐에서 CHAT 만 꺼내 브로드캐스트한다 (실제 로직).

        **CHAT 만 골라 꺼내고 REPLY 등은 순서 그대로 되돌려** 넣는다.
        (큐에서 꺼낸 뒤 다시 넣으면 순서가 유지된다.)

        ★ 게임 루프 스레드와 채팅 전담 스레드가 **동시에** 호출할 수 있으므로
          `_drain_lock` 으로 상호 배제한다. 이게 없으면 REPLY 를 꺼낸 상태에서
          다른 스레드가 끼어들어 **응답이 유실**될 수 있다.
        """
        with self._drain_lock:
            for c in list(self.conns):
                if c is None or not c.alive:
                    continue
                pending = []
                while True:
                    try:
                        item = c.inbox.get_nowait()
                    except queue.Empty:
                        break
                    mtype, payload = item
                    if mtype == P.CHAT:
                        c._relay_chat(payload)
                    else:
                        pending.append(item)        # REPLY 등은 보존
                for item in pending:                # 원래 순서대로 되돌린다
                    c.inbox.put(item)

    def any_peer_lost(self, exclude_seat=None):
        """다른 좌석 중 PING 이 끊긴 사람이 있는가.

        ★ `read_reply` 블록 중 세션을 깨우는 용도. 한 사람이 응답을 안 보내
          게임 루프가 멈춰 있을 때, 다른 사람이 나가면 기권 처리가 안 된다.
          (기권 처리는 세션 루프의 `check_forfeit` 가 하는데 루프가 안 돈다.)
        """
        for i, c in enumerate(self.conns):
            if c is None or i == exclude_seat:
                continue
            if i in self.cpu_seats:
                continue
            if c.has_pinged and (time.time() - c.last_ping) > self.ping_timeout:
                return True
        return False

    def _accept_loop(self, srv):
        """필요 인원이 다 찰 때까지 접속 받기. 좌석을 순서대로 배정."""
        next_seat = 0
        while next_seat < self.player_count:
            # CPU 좌석은 건너뛴다
            while next_seat in self.cpu_seats and next_seat < self.player_count:
                next_seat += 1
            if next_seat >= self.player_count:
                break
            try:
                sock, addr = srv.accept()
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            seat = next_seat
            conn = ClientConn(sock, addr, seat)
            conn.server = self            # ★ CHAT 브로드캐스트용 서버 참조
            self.conns[seat] = conn
            # 이름 입력받기 (첫 줄)
            # ★ 타임아웃 필수 — 응답이 없으면 다음 참가자가 영영 접속하지
            #   못한다(accept 루프가 여기서 블록됨). 초과 시 기본 이름 진행.
            conn.send(P.ASK, "이름을 입력하세요 (Enter=기본, 60초):")
            nm = conn.read_reply(timeout=60)
            if nm:
                self.names[seat] = nm.strip()[:12] or self.names[seat]
            elif nm is None:
                # 연결이 끊겼다 → 이 좌석은 비워두고 다음 접속을 받는다.
                print(f"[Sys] 좌석 {seat+1} 접속 직후 끊김 — 다시 받습니다.")
                self.conns[seat] = None
                continue
            conn.send(P.HELLO, f"{seat+1} {self.names[seat]}")
            print(f"[Sys] 좌석 {seat+1} 접속: {self.names[seat]} ({addr[0]})")
            next_seat += 1
        self.ready.set()

    # ---------------- ★ 다시하기 (재시작) ----------------
    def _restart_wait(self):
        """게임 종료 후 '다시하기' 투표를 기다린다.

        규칙 (EHone 확정)
        -----------------
          - 투표권은 **살아있는 사람 좌석**만 갖는다 (CPU 는 자동 동의).
          - **전원이 누르면** 재시작한다.
          - 기권(끊김)한 사람 처리:
              ·  2인 게임 → 그 좌석을 **CPU 로 대체**해 2인 유지
              ·  3~4인 게임 → 그 사람을 **제외**하고 시작
          - 남은 사람이 1명뿐이면 게임이 안 굴러가므로 **새 접속을 기다린다**.

        Returns
        -------
        True  : 재시작한다. self.human_seats / self.cpu_seats 를 갱신해 두었다.
        False : 재시작하지 않는다 (남은 사람이 없거나 1명뿐 → 종료).
        """
        # ★ 살아있는 사람 좌석만 투표권. (CPU 좌석은 애초에 사람이 아니다.)
        #   ⚠️ c.alive 만 보면 브라우저를 닫은 사람을 못 잡는다 → seat_alive 사용
        #      (PING 공백까지 반영). 안 그러면 이미 나간 사람을 기다리며
        #      다시하기가 영원히 대기한다. (실측 버그)
        alive_humans = self.alive_human_seats()

        # ★★ CPU 가 있으면 사람이 1명이어도 게임이 굴러간다 (혼자 해보기!).
        #    예전엔 사람 수만 보고 '새 접속 대기'로 빠져서 solo 모드에서
        #    다시하기가 영영 안 됐다. 총 좌석(사람+CPU)이 2 이상이면 재시작한다.
        total_seats = len(alive_humans) + len(self.cpu_seats)

        if total_seats < 2:
            # 사람도 1명 이하, CPU 도 없음 → 새 사람을 기다린다.
            if alive_humans:
                self._broadcast_restart(0, [alive_humans[0]],
                                        extra="혼자서는 시작할 수 없습니다. "
                                              "다른 플레이어를 기다리는 중...")
                print("[Sys] 다시하기: 남은 사람이 1명 — 새 접속 대기")
            return self._wait_for_more_players(len(alive_humans))

        print(f"[Sys] 다시하기 대기 — 전원 동의 필요 "
              f"(살아있는 사람 {len(alive_humans)}명: "
              f"{[self.names[s] for s in alive_humans]})")
        # ★ 투표 초기화
        for s in alive_humans:
            self.conns[s].voted_restart = False
        self._broadcast_restart(0, alive_humans)

        while True:
            time.sleep(0.2)
            # 살아있는 사람 좌석을 다시 계산 (투표 중에 또 나갈 수 있다)
            # ★ PING 공백까지 반영해야 한다 (c.alive 만 보면 안 됨)
            alive_humans = [s for s in alive_humans if self.seat_alive(s)]
            if not alive_humans:
                print("[Sys] 다시하기: 남은 사람 없음 — 종료")
                return False
            # ★ CPU 가 있으면 1명이어도 게임이 굴러간다 (혼자 해보기).
            #   사람도 없고 CPU 도 없을 때만 새 접속을 기다린다.
            if len(alive_humans) + len(self.cpu_seats) < 2:
                print("[Sys] 다시하기: 1명만 남음 — 새 접속 대기")
                return self._wait_for_more_players(len(alive_humans))

            voted = [s for s in alive_humans if self.conns[s].voted_restart]
            self._broadcast_restart(len(voted), alive_humans)
            if len(voted) == len(alive_humans):
                print("[Sys] 다시하기: 전원 동의 → 새 게임을 시작합니다.")
                self._apply_restart_roster(alive_humans)
                return True

    def _wait_for_more_players(self, have):
        """사람이 1명(또는 0명)뿐일 때 새 접속을 기다린다.

        이미 자리(conns)는 살아있으므로, **비어 있는 좌석**으로 새 접속을
        받아 채운 뒤 재시작한다. 새 접속이 없으면 False.
        """
        deadline = time.time() + 300.0      # 5분까지 기다려 본다
        while time.time() < deadline:
            time.sleep(0.4)
            humans = self.alive_human_seats()
            if len(humans) >= 2:
                print(f"[Sys] 다시하기: 새 플레이어 합류 — {len(humans)}명으로 시작")
                for s in humans:
                    self.conns[s].voted_restart = False
                self._apply_restart_roster(humans)
                return True
        print("[Sys] 다시하기: 대기 시간 초과 — 종료")
        return False

    def _apply_restart_roster(self, alive_humans):
        """재시작 좌석 구성 확정 (EHone 규칙).

        · **CPU 좌석은 항상 남는다** (CPU 는 기권하지 않는다).
        · 사람이 기권했을 때:
            - 2인 게임 → 그 좌석을 **CPU 로 대체**해 2인 유지
            - 3~4인  → 그 사람을 **제외**하고 인원을 줄인다
        · 사람이 아무도 안 나갔으면 **인원·좌석 그대로** (CPU 포함).

        ★★ 좌석 재배치(remap)가 핵심이다.
           Session 은 좌석 번호를 0..player_count-1 로 강제한다
           (names[i] 인덱싱, game.players[i] 순회). 그래서 3인에서 좌석 1 이
           나가면 살아있는 {0,2} 를 그대로 넘길 수 없다 — 반드시
           **0..k-1 로 다시 매핑**해야 한다. (안 하면 IndexError 로 서버가 죽어
           '다시하기를 눌러도 아무 일이 안 일어나는' 증상이 된다.)

           remap 하면서 conns/names 도 함께 옮긴다. 그래야 이후 턴 진행,
           PING 감시, 브로드캐스트가 새 좌석 기준으로 동작한다.
        """
        alive_humans = sorted(alive_humans)
        cpu = sorted(self.cpu_seats)      # ★ CPU 는 언제나 유지

        # ---- 사람이 아무도 안 나갔으면 구성 유지 ----
        if len(alive_humans) == len(self.human_seats):
            # 좌석이 바뀌지 않았으니 names/conns 도 그대로 둔다.
            self.human_seats = set(alive_humans)
            print(f"[Sys] 다시하기 구성: 사람 {len(alive_humans)}명 + "
                  f"CPU {len(cpu)}명 — 그대로")
            return

        # ---- 2인 게임에서 1명 나감 → 그 자리를 CPU 로 채워 2인 유지 ----
        if self.player_count == 2 and len(alive_humans) == 1:
            seat = alive_humans[0]
            other = 1 - seat
            self.cpu_seats = {other}
            self.human_seats = {seat}
            self.names[other] = "CPU1"
            if self.conns[other] is not None:
                self.conns[other].close()
                self.conns[other] = None
            print(f"[Sys] 다시하기 구성: {self.names[seat]} + CPU1 — 2인 유지")
            return

        # ---- 사람이 나감 → 살아있는 사람 + CPU 로 새 좌석 목록을 만든다 ----
        #      (사람 먼저, CPU 뒤 — CPU 는 항상 뒤쪽 좌석이라는 관례 유지)
        living = alive_humans + cpu
        if living == list(range(len(living))):
            # 이미 0..k-1 이면 이동 불필요. 길이만 잘라낸다.
            for s in range(len(living), len(self.conns)):
                if self.conns[s] is not None:
                    self.conns[s].close()
            self.conns = self.conns[:len(living)]
            self.names = self.names[:len(living)]
            self.human_seats = set(range(len(alive_humans)))
            self.cpu_seats = set(range(len(alive_humans), len(living)))
            self.player_count = len(living)
            print(f"[Sys] 다시하기 구성: 사람 {len(alive_humans)}명 + "
                  f"CPU {len(cpu)}명 {self.names} — 좌석 유지")
            return

        new_conns, new_names = [], []
        for new_seat, old_seat in enumerate(living):
            c = self.conns[old_seat]
            if c is not None:
                c.seat = new_seat           # ★ 클라이언트 좌석번호 갱신
            new_conns.append(c)
            new_names.append(self.names[old_seat])
        # 빠진 좌석의 소켓 정리
        for old_seat in range(len(self.conns)):
            if old_seat not in living and self.conns[old_seat] is not None:
                self.conns[old_seat].close()
        self.conns = new_conns
        self.names = new_names
        self.human_seats = set(range(len(alive_humans)))
        self.cpu_seats = set(range(len(alive_humans), len(living)))
        self.player_count = len(living)
        print(f"[Sys] 다시하기 구성: 사람 {len(alive_humans)}명 + "
              f"CPU {len(cpu)}명 {self.names} — 좌석 재배치 "
              f"{living} → {list(range(len(living)))}")

    def _broadcast_restart(self, voted, voters, extra=None):
        """다시하기 현황을 모두에게 알린다 (STATE 가 아닌 전용 메시지)."""
        payload = json.dumps({
            "voted": voted, "total": len(voters),
            "names": [self.names[s] for s in voters],
            "voted_names": [self.names[s] for s in voters
                            if self.conns[s] is not None
                            and self.conns[s].voted_restart],
            "extra": extra or "",
        }, ensure_ascii=False)
        self.broadcast(P.RESTARTED, payload)

    # ---------------- 실행 ----------------
    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(8)
        print("=" * 52)
        print(f"   다빈치 코드 릴레이 서버 — 인원 {self.player_count}")
        print(f"   포트 {self.port} · 사람 좌석 {sorted(self.human_seats)}")
        if self.cpu_seats:
            print(f"   CPU 좌석 {sorted(s for s in self.cpu_seats)}")
        else:
            print("   ※ 전원 사람입니다. 아무도 추측하지 않으면 게임이 "
                  "진행되지 않습니다.")
        print("   참가자들은 client.py 로 접속하세요.")
        print("=" * 52)
        print(f"[Sys] 대기 중... (접속 필요: {len(self.human_seats)}명)")
        print(f"[Sys] 내 IP: {_local_ip()}  (다른 기기는 --host 로 접속)")

        acc = threading.Thread(target=self._accept_loop, args=(srv,), daemon=True)
        acc.start()
        # ★ 채팅 전담 스레드 — 게임 턴과 무관하게 CHAT 을 즉시 배출한다.
        chat = threading.Thread(target=self._chat_loop, daemon=True)
        chat.start()
        self.ready.wait()

        if not any(c is not None for c in self.conns):
            print("[Sys] 접속자가 없습니다. 종료.")
            srv.close()
            return
        print("[Sys] 게임을 시작합니다.")

        io = RelayOutput(self)
        # 추리 결과 읽을 여유. 환경변수 GUESS_DELAY 로 조절 (기본 1초).
        import os as _os
        guess_delay = float(_os.environ.get("GUESS_DELAY", "1.0"))

        # ★ 재시작 루프 — 게임이 끝나면 '다시하기' 투표를 받아 다시 돌린다.
        while True:
            session = Session(
                io, self.player_count,
                names=list(self.names),
                human_seats=self.human_seats,
                rng=random.Random(),
                delay=guess_delay,
            )
            try:
                session.run()
            except Exception as e:  # 서버가 죽어도 클라이언트에 알린다
                import traceback
                traceback.print_exc()
                self.broadcast(P.END, f"서버 오류로 게임이 중단되었습니다: {e}")
                break

            # ---- 게임 종료 → 다시하기 투표 대기 (소켓은 살려 둔다) ----
            try:
                if not self._restart_wait():
                    break
            except Exception as e:
                # ★ 예외 내용을 남겨야 원인 파악이 된다(traceback 만으론 놓치기 쉬움).
                import traceback
                print(f"[Sys] 다시하기 대기 중 오류: {e}")
                traceback.print_exc()
                break
            # 좌석 구성이 바뀌었을 수 있으므로 다음 게임은 새 session 으로.
            print("[Sys] 새 게임을 시작합니다.")

        # ---- 정리 ----
        self._closed.set()      # ★ 채팅 스레드 종료 신호
        time.sleep(0.5)
        for c in self.conns:
            if c is not None:
                c.close()
        srv.close()
        print("[Sys] 종료.")


# =============================================================================
def parse_args(argv):
    ap = argparse.ArgumentParser(description="다빈치 코드 릴레이 서버")
    ap.add_argument("players", type=int, nargs="?", default=2,
                    help="인원 (2~4)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--cpu", type=int, default=0,
                    help="CPU(자동) 좌석 수. 뒤쪽 좌석부터 채운다.")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if not (2 <= args.players <= 4):
        print("인원은 2~4.")
        return 1
    cpu = max(0, min(args.cpu, args.players - 1))
    cpu_seats = set(range(args.players - cpu, args.players))
    server = RelayServer(args.players, port=args.port, cpu_seats=cpu_seats)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
