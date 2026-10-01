# -*- coding: utf-8 -*-
"""트레이스로 정렬 위반 재현 — seed1 pc2에서 위반 순간 프린트."""
import random
import DavinciCode as md

random.seed(1)
g = md.Game(2)
dec = md.RandomDecider(random)
for p in g.players:
    p.black_deal_count = random.randint(0, g.per)
for p in g.players:
    print("pre-deal blackcount", p.name, p.black_deal_count)
g.deal(); g.start_first_turn()
for p in g.players:
    print("after deal:", p.name, p.show_hand())

def show_line(p):
    return [c.display() for c in p.own_cards]

for i in range(60):
    p = g.players[g.turn_index]
    before = show_line(p)
    if not g.table.deck:
        g.table.deck=[md.make_card("J",True),md.make_card("J",False)]
        random.shuffle(g.table.deck)
    drew = g.draw_and_insert(p, dec)
    after = show_line(p)
    keys = [c for c in p.own_cards]
    print(f"[{i}] {p.name} drew {drew.display()}  {before} -> {after}")
    # 불변식 검사
    seg=[]
    ok=True; rr=""
    for c in p.own_cards:
        if c.is_joker:
            kk=[md._num_key(x) for x in seg]
            if any(a>b for a,b in zip(kk,kk[1:])): ok=False;rr=f"seg{[x.display() for x in seg]}"
            seg=[]
        else:
            seg.append(c)
    kk=[md._num_key(x) for x in seg]
    if any(a>b for a,b in zip(kk,kk[1:])): ok=False;rr=f"last{[x.display() for x in seg]}"
    if not ok:
        print("  >>> 위반!", rr); break
    g.next_turn()
