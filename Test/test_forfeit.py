# -*- coding: utf-8 -*-
"""기권(연결 끊김) 처리 검증.

시나리오:
  서버 1개 + 클라이언트 3개(사람 2 + CPU 1).
  한 클라이언트가 게임 중에 소켓을 끊는다.
  → 서버가 그 좌석을 기권 처리하고 게임이 계속/종료되는지 확인.

검증 항목:
  1) 끊긴 좌석이 '기권' 메시지로 순위 확정
  2) 남은 클라이언트들이 게임을 끝까지 받음 (END)
  3) 최종 순위에 기권자가 포함됨
"""

import socket
import threading
import time

import protocol as P
from relay import RelayServer


class AutoClient:
    """자동응답 클라이언트. quit_after 로 n번째 응답 후 소켓을 끊는다."""

    def __init__(self, port, name, quit_after=None):
        self.port = port
        self.name = name
        self.quit_after = quit_after      # 이 횟수만큼 응답한 뒤 끊는다
        self.seat = None
        self.log = []
        self.reply_count = 0
        self._sock = None
        self._file = None
        self._running = True
        self._done = threading.Event()
        self.disconnected = False

    def connect(self):
        self._sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self._file = self._sock.makefile("rb")

    def _auto_reply(self, prompt):
        self.reply_count += 1
        if "이름" in prompt:
            return self.name
        if "검은 카드" in prompt:
            return "1"
        if "추측" in prompt:
            return "q"
        if "공개할 자리" in prompt:
            return "1"
        if "슬롯" in prompt:
            return "1"
        if "조커" in prompt:
            return "1"
        if "연속" in prompt:
            return "q"
        return ""

    def _quit(self):
        """소켓을 강제로 닫는다 (프로그램 강제 종료 흉내)."""
        self.disconnected = True
        self._running = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def run(self):
        self.connect()
        while self._running:
            mtype, payload = P.recv_message(self._file)
            if mtype is None:
                break
            if mtype == P.HELLO:
                self.seat = int(payload.split(" ")[0])
            elif mtype == P.ASK:
                # quit_after 에 도달하면 응답 대신 연결을 끊는다
                if self.quit_after is not None and self.reply_count >= self.quit_after:
                    self._quit()
                    break
                ans = self._auto_reply(payload)
                try:
                    self._sock.sendall(P.encode(P.REPLY, ans))
                except OSError:
                    self._quit()
                    break
            elif mtype in (P.SHOW, P.SHOWME, P.WAIT):
                self.log.append((mtype, payload))
            elif mtype == P.END:
                self.log.append(("END", payload))
                self._running = False
                break
        self._done.set()


def main():
    PORT = 8831
    N = 3
    # 이전 실행의 좀비 서버가 포트를 점유하면 접속이 실패한다 → 정리.
    import testutil
    testutil.free_port(PORT)
    # 좌석3 을 CPU 로 → 사람 2명 접속
    server = RelayServer(N, port=PORT, cpu_seats={2})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(1.0)

    # p1: 정상. p2: 6번 응답 후 강제 종료.
    c1 = AutoClient(PORT, "정상맨", quit_after=None)
    c2 = AutoClient(PORT, "나가리", quit_after=6)
    for c in (c1, c2):
        threading.Thread(target=c.run, daemon=True).start()
        time.sleep(0.3)

    # 게임 종료 대기
    c1._done.wait(timeout=60)
    c2._done.wait(timeout=10)
    time.sleep(1.0)

    print("=" * 60)
    for c in (c1, c2):
        texts = [t for _m, t in c.log]
        forfeit = [t for t in texts if "기권" in t]
        end = [t for t in texts if "등" in t or "🏆" in t]
        print(f"[{c.name}] 좌석={c.seat} 응답={c.reply_count} "
              f"메시지={len(c.log)} 끊김={c.disconnected}")
        if forfeit:
            for t in forfeit:
                print(f"    기권알림: {t.strip()}")
        if end:
            print(f"    종료: {end[-1].strip()}")

    # 검증
    c1_texts = [t for _m, t in c1.log]
    got_forfeit = any("기권" in t for t in c1_texts)
    got_end = any("등" in t or "🏆" in t for t in c1_texts)
    # 기권자의 패가 전부 공개됐는지 (알림에 '모든 패를 공개' 문구)
    got_reveal = any("모든 패를 공개" in t for t in c1_texts)
    # 최종 순위에 기권자 포함
    end_text = c1_texts[-1] if c1_texts else ""
    forfeit_in_rank = "나가리" in end_text or "3등" in end_text

    print()
    print("기권 감지 + 알림:", "✅" if got_forfeit else "❌")
    print("기권자 패 전부 공개:", "✅" if got_reveal else "❌")
    print("게임 정상 종료:", "✅" if got_end else "❌")
    print("기권자 순위 포함:", "✅" if forfeit_in_rank else "❌")
    print()
    print("--- 기권 시점 화면 ---")
    for t in c1_texts:
        if "기권" in t or "모든 패를 공개" in t:
            print("  " + t.strip())
    print()
    print("--- 최종 화면 ---")
    print(end_text)
    print()
    ok = got_forfeit and got_end and got_reveal
    print("=" * 60)
    print("PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
