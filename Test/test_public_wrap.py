# -*- coding: utf-8 -*-
"""공개 목록 줄바꿈 + 좀비 정리 헬퍼 검증."""
import random

from session import Session, SilentOutput


def main():
    checks = []

    # ---- 1) _public_lines 줄바꿈 단위 검증 ----
    io = SilentOutput()
    s = Session(io, 3, human_seats={0}, rng=random.Random(0))

    class FakeCard:
        def __init__(self, name):
            self._n = name

        def display(self):
            return self._n

    def set_pubs(n):
        s.game.table.public = [FakeCard(f"c{i:02d}") for i in range(n)]

    # 0개 → 빈 리스트
    set_pubs(0)
    checks.append(("0개 → 빈 목록", s._public_lines() == []))
    # 13개 → 1줄
    set_pubs(13)
    lines = s._public_lines()
    checks.append(("13개 → 1줄", len(lines) == 1 and "[공개]" in lines[0]))
    # 14개 → 2줄
    set_pubs(14)
    lines = s._public_lines()
    checks.append(("14개 → 2줄", len(lines) == 2))
    checks.append(("2줄째 들여쓰기 정렬",
                   lines[1].startswith(" " * len("   [공개] "))))
    # 27개 → 3줄
    set_pubs(27)
    lines = s._public_lines()
    checks.append(("27개 → 3줄", len(lines) == 3))

    print("=== 14개일 때 실제 출력 ===")
    set_pubs(14)
    for l in s._public_lines():
        print("   " + repr(l))
    print()

    # ---- 2) _board_text 안에도 반영되는지 ----
    s2 = Session(SilentOutput(), 3, human_seats={0}, rng=random.Random(1))
    g = s2.game
    per = g.table.cards_per_player(3)
    for p in g.players:
        p.black_deal_count = 0 if p.is_human else 1
    g.deal()
    for p in g.players:
        p.sort_hand()
    g.table.public = [FakeCard(f"c{i:02d}") for i in range(20)]
    txt = s2._board_text(0, None, False)
    n_public_lines = sum(1 for l in txt.splitlines() if "[공개]" in l
                         or l.startswith(" " * len("   [공개] ")))
    checks.append(("_board_text 에서도 2줄 이상", n_public_lines >= 2))

    # ---- 3) testutil 좀비 정리 함수 존재/동작 (빈 포트는 아무것도 안 죽임) ----
    import testutil
    k = testutil.free_port(9999, verbose=False)
    checks.append(("빈 포트 → 정리 대상 없음", k == []))

    print("[판정]")
    allok = True
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print("=" * 50)
    print("ALL PASS" if allok else "SOME FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
