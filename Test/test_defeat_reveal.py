# -*- coding: utf-8 -*-
"""패배자 패 공개 검증.

EHone 요청(테스터 친구 조언):
  "죽은 사람의 패를 그대로 공개한 채 두자. 죽었을 때 패를 다 지우지 말고,
   패배라는 인터페이스가 뜨게 해달라."

배경: 죽은 사람의 패가 안 보이면 남은 사람이 '무엇을 들고 있었는지'를
      추리할 수 없어 추리에 차질이 생긴다.

검증:
  1) 단위(_board_text): 생존자 시점에서 패배자 손패가 전부 값으로 보이고
     '(패배' 표시가 나온다. 비밀 카드가 남아 있으면 안 된다.
  2) 단위(_state_dict): 탈락자의 cards[].value 가 전부 실려 있고
     is_eliminated=True 로 내려간다.
  3) 실전: 사람이 탈락한 뒤 다른 생존자 좌석의 WAIT/STATE 에
     그 패배자 카드가 공개 상태로 계속 포함되는지 확인.

실행: python -E -X utf8 test_defeat_reveal.py
"""
import random

from session import Session, SilentOutput


class LogIo(SilentOutput):
    def __init__(self):
        super().__init__()
        self.waits = []
        self.states = []

    def wait(self, seat, text):
        self.log.append((f"WAIT#{seat}", text))
        self.waits.append((seat, text))

    def update_state(self, seat, st):
        self.log.append((f"STATE#{seat}", st))
        self.states.append((seat, st))

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "추측" in prompt:
            tgt = 2 if seat == 0 else 1
            return f"{tgt + 1} 1 0w"
        if "검은 카드" in prompt:
            return "1"
        if "공개할 자리" in prompt:
            return "1"
        if "슬롯" in prompt:
            return "0"
        return "0"


def _kill(p, game):
    """p 를 강제 탈락시킨다 (패 전부 공개 + 공개 더미 반영)."""
    for c in p.own_cards:
        p.reveal(c)
        if c not in game.table.public:
            game.table.public.append(c)
    assert p.is_eliminated(), "탈락 처리 실패"


def unit_board_text():
    """생존자 시점 _board_text 에 패배자 손패가 값으로 보이는지."""
    io = SilentOutput()
    s = Session(io, 4, human_seats={0, 1}, rng=random.Random(3))
    game = s.game
    for p in game.players:
        p.black_deal_count = 0 if p.is_human else 1
    game.deal()
    for p in game.players:
        p.sort_hand()

    dead = game.players[0]
    _kill(dead, game)

    # 생존자 좌석1 시점 (자기 턴 화면)
    txt = s._board_text(1, None, False)

    print("=== 단위: 생존자 시점 _board_text (패배자 포함) ===")
    for line in txt.splitlines():
        print("   " + line)
    print()

    checks = []
    checks.append(("패배자 좌석이 목록에 남음",
                   f"[#1] {dead.name}" in txt))
    checks.append(("'(패배' 표시가 있음", "(패배" in txt))
    checks.append(("'손패 전부 공개' 문구", "손패 전부 공개" in txt))

    # 패배자 줄에서 값(■/□)이 하나도 없어야 한다 = 전부 공개
    dead_line = None
    lines = txt.splitlines()
    for i, ln in enumerate(lines):
        if f"[#1] {dead.name}" in ln:
            dead_line = lines[i + 1] if i + 1 < len(lines) else ""
            break
    checks.append(("패배자 손패에 가림(■/□) 없음",
                   dead_line is not None and "■" not in dead_line
                   and "□" not in dead_line))
    return checks, dead, s


def unit_state_dict():
    """_state_dict 에서 탈락자 cards[].value 가 전부 실리는지."""
    io = SilentOutput()
    s = Session(io, 4, human_seats={0, 1}, rng=random.Random(5))
    game = s.game
    for p in game.players:
        p.black_deal_count = 0 if p.is_human else 1
    game.deal()
    for p in game.players:
        p.sort_hand()

    dead = game.players[0]
    _kill(dead, game)

    st = s._state_dict(1)
    entry = st["players"][0]
    print("=== 단위: _state_dict 좌석0(패배자) ===")
    print(f"   is_eliminated={entry['is_eliminated']} "
          f"cards={[c['value'] for c in entry['cards']]}")
    print()

    checks = []
    checks.append(("is_eliminated=True", entry["is_eliminated"] is True))
    checks.append(("모든 카드에 value 실림",
                   all(c["value"] is not None for c in entry["cards"])))
    checks.append(("비밀 카드 0",
                   entry["hidden_count"] == 0))
    return checks


def live_check():
    """실전: 사람 탈락 후 다른 좌석 STATE 에 패배자 카드가 공개로 계속 오는지.

    ★ 판이 끝나면 상태 발행이 멈추므로, '탈락자가 생겼는데 아직 생존자가
      남아 있는' 중간 시점의 STATE 를 봐야 한다. 그래서 게임 전체를 돌리는
      대신, 사람 1명만 강제 탈락시킨 뒤 _push_state_all 로 상태를 밀어본다.
    """
    io = LogIo()
    s = Session(io, 4, human_seats={0, 1, 2}, rng=random.Random(11))
    game = s.game
    for p in game.players:
        p.black_deal_count = 0 if p.is_human else 1
    game.deal()
    for p in game.players:
        p.sort_hand()

    dead = game.players[0]
    _kill(dead, game)

    # 생존자(좌석1) 시점으로 전원 상태 발행
    io.states.clear()
    s._push_state_all()

    dead_seats = {0}
    ok_found = False
    for seat, st in io.states:
        if seat in dead_seats:
            continue  # 탈락자 본인 상태는 제외
        for pe in st["players"]:
            if pe["seat"] in dead_seats and pe["is_eliminated"]:
                if pe["cards"] and all(c["value"] is not None for c in pe["cards"]):
                    ok_found = True

    print("=== 실전: 탈락 후 생존자 STATE 발행 ===")
    print(f"   상태 발행 좌석: {sorted(set(seat for seat, _ in io.states))}")
    print(f"   생존자 화면에 패배자 손패(전부 공개) 포함: {ok_found}")
    print()

    checks = []
    checks.append(("탈락 발생", dead.is_eliminated()))
    checks.append(("생존자 STATE 에 패배자 손패 공개됨", ok_found))
    return checks


def main():
    all_checks = []
    c1, dead, _ = unit_board_text()
    all_checks += c1
    all_checks += unit_state_dict()
    all_checks += live_check()

    print("=== 검증 결과 ===")
    allok = True
    for name, ok in all_checks:
        print(f"   [{'OK ' if ok else 'FAIL'}] {name}")
        allok = allok and ok
    print()
    print("PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
