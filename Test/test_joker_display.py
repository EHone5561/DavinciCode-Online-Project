# -*- coding: utf-8 -*-
"""조커 삽입 시 '내 패 표시' 검증 — 표시되는 텍스트를 확인한다."""

import random

import DavinciCode as md
from session import Session, SilentOutput


class LogIo(SilentOutput):
    """show_me/ask 를 그대로 기록만 한다."""

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "슬롯" in prompt:
            return "2"          # 슬롯 2 선택
        if "조커" in prompt:
            return "0"          # 앞(front)
        if "추측" in prompt:
            return "q"
        if "검은 카드" in prompt:
            return "1"
        return ""


def test_joker_slot():
    """조커를 뽑았을 때: '조커 뽑음' 안내 + 슬롯 번호가 보이는 라인."""
    io = LogIo()
    s = Session(io, 2, human_seats={0}, rng=random.Random(1))
    dec = None
    # _SeatDecider 를 직접 만들어 조커 슬롯 질문을 흉내낸다
    from session import _SeatDecider
    game = s.game
    # 가짜 라인 구성
    p = game.players[0]
    p.own_cards = [md._spec_to_card(x) for x in ("2b", "5w", "7b")]
    dec = _SeatDecider(s, 0)
    jcard = md.Card(None, True)      # Jb
    slot = dec.select_joker_slot(jcard, len(p.own_cards))

    print("=== 조커 슬롯 질문 ===")
    for k, v in io.log:
        print(f"  [{k}] {v}")
    print(f"  → 선택된 슬롯: {slot}")
    print()
    texts = " ".join(v for _k, v in io.log)
    ok1 = "조커(Jb) 를 뽑았습니다" in texts
    ok2 = "슬롯0 [2b] 슬롯1 [5w] 슬롯2 [7b] 슬롯3" in texts
    print("  조커 안내 표시:", "✅" if ok1 else "❌")
    print("  슬롯 번호 표시:", "✅" if ok2 else "❌")
    return ok1 and ok2


def test_joker_side():
    """숫자가 조커에 걸렸을 때: 현재 패 + 새 카드가 표시."""
    io = LogIo()
    s = Session(io, 2, human_seats={0}, rng=random.Random(1))
    from session import _SeatDecider
    game = s.game
    p = game.players[0]
    p.own_cards = [md._spec_to_card(x) for x in ("2b", "Jb", "7b")]
    dec = _SeatDecider(s, 0)
    ncard = md._spec_to_card("5b")
    side = dec.ask_joker_side_full("Jb", ncard)

    print("=== 조커 앞뒤 질문 ===")
    for k, v in io.log:
        print(f"  [{k}] {v}")
    print(f"  → 선택: {side}")
    print()
    texts = " ".join(v for _k, v in io.log)
    ok1 = "<내 패(현재)>" in texts
    ok2 = "5b" in texts
    print("  현재 패 표시:", "✅" if ok1 else "❌")
    print("  새 카드 표시:", "✅" if ok2 else "❌")
    return ok1 and ok2


if __name__ == "__main__":
    r1 = test_joker_slot()
    print()
    r2 = test_joker_side()
    print()
    print("=" * 50)
    print("전체:", "PASS ✅" if (r1 and r2) else "FAIL ❌")
