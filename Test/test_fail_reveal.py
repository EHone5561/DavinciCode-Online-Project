# -*- coding: utf-8 -*-
"""덱 소진 오답 시 '공개할 자리 선택' 동작 검증."""

import random

import DavinciCode as md
from session import Session, SilentOutput


class PickIo(SilentOutput):
    """'공개할 자리' 질문에 특정 번호를 답하는 IO."""

    def __init__(self, pick="2"):
        super().__init__()
        self.pick = pick
        self.reveal_asks = 0

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "공개할 자리" in prompt:
            self.reveal_asks += 1
            return self.pick
        if "추측" in prompt:
            return "q"
        if "검은 카드" in prompt:
            return "1"
        return "0"


def main():
    # 2인: 사람 1 + CPU 1. 덱을 강제로 비우고 상황을 만든다.
    io = PickIo(pick="2")
    s = Session(io, 2, human_seats={0}, rng=random.Random(5))
    game = s.game
    for p in game.players:
        p.black_deal_count = 1
    game.deal()
    for p in game.players:
        p.sort_hand()
    game.start_first_turn()

    # 사람 좌석을 턴 주인으로 만들고, 덱을 비운다.
    game.turn_index = 0
    game.table.deck = []
    me = game.players[0]
    # 아직 아무것도 공개 안 된 상태
    assert not me.revealed_cards

    before_hidden = [i for i, c in enumerate(me.own_cards, 1)
                     if c not in me.revealed_cards]
    print(f"사람 패: {[c.display() for c in me.own_cards]}")
    print(f"비공개 자리: {before_hidden}")
    print(f"덱: {len(game.table.deck)}장")
    print()

    # _ask_fail_reveal_pos 를 직접 호출 (덱 소진 오답 경로)
    pos = s._ask_fail_reveal_pos(0)
    print(f"→ 선택된 자리: {pos}")
    pen = me.own_cards[pos - 1]
    me.reveal(pen)
    print(f"→ 공개된 카드: {pen.display()}")
    print()

    # 검증
    ok1 = pos == 2
    ok2 = pen.display() == [c.display() for c in me.own_cards][1]
    ok3 = any("공개할 자리" in v for _k, v in io.log)
    ok4 = any("<내 패>" in v and "* = 아직 비공개" in v for _k, v in io.log)
    print("선택한 자리가 반영됨:", "✅" if ok1 and ok2 else "❌")
    print("'공개할 자리' 질문 발생:", "✅" if ok3 else "❌")
    print("후보 미리보기 표시:", "✅" if ok4 else "❌")
    print()
    print("--- 실제 출력 ---")
    for k, v in io.log:
        if "공개할 자리" in v or "<내 패>" in v or "벌칙으로 공개할" in v:
            print(f"  [{k}] {v.strip()}")
    print()
    print("=" * 50)
    print("PASS ✅" if (ok1 and ok2 and ok3 and ok4) else "FAIL ❌")


if __name__ == "__main__":
    main()
