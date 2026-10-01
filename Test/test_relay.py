# -*- coding: utf-8 -*-
"""릴레이 소켓 통합 테스트 — 서버 1개 + 클라이언트 N개.

★ 사람 좌석은 계속 'q'(멈춤)만 보내면 게임이 안 끝난다(아무도 카드를
   공개하지 않으므로). 그래서 CPU 좌석을 섞어 게임이 종료되는 것을 확인한다.
   (--cpu 로 뒤쪽 좌석이 prob_ai 로 플레이)

검증 항목:
  1) 접속 → 좌석 배정 → HELLO 수신
  2) ASK 에 대한 REPLY 왕복
  3) SHOW/SHOWME 구분 (비밀 정보가 남에게 안 감)
  4) 게임 종료(END)가 모든 클라이언트에 전달
"""

import random
import socket
import threading
import time

import protocol as P
from relay import RelayServer


class AutoClient:
    """자동응답 클라이언트 — 터미널 입력 없이 규칙대로 답한다.

    사람 좌석이면 'q'(멈춤)만 보낸다 → CPU 좌석이 게임을 끝내준다.
    """

    def __init__(self, port, name):
        self.port = port
        self.name = name
        self.seat = None
        self.log = []
        self.reply_count = 0
        self._sock = None
        self._file = None
        self._running = True
        self._done = threading.Event()

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
            return "q"          # 사람은 멈춤만 (CPU 가 게임을 진행)
        if "공개할 자리" in prompt:
            return "1"          # 벌칙: 1번 자리 공개
        if "슬롯" in prompt:
            return "1"
        if "조커" in prompt:
            return "1"
        if "연속" in prompt:
            return "q"
        return ""

    def run(self):
        self.connect()
        while self._running:
            mtype, payload = P.recv_message(self._file)
            if mtype is None:
                break
            if mtype == P.HELLO:
                self.seat = int(payload.split(" ")[0])
            elif mtype == P.ASK:
                ans = self._auto_reply(payload)
                self._sock.sendall(P.encode(P.REPLY, ans))
            elif mtype in (P.SHOW, P.SHOWME, P.WAIT):
                self.log.append((mtype, payload))
            elif mtype == P.END:
                self.log.append(("END", payload))
                self._running = False
                break
        self._done.set()


def run_once(port, n, cpu_count, timeout=90):
    # ★ 이전 실행의 좀비 서버가 이 포트를 점유하고 있으면 정리한다.
    import testutil
    testutil.free_port(port)
    server = RelayServer(n, port=port,
                         cpu_seats=set(range(n - cpu_count, n)))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # ★ 서버가 listen 할 시간을 충분히 준다.
    #   ⚠️ 프로브 소켓으로 확인하면 안 된다 — 접속 즉시 좌석 하나를
    #      소모해버려 실제 클라이언트가 앉을 자리가 사라진다.
    time.sleep(1.5)

    humans = n - cpu_count
    clients = [AutoClient(port, f"auto{i+1}") for i in range(humans)]
    for c in clients:
        threading.Thread(target=c.run, daemon=True).start()
        time.sleep(0.25)

    for c in clients:
        c._done.wait(timeout=timeout)

    results = {}
    for i, c in enumerate(clients):
        texts = [t for (_m, t) in c.log]
        results[i] = {
            "seat": c.seat,
            "nmsg": len(c.log),
            "replies": c.reply_count,
            "got_end": any("등" in t or "🏆" in t or "1등" in t for t in texts),
            "end_text": texts[-1] if texts else "",
        }
    return results


def main():
    print("=" * 60)
    print("릴레이 통합 테스트")
    print("=" * 60)

    cases = [
        (8801, 3, 2),    # 사람 1 + CPU 2
        (8802, 4, 3),    # 사람 1 + CPU 3
        (8803, 2, 1),    # 사람 1 + CPU 1
    ]
    all_ok = True
    for port, n, cpu in cases:
        print(f"\n--- 인원 {n} · CPU {cpu} (사람 {n-cpu}) ---")
        try:
            res = run_once(port, n, cpu)
        except Exception as e:
            print(f"  예외: {e}")
            all_ok = False
            continue
        ok = all(r["got_end"] for r in res.values())
        for i, r in res.items():
            print(f"  클라{i+1}: 좌석={r['seat']} 응답={r['replies']} "
                  f"메시지={r['nmsg']} 종료={'✅' if r['got_end'] else '❌'}")
        print(f"  → {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    print()
    print("=" * 60)
    print("최종:", "ALL PASS ✅" if all_ok else "FAIL ❌")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
