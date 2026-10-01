# -*- coding: utf-8 -*-
"""STATE 비밀 정보 누출 검증 — 조커 노란테두리(최중요).

EHone 보고:
  "조커는 노란 테두리로 해놓은게 상대방에게도 전달되고 있어."
원인: session._state_dict 가 '볼 수 없는 카드'에도 is_joker=True 를 실어보냈다.

검증: 남의 비밀 패에 조커가 있을 때 그 좌석의 STATE 에서 is_joker 가 False 인지,
      반대로 내 패/공개된 카드에서는 True 로 오는지 확인한다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import session as S                     # noqa: E402
from DavinciCode import Card            # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + name +
          ("  (" + str(extra) + ")" if extra else ""))
    if not cond:
        fails.append(name)


# 사람 1 + CPU 1 (좌석 0 = 나, 좌석 1 = CPU)
io = S.SilentOutput()
sess = S.Session(io, 2, names=["태원", "CPU1"], human_seats=[0])
game = sess.game

# ---- 조커 카드로 강제 구성 ----------------------------------------------
# 실제 분배 전이므로 패를 직접 채운다(테스트 픽스처).
cpu = game.players[1]
mine = game.players[0]
joker_black = Card(None, True)     # 'Jb'
joker_white = Card(None, False)    # 'Jw'

cpu.own_cards.extend([Card(3, True), Card(5, False), Card(7, True)])
mine.own_cards.extend([Card(2, False), Card(6, True), Card(8, False)])

# CPU1 의 비밀 카드 하나를 조커로 바꾼다.
cpu.own_cards[0] = joker_black
mine.own_cards[0] = joker_white

# 공개 카드 하나 만들기: CPU1 의 두 번째 카드를 공개 상태로.
cpu.revealed_cards.append(cpu.own_cards[1])
cpu.own_cards[1] = Card(5, False)   # '5w' (공개됨, 조커 아님)

st = sess._state_dict(0)            # 내(좌석 0) 시점 STATE

def find(state, seat):
    return [p for p in state["players"] if p["seat"] == seat][0]

me_p = find(st, 0)
cpu_p = find(st, 1)

print("== 1) 남의 비밀 조커 = 노란테두리 금지 ==")
opp_card0 = cpu_p["cards"][0]
chk("남의 비밀 조커 value 는 None", opp_card0["value"] is None, opp_card0["value"])
chk("남의 비밀 조커 is_joker=False", opp_card0["is_joker"] is False,
    opp_card0["is_joker"])
chk("남의 비밀 조커 revealed=False", opp_card0["revealed"] is False, "")

print("== 2) 내 조커 = 노란테두리 유지 ==")
my_card0 = me_p["cards"][0]
chk("내 조커 is_joker=True", my_card0["is_joker"] is True, my_card0["is_joker"])
chk("내 조커 value 표시('Jw')", my_card0["value"] == "Jw", my_card0["value"])

print("== 3) 공개된 조커 = 보여야 함 ==")
# CPU1 의 카드 하나를 '공개된 조커'로 바꾼다.
cpu.own_cards[2] = joker_black
cpu.revealed_cards.append(cpu.own_cards[2])
st2 = sess._state_dict(0)
cpu_p2 = find(st2, 1)
chk("공개된 조커 is_joker=True", cpu_p2["cards"][2]["is_joker"] is True,
    cpu_p2["cards"][2]["is_joker"])
chk("공개된 조커 value 표시", cpu_p2["cards"][2]["value"] is not None,
    cpu_p2["cards"][2]["value"])

print("== 4) 색(is_black)은 비밀 카드에도 실린다 (규칙) ==")
chk("남의 비밀 조커 is_black 유지", opp_card0["is_black"] is True,
    opp_card0["is_black"])

# =========================================================================
print("== 5) 덱 소진 오답: 벌칙 버튼에 값(values)이 실린다 ==")
# ★ 앞 섹션에서 공개 처리한 카드가 Card.__eq__ 특성상 겹칠 수 있으므로
#   이 검증은 새 세션에서 깨끗하게 한다.
io2 = S.SilentOutput()
sess2 = S.Session(io2, 2, names=["태원", "CPU1"], human_seats=[0])
cpu2 = sess2.game.players[1]
cpu2.own_cards.extend([Card(3, True), Card(5, False), Card(None, True)])  # 3번째가 조커

seen = []


def fake_ask(seat, prompt, mode=None, data=None):
    seen.append({"seat": seat, "mode": mode, "data": data})
    return "1"          # 첫 비공개 자리 선택


sess2._human_ask = fake_ask
pos = sess2._ask_fail_reveal_pos(1)

chk("mode='fail_reveal' 로 질문", bool(seen) and seen[0]["mode"] == "fail_reveal",
    seen[0]["mode"] if seen else "없음")
chk("data.hidden 존재", bool(seen and seen[0]["data"].get("hidden")),
    seen[0]["data"].get("hidden") if seen else None)
chk("data.values 개수 = hidden 개수",
    bool(seen) and len(seen[0]["data"]["values"]) == len(seen[0]["data"]["hidden"]),
    seen[0]["data"].get("values") if seen else None)
chk("values 에 조커 값('Jb') 포함",
    bool(seen) and "Jb" in seen[0]["data"]["values"],
    seen[0]["data"].get("values") if seen else None)
chk("values 에 일반 값('3b') 포함",
    bool(seen) and "3b" in seen[0]["data"]["values"],
    seen[0]["data"].get("values") if seen else None)
chk("자리번호 반환", pos == 1, pos)

print("\n" + "=" * 50)
print("ALL PASS ✅" if not fails else "FAIL (%d개)" % len(fails))
sys.exit(0 if not fails else 1)
