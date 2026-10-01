# -*- coding: utf-8 -*-
"""빈 Enter 재질문 + 실패 상한 10회 검증 (session._parse_guess 단위)."""
import session as S

from DavinciCode import Game


def _deal(ses):
    """세션 게임에 실제 딜을 수행 (테스트용)."""
    game = ses.game
    per = game.table.cards_per_player(len(game.players))
    for p in game.players:
        p.black_deal_count = 0 if p.is_human else ses.rng.randint(0, per)
    game.deal()
    for p in game.players:
        p.sort_hand()
    return game


def main():
    game = Game(3)
    # 사람 좌석 0, CPU 좌석 나머지
    ses = S.Session(S.SilentOutput(), 3, human_seats={0},
                    rng=__import__("random").Random(0))
    game = _deal(ses)
    seat = 0

    checks = []
    # 1) 빈 문자열 → ERR (멈춤 아님)
    r = ses._parse_guess(seat, "")
    checks.append(("빈 Enter → ERR(재질문)", isinstance(r, tuple)
                   and r[0] == "ERR"))
    # 2) 공백만 → ERR
    r = ses._parse_guess(seat, "   ")
    checks.append(("공백만 → ERR", isinstance(r, tuple) and r[0] == "ERR"))
    # 3) q → None(멈춤)
    checks.append(("q → 멈춤(None)", ses._parse_guess(seat, "q") is None))
    checks.append(("그만 → 멈춤", ses._parse_guess(seat, "그만") is None))
    # 4) 정상 입력 → 튜플
    own = game.players[seat].own_value_specs()
    cand = None
    for spec in ("0b", "0w", "1b", "1w", "2b", "2w"):
        if spec not in own:
            cand = spec
            break
    r = ses._parse_guess(seat, f"3 1 {cand}")
    checks.append((f"정상 입력({cand}) → 튜플", isinstance(r, tuple)
                   and len(r) == 3))

    # 5) _human_guess: 빈 입력 10회 후 상한 동작
    class AskScript(S.Output):
        def __init__(self, answers):
            self.answers = list(answers)
            self.i = 0
            self.msgs = []
        def show(self, t):
            self.msgs.append(t)
        def show_me(self, seat, t):
            self.msgs.append(t)
        def ask(self, seat, prompt, mode=None, data=None):
            a = self.answers[self.i] if self.i < len(self.answers) else ""
            self.i += 1
            return a
        def wait(self, seat, t):
            pass
        def finish(self, t):
            pass
        def is_connected(self, seat):
            return True

    ses2 = S.Session(AskScript([""] * 12), 3, human_seats={0},
                     rng=__import__("random").Random(0))
    _deal(ses2)
    g = ses2._human_guess(0)
    checks.append(("빈 입력 반복 → 상한 후 None(멈춤)", g is None))
    errs = [m for m in ses2.io.msgs if "빈" in m or "3개 항목" in m]
    checks.append((f"재질문 {len(errs)}회 발생", len(errs) >= 3))

    # 6) 3회 오답 후 4번째 정상 → 통과 (3번까지 실수 허용)
    own2 = ses2.game.players[0].own_value_specs()
    cand2 = next(s for s in ("0b", "0w", "1b", "1w", "2b", "2w")
                 if s not in own2)
    ses3 = S.Session(AskScript(["zzz", "yyy", "xxx", f"3 1 {cand2}"]),
                     3, human_seats={0}, rng=__import__("random").Random(0))
    _deal(ses3)
    g3 = ses3._human_guess(0)
    checks.append(("3회 실수 후 정상 통과", isinstance(g3, tuple)
                   and len(g3) == 3))

    print("=" * 50)
    allok = True
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print("=" * 50)
    print("ALL PASS" if allok else "SOME FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
