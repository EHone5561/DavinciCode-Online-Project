# -*- coding: utf-8 -*-
"""대기 화면 검증 — 남의 턴일 때 자기 패가 보이는지 확인."""

import random
from session import Session, SilentOutput


class LogIo(SilentOutput):
    """show/show_me/wait 를 구분해 기록."""

    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, seat, text):
        self.log.append((f"WAIT#{seat}", text))
        self.waits.append((seat, text))

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "추측" in prompt:
            return "q"
        if "검은 카드" in prompt:
            return "1"
        return "0"


def main():
    # ★ 전원 사람이 계속 'q'만 보내면 게임이 안 끝난다(공개가 없으므로).
    #   그래서 일부 좌석을 CPU 로 두어 게임이 실제로 진행되게 한다.
    #   대기 화면은 '사람 좌석'에만 가므로, 사람 좌석이 2명 이상이면 관찰 가능.
    io = LogIo()
    s = Session(io, 4, human_seats={0, 1}, rng=random.Random(3))   # 사람2 + CPU2
    s.delay = 0
    s.run()

    print("=== 대기(WAIT) 메시지 ===")
    if not io.waits:
        print("  (없음)")
    for seat, text in io.waits[:3]:
        print(f"  [좌석{seat}]")
        for line in text.strip().splitlines():
            print(f"    {line}")

    # 검증: 대기 화면에 '내 패'와 '지금 ... 님의 차례'가 있어야
    ok1 = len(io.waits) > 0
    ok2 = any("내 패" in t for _s, t in io.waits)
    ok3 = any("님의 차례입니다" in t for _s, t in io.waits)
    # 공개 카드가 없는 초반엔 [공개] 줄이 없을 수 있다.
    #   → 공개가 하나라도 생기면 그 뒤 대기 화면엔 포함돼야 한다.
    has_public_any = any(
        "[공개]" in t for k, t in io.log if k.startswith("SHOW"))
    if has_public_any:
        ok4 = any("[공개]" in t for _s, t in io.waits)
    else:
        ok4 = True          # 아직 공개가 없었으니 검사 대상 아님
    # 대기 화면이 턴 주인에게는 안 가야 함 (자기 턴엔 show_me)
    print()
    print("대기 화면 발생:", "✅" if ok1 else "❌")
    print("내 패 표시:", "✅" if ok2 else "❌")
    print("턴 주인 안내:", "✅" if ok3 else "❌")
    print("공개 목록 포함:", "✅" if ok4 else "❌")
    print()
    print("=" * 50)
    print("PASS ✅" if all([ok1, ok2, ok3, ok4]) else "FAIL ❌")


if __name__ == "__main__":
    main()
