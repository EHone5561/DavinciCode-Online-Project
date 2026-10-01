# -*- coding: utf-8 -*-
"""session.py 검증 — SilentOutput 으로 게임이 끝까지 도는지 확인.

전부 사람 좌석이지만 SilentOutput 이 자동응답(q=멈춤)하므로
사람이 추측을 안 해서 게임이 안 끝날 수 있다.
→ 검증에서는 좌석을 전부 CPU 로 두고 prob_ai 가 플레이하게 한다.
"""

import random
import sys

from session import Session, SilentOutput


def run_case(player_count, human_seats):
    io = SilentOutput()
    s = Session(io, player_count, human_seats=human_seats,
                rng=random.Random(1234))
    s.run()
    end = [t for (k, t) in io.log if k == "END"]
    return end[0] if end else "(END 없음)", len(io.log)


if __name__ == "__main__":
    # ① 전부 CPU (가장 많이 도는 케이스)
    for n in (2, 3, 4):
        text, nlog = run_case(n, human_seats=set())
        lines = [l for l in text.splitlines() if "등" in l or "🏆" in l]
        print(f"== {n}인 전부CPU ==")
        print("  메시지수:", nlog)
        for l in lines:
            print("  " + l.strip())
        print()

    # ② 사람 1 + CPU (사람은 자동응답 = 'q' 멈춤)
    text, nlog = run_case(3, human_seats={0})
    print("== 3인 사람1+CPU2 (사람은 멈춤만) ==")
    print("  메시지수:", nlog)
    print("  " + text.strip().splitlines()[-1].strip())
