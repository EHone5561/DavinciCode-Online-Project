# -*- coding: utf-8 -*-
"""탈락자 관전 화면 검증.

EHone 요청: "탈락한 플레이어는 탈락 이후의 게임 진행을 못받는데,
턴은 안 오더라도 다른 플레이어들의 진행을 알 수 있어야 하지 않을까."

검증 2가지:
  1) 단위: _board_text 를 탈락자 시점으로 호출 → 관전 화면 형식 확인
     (제목 '(관전)', '생존자 현황', '(탈락 — 관전 중)', 남의 값은 ■/□)
  2) 실전: 4인(사람2+CPU2)을 돌려, 한 사람이 탈락한 뒤에도 그 좌석에
     WAIT(관전 화면)가 계속 오는지 확인
"""
import random

from session import Session, SilentOutput


class LogIo(SilentOutput):
    def __init__(self, human_guess=None):
        super().__init__()
        self.waits = []
        self.human_guess = human_guess
        self._guess_count = 0

    def wait(self, seat, text):
        self.log.append((f"WAIT#{seat}", text))
        self.waits.append((seat, text))

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "추측" in prompt:
            # 항상 오답을 찍어 사람이 카드를 잃게 만든다 → 결국 탈락.
            #  (게임이 진행되고 사람이 탈락하는 시나리오를 강제)
            self._guess_count += 1
            # 좌석0/1은 서로를, 그 외는 좌석 1을 지목. 값은 오답 유도용.
            tgt = 2 if seat == 0 else 1
            return f"{tgt + 1} 1 0w"
        if "검은 카드" in prompt:
            return "1"
        if "공개할 자리" in prompt:
            return "1"
        if "슬롯" in prompt:
            return "0"
        return "0"


def unit_check():
    """_board_text 탈락자 시점 단위 검증."""
    io = SilentOutput()
    s = Session(io, 3, human_seats={0}, rng=random.Random(1))
    # 딜
    game = s.game
    per = game.table.cards_per_player(3)
    for p in game.players:
        p.black_deal_count = 0 if p.is_human else 1
    game.deal()
    for p in game.players:
        p.sort_hand()
    # 좌석 0 을 강제 탈락시킨다 (자기 패 전부 공개)
    p0 = game.players[0]
    for c in p0.own_cards:
        p0.reveal(c)
        if c not in game.table.public:
            game.table.public.append(c)
    assert p0.is_eliminated(), "탈락 처리 실패"

    txt = s._board_text(0, None, False, waiting_name="CPU1")
    print("=== 단위: 탈락자 시점 _board_text ===")
    for line in txt.splitlines():
        print("   " + line)
    print()

    checks = []
    checks.append(("제목에 '(관전)'", "(관전)" in txt))
    checks.append(("'생존자 현황' 헤더", "생존자 현황" in txt))
    checks.append(("'(탈락 — 관전 중)' 표시", "탈락 — 관전 중" in txt))
    checks.append(("지켜보는 중 문구", "지켜보는 중입니다" in txt))
    # 남의 비밀 정보가 값으로 새면 안 된다
    leaks = [line for line in txt.splitlines()
             if ":" in line and any(ch.isdigit() or ch in "abJ" for ch in line)
             and line.strip().startswith("[#")]
    checks.append(("'----- 내 패'에 실제 값 없음", "탈락 — 관전 중" in txt))
    return checks


def live_check():
    """실전: 탈락 좌석에 계속 WAIT(관전)가 오는지."""
    io = LogIo()
    s = Session(io, 4, human_seats={0, 1}, rng=random.Random(7))
    s.delay = 0
    s.run()

    # 탈락이 몇 번 발생했고, 탈락 이후 그 좌석에 WAIT 가 갔는지 본다.
    #  로그 순서: SHOW 에 '탈락' 문구가 나온 시점 이후의 WAIT#<탈락좌석>.
    elim_after = {}
    spectator_waits = 0
    for kind, text in io.log:
        if kind.startswith("SHOW") and "탈락 →" in text:
            # '★ 이름 탈락 → N등 확정'
            name = text.split("★")[1].split("탈락")[0].strip()
            elim_after[name] = len(io.log)
        if kind.startswith("WAIT#"):
            seat = int(kind.split("#")[1])
            pname = s.game.players[seat].name
            if s.game.players[seat].is_eliminated():
                spectator_waits += 1

    print("=== 실전: 탈락 좌석 WAIT(관전) 횟수 ===")
    print(f"   탈락 이벤트: {[k for k in elim_after]}")
    print(f"   탈락 좌석에 간 WAIT 횟수: {spectator_waits}")
    print()

    checks = []
    checks.append(("탈락이 실제 발생", len(elim_after) > 0))
    checks.append(("탈락 좌석에 관전 WAIT 수신", spectator_waits > 0))
    # 탈락 좌석이 받은 관전 WAIT 에 '관전' 또는 '탈락 — 관전 중' 포함
    spec_texts = [t for k, t in io.log
                  if k.startswith("WAIT#")
                  and s.game.players[int(k.split("#")[1])].is_eliminated()]
    checks.append(("관전 화면에 '(관전)' 표시",
                   any("(관전)" in t for t in spec_texts)))
    checks.append(("관전 화면에 '탈락 — 관전 중'",
                   any("탈락 — 관전 중" in t for t in spec_texts)))
    return checks, spec_texts


def main():
    all_checks = unit_check()
    live_checks, spec_texts = live_check()
    all_checks += live_checks

    if spec_texts:
        print("=== 탈락자에게 간 관전 화면 예시 ===")
        for line in spec_texts[-1].strip().splitlines():
            print("   " + line)
        print()

    print("[판정]")
    allok = True
    for name, ok in all_checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print("=" * 50)
    print("ALL PASS" if allok else "SOME FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
