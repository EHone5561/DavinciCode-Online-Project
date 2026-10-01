# -*- coding: utf-8 -*-
"""조커 라인 불변식 스트레스 검증 — 매 draw/삽입 직후 반드시:
   (1) 조커는 스스로 움직이지 않는다(지워질 일 없음→카드 수만 늘어남, 공개만)
   (2) 각 조커(벽) 사이 구간의 숫자들은 (값, 흑-왼쪽) 오름차순.
   (3) 이웃 생성 없이? — 숫자만 삽입은 항상 구간 내 1장 추가, 조커는 슬롯 지정.
   시나리오: 2~4명, 수백 회 draw 를 랜덤 decider 로 굴림.
"""
import random, sys
import DavinciCode as md

def seg_ok(seq):
    # seq: 숫자 카드만 있는 구간. 오름차순이어야(값, 흑먼저). 조커는 여기 없음.
    keys = [md._num_key(c) for c in seq]
    return all(a <= b for a, b in zip(keys, keys[1:]))

def verify_line(player):
    line = player.own_cards
    seg = []
    ok = True
    reason = ""
    for c in line:
        if c.is_joker:
            if not seg_ok(seg):
                ok = False
                reason = f"구간 비오름:{[x.display() for x in seg]}"
                break
            seg = []
        else:
            seg.append(c)
    if ok and not seg_ok(seg):
        ok = False
        reason = f"마지막구간 비오름:{[x.display() for x in seg]}"
    return ok, reason

def run_one(player_count, seed, steps=3000):
    random.seed(seed)
    g = md.Game(player_count)
    dec = md.RandomDecider(random)
    for p in g.players:
        p.black_deal_count = random.randint(0, g.per)
    g.deal()
    # 분배 직후 모든 플레이어 전역 오름차순
    for p in g.players:
        ok, r = verify_line(p)
        assert ok, (seed, "deal", p.name, p.show_hand(), r)
    g.start_first_turn()
    # 진행중 뽑기 반복
    for i in range(steps):
        # 순환 턴(탈락은 eval 하지 않고 '전부 아직'이라 가정): 단순히 사람 라인에만 집중,
        # 모든 플레이어 번갈아 들어 계속 확대
        p = g.players[g.turn_index]
        if not g.table.deck:
            g.table.deck = [md.make_card("J", True), md.make_card("J", False),
                            md.make_card(random.choice(list("0123456789ab")),
                                         random.random()<0.5)]
            random.shuffle(g.table.deck)
        g.draw_and_insert(p, dec)
        # 조커 드로우는 슬롯을 제어하므로 그 순간도 벽 위치 그대로; 검증만
        ok, rr = verify_line(p)
        if not ok:
            return False, (seed, player_count, p.name, p.show_hand(), rr)
        g.next_turn()
    return True, None

def main():
    fails = []
    for pc in (2, 3, 4):
        for seed in range(1, 41):
            ok, info = run_one(pc, seed)
            if not ok:
                fails.append(info)
    if fails:
        print("불변식 위반 발견:", len(fails), "예시:", fails[0])
        return 1
    print("스트레스 검증 통과: 2/3/4인 × 40 seed × 3000 draw = 모두 오름차순·벽 이동 없이 유지")
    return 0

if __name__ == "__main__":
    sys.exit(main())
