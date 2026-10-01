# -*- coding: utf-8 -*-
"""추측 페이즈 후보 값이 공개 정보에 따라 줄어드는지 검증.

EHone 요청: "게임이 진행되면서 공개 정보가 많아질수록, 추측 페이즈 때
밑에 나타나는 정답 지목 후보 패가 줄어들어야 하는데 안 줄어든다.
테이블에서 보이는 패는 지목하지 않게 해야지."

규칙: 지목 가능 값 = 전체 값 - 내 패 값 - **이미 공개된 카드 값**

검증:
  1) _state_dict 의 ask.values 가 table.public 을 제외하는지
  2) 공개 카드가 늘면 후보가 실제로 줄어드는지 (단조 감소)
  3) _parse_guess 가 공개된 값을 거부하는지

실행: python -E -X utf8 test_guess_candidates.py
"""
import random

from session import Session, SilentOutput


def setup(n=4, humans={0}, seed=1):
    io = SilentOutput()
    s = Session(io, n, human_seats=humans, rng=random.Random(seed))
    g = s.game
    for p in g.players:
        p.black_deal_count = 0 if p.is_human else 1
    g.deal()
    for p in g.players:
        p.sort_hand()
    return s, g


def guess_values(s, seat):
    """해당 좌석이 추측 입력 중일 때 후보 values 목록."""
    st = s._state_dict(seat, pending_ask=("guess", None, "추측 :"))
    return set(st["ask"]["values"])


def check_public_excluded():
    """공개된 카드 값이 후보에서 빠지는지."""
    s, g = setup()
    before = guess_values(s, 0)

    # 상대(좌석1) 카드 하나를 강제로 공개
    victim = g.players[1]
    card = victim.own_cards[0]
    victim.reveal(card)
    g.table.public.append(card)

    after = guess_values(s, 0)

    print(f"   공개 카드: {card.display()}")
    print(f"   후보 수: {len(before)} → {len(after)}")
    print(f"   '{card.display()}' 가 후보에서 빠졌나: {card.display() not in after}")

    checks = []
    checks.append(("공개 전엔 후보에 있었음", card.display() in before))
    checks.append(("공개 후엔 후보에서 빠짐", card.display() not in after))
    checks.append(("후보 수가 줄어듦", len(after) < len(before)))
    return checks


def check_monotonic():
    """공개 카드가 늘수록 후보가 단조 감소하는지."""
    s, g = setup()
    counts = [len(guess_values(s, 0))]
    print(f"   초기 후보 수: {counts[0]}")

    for i in range(1, 4):
        victim = g.players[i % len(g.players)]
        hidden = [c for c in victim.own_cards if c not in victim.revealed_cards]
        if not hidden:
            continue
        card = hidden[0]
        victim.reveal(card)
        g.table.public.append(card)
        n = len(guess_values(s, 0))
        counts.append(n)
        print(f"   +공개 {card.display()} → 후보 {n}")

    mono = all(counts[i] >= counts[i+1] for i in range(len(counts)-1))
    checks = []
    checks.append(("단조 감소", mono))
    checks.append(("최종이 최초보다 적음", counts[-1] < counts[0]))
    return checks


def check_parse_rejects():
    """수동 입력도 공개된 값을 거부하는지.

    ★ 자리 검사(이미 공개된 자리)에 먼저 걸리지 않도록,
      공개 카드의 '주인'이 아닌 다른 상대를 지목 대상으로 삼는다.
    """
    s, g = setup()
    # 좌석2 의 카드를 공개 (좌석1 을 지목할 것이므로 자리 검사에 안 걸린다)
    victim = g.players[2]
    card = victim.own_cards[0]
    victim.reveal(card)
    g.table.public.append(card)

    # 좌석0 이 좌석1(번호 2)의 아직 안 공개된 자리를, 공개된 값으로 지목 시도
    raw = f"2 1 {card.display()}"
    res = s._parse_guess(0, raw)
    print(f"   공개 카드: {card.display()} (좌석2)")
    print(f"   입력: '{raw}' → {res}")

    checks = []
    checks.append(("공개값 지목 거부", isinstance(res, tuple)
                   and res[0] == "ERR" and "공개" in res[1]))
    return checks


def main():
    all_checks = []
    print("=== 1) 공개 카드 제외 ===")
    all_checks += check_public_excluded()
    print("\n=== 2) 후보 단조 감소 ===")
    all_checks += check_monotonic()
    print("\n=== 3) 수동 입력 검증 ===")
    all_checks += check_parse_rejects()

    print("\n=== 검증 결과 ===")
    ok_all = True
    for name, ok in all_checks:
        print(f"   [{'OK ' if ok else 'FAIL'}] {name}")
        ok_all = ok_all and ok
    print()
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
