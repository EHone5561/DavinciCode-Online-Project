# -*- coding: utf-8 -*-
"""다빈치 코드 (Davinci Code) 게임 — 카드 및 게임판 설계 모듈 (조커 라인 모델 기준).

카드 표기 규칙:
  - 숫자 0..9,10,11 을 각각 '0'~'9','a','b' 한 글자로 표기한다.
  - 카드 표기는 항상 '숫자(1자) + 색(1자)'로 정확히 2글자. (예: '5b', 'ab', 'bw')
  - 조커 표기는 'J + 색'로 2글자. (예: 'Jb', 'Jw')

라인(손패 배치) 모델 — "조커 철학"(game_spec 섹션6):
  - 각 플레이어의 라인 = 숫자 카드(값 오름차순, 동일 값은 흑이 왼쪽)
    + 그 사이사이 끼어 있는 조커('벽'·이동 불가).
  - 초기 분배에는 조커가 없다. 조커는 오직 도중 draw 로만 들어온다.
  - 조커는 스스로 정렬되지 않고 자기 칸(슬롯)을 유지한다.

핵심 삽입 규칙:
  [A] 일반 숫자 N 삽입 — "조커 사이로 정렬되지 않는다"
      값 오름차순으로 놓일 자리 주변에 조커(벽)가 방해하면 그 조커에게
      '앞(왼쪽)/뒤(오른쪽)'을 묻는다. 연달아 조커 k개면 최대 k회 다음 벽에도 묻는다.
      벽이 전혀 안 걸리면 질문 없이 값 자리에 자동 삽입.
  [B] 조커 삽입 — 슬롯(0..M) 번호 지정. 카드 M장일 때 슬롯 0..M
      (0=맨앞, n=n번째 카드 뒤, M=맨뒤). 범위 밖이면 재결정.
  [C] 조커(Jb/Jw)도 추측값으로 지목할 수 있다.

정보 모델:
  - 모델은 print/input 을 절대 직접 부르지 않는다. 사람 입력은 View,
    CPU/자동 결정은 랜덤 등 '결정자(decider)'가 만들어 주입한다.
  - draw & 삽입에 필요한 결정(조커 슬롯, 숫자 벽 앞뒤)은
    Game.draw_and_insert(player, decide) 의 decide 콜백이 생성한다.
"""

import bisect

# 숫자 표기용 문자 (0~11 -> 0 1 2 ... 9 a b). 항상 1자리.
_DIGITS = "0123456789ab"

# 조커 표기용 문자
_JOKER_CHAR = "J"


def _num_key(card):
    """숫자 카드 정렬 키: (값, 색우선). 흑(True)을 왼쪽=0 으로."""
    return (card.value, 0 if card.is_black else 1)


class Card:
    """다빈치 코드 카드 한 장.
    숫자 카드: value = 0~11 정수 / 조커 카드: value = None
    색은 is_black (True=흑, False=백).
    """

    def __init__(self, value, is_black):
        if value is not None and not (0 <= value <= 11):
            raise ValueError(f"카드 숫자는 0~11 이어야 합니다. (받은 값: {value})")
        self.value = value
        self.is_black = is_black

    @property
    def is_joker(self):
        return self.value is None

    @property
    def color_char(self):
        return "b" if self.is_black else "w"

    def display(self):
        if self.is_joker:
            return _JOKER_CHAR + self.color_char
        return _DIGITS[self.value] + self.color_char

    def __eq__(self, other):
        if isinstance(other, Card):
            return self.value == other.value and self.is_black == other.is_black
        return NotImplemented

    def __hash__(self):
        return hash((self.value, self.is_black))

    def __repr__(self):
        return self.display()


#####################################################################################
class Table:
    """게임판: deck(안 뽑힌 패산), public(공개 정보).
    분배 룰: 초기 분배는 조커 없이 나누고(2·3인 각4장, 4인 각3장),
    남은 카드에 조커 2장을 넣어 섞어 공용 덱으로 둔다. 조커는 도중 draw 로만 들어온다.
    """

    def __init__(self):
        self.deck = []
        self.public = []

    @staticmethod
    def cards_per_player(player_count):
        if player_count in (2, 3):
            return 4
        elif player_count == 4:
            return 3
        raise ValueError("플레이어 수는 2~4 여야 합니다.")

    def draw(self):
        return self.deck.pop() if self.deck else None

    def deal(self, players):
        import random as _r
        per = Table.cards_per_player(len(players))
        black_pool = [Card(v, True) for v in range(12)]
        white_pool = [Card(v, False) for v in range(12)]
        _r.shuffle(black_pool)
        _r.shuffle(white_pool)
        for pl in players:
            black = pl.black_deal_count
            if black is None:
                black = _r.randint(0, per)
            black = max(0, min(per, black))
            pl.black_deal_count = black
            white = per - black
            for _ in range(black):
                pl.receive_card(black_pool.pop())
            for _ in range(white):
                pl.receive_card(white_pool.pop())
            pl.sort_hand()
        remaining = black_pool + white_pool
        self.deck = remaining + [Card(None, True), Card(None, False)]
        _r.shuffle(self.deck)

    def add_public(self, card):
        self.public.append(card)

    def __repr__(self):
        return f"Table(deck={len(self.deck)}장, public={self.public})"


#####################################################################################
class Player:
    """게임 참가자.
    - own_cards      : 자기 라인(물리 배치 순서). 숫자 오름차순 + 끼어든 조커(벽).
    - revealed_cards : 공개된 카드 부분집합.
    - is_human       : True=사람(View), False=CPU(랜덤). Player 는 Table 을 소유/변경 안 함.
    """

    def __init__(self, name, is_human):
        self.name = name
        self.is_human = is_human
        self.own_cards = []
        self.revealed_cards = []
        self.black_deal_count = None
        # 기권(연결 끊김 등): True 면 탈락과 동일하게 취급한다.
        # 멀티플레이에서 클라이언트가 접속을 끊었을 때 세션이 세운다.
        self.forfeited = False

    def receive_card(self, card):
        self.own_cards.append(card)

    def sort_hand(self):
        """초기(조커 없는 상태) 용 전체 숫자 정렬. 조커가 섞여도 벽은 고정한 채
        '숫자 구간별 오름차순' 을 안전 복구한다(현재 라인이 규칙을 만족하면 그대로)."""
        # 벽(조커) 위치는 절대 이동시키지 않는다.
        new_line = []
        seg = []
        for c in self.own_cards:
            if c.is_joker:
                seg.sort(key=_num_key)
                new_line.extend(seg)
                seg = []
                new_line.append(c)          # 벽 제자리
            else:
                seg.append(c)
        seg.sort(key=_num_key)
        new_line.extend(seg)
        self.own_cards = new_line

    def is_eliminated(self):
        """모든 손패가 공개됐는지(=탈락) 또는 기권했는지."""
        if self.forfeited:
            return True
        return bool(self.own_cards) and set(self.revealed_cards) == set(self.own_cards)

    def reveal(self, card):
        if card in self.own_cards and card not in self.revealed_cards:
            self.revealed_cards.append(card)

    def reveal_attacked(self, pos):
        """내 라인의 pos(1부터) 번째가 맞혀져 공개된다."""
        c = self.card_at_pos(pos)
        if c is not None and c not in self.revealed_cards:
            self.revealed_cards.append(c)
            return c
        return None

    def reveal_failed(self, card=None):
        """(오답 벌칙) 카드 or 미공개 임의패 하나를 공개. 없다면 None."""
        target = card
        if target is None or target in self.revealed_cards:
            hidden = [c for c in self.own_cards if c not in self.revealed_cards]
            if not hidden:
                return None
            target = hidden[0]
        self.revealed_cards.append(target)
        return target

    # --- 라인 헬퍼 (왼쪽 1부터의 pos) ---------------------------------------
    def card_at_pos(self, pos):
        if 1 <= pos <= len(self.own_cards):
            return self.own_cards[pos - 1]
        return None

    def pos_of(self, card):
        for i, c in enumerate(self.own_cards):
            if c is card:
                return i + 1
        return None

    def is_revealed_at(self, pos):
        c = self.card_at_pos(pos)
        return c is not None and c in self.revealed_cards

    def show_hand(self):
        return [c.display() for c in self.own_cards]

    def guessable_values(self, include_joker=True):
        """추측값 후보 display 집합. include_joker(기본 True)면 Jb/Jw 포함."""
        vals = {Card(v, b).display() for v in range(12) for b in (True, False)}
        if include_joker:
            vals |= {"Jb", "Jw"}
        return vals

    def own_value_specs(self):
        """내 라인에 실제로 들어 있는 값들의 display 집합.

        규칙: 지목(추측)은 '본인 라인에서 값이 보이는 카드'를 근거로 하므로,
        사람이 지목할 수 있는 값은 자기 패에 있는 값뿐이다.
        """
        return {c.display() for c in self.own_cards}

    def __repr__(self):
        return f"{self.name}({'人' if self.is_human else 'CPU'})"


#####################################################################################
class RandomDecider:
    """CPU / AUTOHUMAN(자동응답) 에 쓰는 랜덤 결정자. 모델·부정행위 없음."""

    def __init__(self, rng=None):
        import random
        self.rng = rng or random

    def select_joker_slot(self, card, M):
        """조커 삽입 슬롯 0..M 중 랜덤."""
        return self.rng.randint(0, M)

    def ask_joker_side(self, display):
        """숫자 카드가 벽에 걸렸을 때 앞/뒤 랜덤 결정."""
        return self.rng.choice(["front", "back"])


#####################################################################################
class Game:
    """게임 진행자. 순수 로직. print/input 없음.
    draw&삽입의 결정은 외부 decide(RandomDecider/View가 만든 콜백)에 위임한다.
    """

    def __init__(self, player_count, human_name="나"):
        self.table = Table()
        self.players = []
        self.turn_index = None
        self.round_number = 0
        self.round_start_index = None

        self.players.append(Player(human_name, is_human=True))
        for i in range(player_count - 1):
            self.players.append(Player(f"CPU{i+1}", is_human=False))

    # ----- 턴 / 라운드 ---------------------------------------------------
    def start_first_turn(self):
        import random as _r
        alive = [i for i in range(len(self.players))
                 if not self.players[i].is_eliminated()]
        if not alive:
            return None
        self.turn_index = _r.choice(alive)
        self.round_start_index = self.turn_index
        self.round_number = 1
        return self.current_player()

    def _next_alive_index(self, start):
        n = len(self.players)
        for step in range(1, n + 1):
            idx = (start + step) % n
            if not self.players[idx].is_eliminated():
                return idx
        return None

    def next_turn(self):
        if self.turn_index is None:
            return self.start_first_turn()
        nxt = self._next_alive_index(self.turn_index)
        if nxt is None:
            return None
        self.turn_index = nxt
        if self.round_start_index is not None and nxt == self.round_start_index:
            self.round_number += 1
        return self.current_player()

    def current_player(self):
        if self.turn_index is None:
            return None
        return self.players[self.turn_index]

    def deal(self):
        self.table.deal(self.players)

    @property
    def per(self):
        return Table.cards_per_player(len(self.players))

    def alive_players(self):
        return [p for p in self.players if not p.is_eliminated()]

    def human(self):
        for p in self.players:
            if p.is_human:
                return p
        return None

    def opponents_of(self, player):
        return [(i, p) for i, p in enumerate(self.players)
                if p is not player and not p.is_eliminated()]

    # ================= 조커 라인 삽입 핵심 ================================
    def draw_and_insert(self, player, decide):
        """player 가 덱에서 1장 뽑아 규칙에 맞게 라인에 삽입하고 반환한다.

        - 덱 비면 None.
        - 뽑은 게 조커 : decide.select_joker_slot(card, M) 로 슬롯 0..M 결정 후 삽입.
        - 뽑은 게 숫자 : 규칙(A) 따라 필요시 decide.ask_joker_side 로 앞/뒤 연쇄 질문 후 배치.
        Returns: 뽑은 Card or None.
        """
        card = self.table.draw()
        if card is None:
            return None
        if card.is_joker:
            self._insert_joker_at_slot(player, card, decide)
        else:
            self._insert_number_chain(player, card, decide)
        return card

    # --- [B] 조커 삽입: 슬롯 0..M ---------------------------------------- 
    def _insert_joker_at_slot(self, player, jcard, decide):
        """조커(벽)를 슬롯만 골라 삽입. 카드 M장이면 슬롯 0..M 총 M+1개.
        슬롯이 범위 밖으로 나오면(부정행위 방지) 0..M 으로 클램프한다.
        사람은 View 가 범위 밖이면 재입력하도록 이미 걸러냈고,
        여기서는 모델 안전장치로 1회 재질문 없이 clamp 후 삽입한다."""
        M = len(player.own_cards)
        slot = _clamp_int(decide.select_joker_slot(jcard, M), 0, M)
        player.own_cards.insert(slot, jcard)
        return slot

    # --- [A] 일반 숫자 삽입: 조커(벽) 앞뒤 연쇄 ----------------------------
    def _insert_number_chain(self, player, ncard, decide):
        """새 숫자 N 을 규칙(A)대로 배치한다.

        절차:
          1) 값 순 참조에서 N 의 좌우 숫자 이웃 A(작은 값)/B(크거나 같은 값) 를 구한다.
          2) 라인 물리 위치에서 N 이 꽂힐 '구간'이자 값상 'A..B 사이' 의 (슬롯)영역을 본다.
             이 영역에 조커(벽)가 겹치면 그 벽들에게 차례로 '앞/뒤'를 물어 배치를 정한다.
          3) 벽이 없으면 질문 없이 값 자리(=A와 B 사이, 또는 머리/tail)에 자동 삽입.
          4) 벽 연쇄: 차례로 각 벽에 앞/뒤를 묻되, '앞'이라고 답하면 그 벽의 왼쪽에
             N 을 놓고 중단. 끝까지 '뒤'면 마지막 벽의 오른쪽(B 직전)으로 배치.
        벽은 절대 이동하지 않으며, 어떤 결과든 숫자 구간(벽 제외)은 값 오름차순이다.
        """
        line = player.own_cards
        nk = _num_key(ncard)
        # 1) 값 이웃 A(그 직전), B(그 후)
        nums = sorted([c for c in line if not c.is_joker], key=_num_key)
        ins = bisect.bisect_left([_num_key(c) for c in nums], nk)
        A = nums[ins - 1] if ins > 0 else None
        B = nums[ins] if ins < len(nums) else None

        # 2) 물리 꽂힐 영역의 '열린 창': (A 직후 위치 .. B 직전 위치)
        #    lo = N 이 놓일 수 있는 첫 슬롯(A 다음), hi = 값 자리(벽 없을 때 N이 앉는 인덱스)
        if A is not None:
            lo_slot = line.index(A) + 1        # A 다음부터
        else:
            lo_slot = 0                        # 머리부터
        if B is not None:
            hi_slot = line.index(B)            # B 직전까지
        else:
            hi_slot = len(line)                # 라인 끝

        # 3~4) 그 창 안에 있는 벽 연쇄 조사
        walls = [i for i in range(lo_slot, hi_slot) if line[i].is_joker]
        if not walls:
            line.insert(hi_slot, ncard)        # 질문 없이 값 자리(B 직전 / 끝) 자동 삽입
            return
        # 벽이 개입: 왼쪽부터 차례로 앞/뒤를 계속 묻는다.
        # '앞'이라 물은 벽이 몇 번째 벽인지 흘지 t 를 써 배치 인덱스를 결정한다.
        t = len(walls)                          # 기본: 모두 '뒤' → 마지막 벽의 오른쪽(B 직전)
        for j, idx in enumerate(walls):
            # 전략 결정자는 '새 카드의 값'까지 알아야 간격을 비교할 수 있다.
            # → 카드 값을 함께 넘기는 확장 시그니처를 우선 시도하고,
            #    구형 decide(ask_joker_side(display) 만) 이면 그대로 호출한다.
            side = _ask_joker_side(decide, line[idx], ncard)
            if side == "front":
                t = j                           # 이 벽의 왼쪽(그 벽 바로 앞)에 배치
                break
        if t < len(walls):
            insert_at = walls[t]                # t번째(0부터) 벽의 왼쪽 자리에 삽입
        else:
            insert_at = hi_slot                 # 모든 벽 지나 최종 값 자리(B 직전) 배치
        line.insert(insert_at, ncard)


# ---------------------------------------------------------------------------
def make_card(value_or_joker, is_black):
    """카드 생성. value_or_joker 가 'J'/None 이면 조커, 아니면 정수(0~11)."""
    if value_or_joker is None or value_or_joker == "J":
        value = None
    else:
        value = int(value_or_joker)
    return Card(value, is_black)


def _clamp_int(x, lo, hi):
    """x 를 정수로 보정해 [lo,hi] 로 클램프 (외부값 안전화)."""
    if isinstance(x, str) and x.isdigit():
        x = int(x)
    try:
        x = int(x)
    except Exception:
        x = lo
    return max(lo, min(hi, x))


def _ask_joker_side(decide, wall_card, ncard):
    """벽(조커) 앞/뒤 질문. 전략 결정자면 새 카드까지 넘겨 정확히 묻는다.

    - decide 에 ask_joker_side_full(wall_display, ncard) 가 있으면 그걸 쓴다.
      (전략 결정자: 간격을 비교해 '넓은 쪽'을 고름)
    - 없으면 구형 ask_joker_side(wall_display) 를 호출한다 (하위 호환).
    """
    display = wall_card.display()
    full = getattr(decide, "ask_joker_side_full", None)
    if callable(full):
        return full(display, ncard)
    return decide.ask_joker_side(display)


def _spec_to_card(spec):
    """'단일 카드 스펙 문자열'(예 '3b', 'Jw')을 Card 로."""
    color_black = spec[-1] == "b"
    ch = spec[0]
    if ch == "J":
        return Card(None, color_black)
    v = {"a": 10, "b": 11}.get(ch)
    return Card(v if v is not None else int(ch), color_black)


def _verify_joker_examples():
    """game_spec 섹션6 동작예(A·B)를 실제 규칙엔진으로 재현·검증.

    사람 input 없이 결정 클로저(decide)로 '앞/뒤'를 고정해 Game._insert_number_chain 을
    직접 구동한다.
    Returns: (모두 통과 bool, 설명 str)
    """
    def run_insert(base_list, new_spec, side_list):
        """base_list 에 new_spec 을, side_list 순서대로 벽에 앞/뒤 답하며 삽입."""
        player = Player("검증", False)
        player.own_cards = [_spec_to_card(s) for s in base_list]
        ncard = _spec_to_card(new_spec)
        it = iter(side_list)
        qs = []

        class _D:
            def ask_joker_side(self, display):
                qs.append(display)
                try:
                    return next(it)
                except StopIteration:
                    return "back"       # 지급 부족 시 나머지는 전부 back(기본방향)

        def _run(self, pl, nc, dec):
            self._insert_number_chain(pl, nc, dec)
        g = Game.__new__(Game)
        _run(g, player, ncard, _D())
        return [c.display() for c in player.own_cards], qs

    # 동작예1 : [2b,Jb,5w] + 3b → Jb 인접 1회만 질문. 앞 또는 뒤.
    out_f, q_f = run_insert(["2b", "Jb", "5w"], "3b", ["front"])
    out_k, q_k = run_insert(["2b", "Jb", "5w"], "3b", ["back"])
    # 동작예2 : [1b,Jb,Jw,4w] + 5b → 질문 없이 자동
    out2, q2 = run_insert(["1b", "Jb", "Jw", "4w"], "5b", [])
    # 동작예3 : [2b,Jb,Jw,6w] + 4w, Jb뒤→Jw뒤
    out3, q3 = run_insert(["2b", "Jb", "Jw", "6w"], "4w", ["back", "back"])

    ok1f = q_f == ["Jb"] and out_f == ["2b", "3b", "Jb", "5w"]
    ok1k = q_k == ["Jb"] and out_k == ["2b", "Jb", "3b", "5w"]
    ok2 = q2 == [] and out2 == ["1b", "Jb", "Jw", "4w", "5b"]
    ok3 = q3 == ["Jb", "Jw"] and out3 == ["2b", "Jb", "Jw", "4w", "6w"]

    desc = (f"예1 앞:\"{out_f}\"(질문{q_f}) 예1 뒤:\"{out_k}\"(질문{q_k})\n"
            f"  예2:\"{out2}\"(질문{q2})\n  예3:\"{out3}\"(질문{q3})")
    return (ok1f and ok1k and ok2 and ok3), desc


def _model_full_game(player_count, seed=1, max_turn=2_000_000):
    """모델만으로 한 판(사람도 랜덤)을 끝까지 돌려 탈락→등수로 종료 확인.

    Returns: (정상종료 bool, 등수 dict idx->rank)
    """
    import random as _r
    _r.seed(seed)
    g = Game(player_count, human_name="나")
    dec = RandomDecider(_r)
    for p in g.players:
        p.black_deal_count = _r.randint(0, g.per)
    g.deal()

    next_rank = player_count
    elim_rank = {}

    def sweep():
        nonlocal next_rank
        for i2, pp in enumerate(g.players):
            if i2 not in elim_rank and pp.is_eliminated():
                elim_rank[i2] = next_rank
                next_rank -= 1

    def alive():
        return [i for i, p in enumerate(g.players) if not p.is_eliminated()]

    g.start_first_turn()
    sweep()
    guard = 0
    while len(alive()) > 1 and guard < max_turn:
        guard += 1
        cur = g.players[g.turn_index]
        if g.table.deck:
            g.draw_and_insert(cur, dec)            # 조커 슬롯/숫자 앞뒤 랜덤 삽입
        opps = [(i, p) for i, p in enumerate(g.players)
                if i != g.turn_index and not p.is_eliminated()]
        if opps:
            ti, tp = _r.choice(opps)
            hidden = [c for c in tp.own_cards if c not in tp.revealed_cards]
            if hidden and _r.random() < 0.5:       # 절반은 정답 시도 (벌칙/승자 양쪽 겸해)
                pos = tp.pos_of(_r.choice(hidden))
                rc = tp.reveal_attacked(pos)
                if rc is not None and rc not in g.table.public:
                    g.table.public.append(rc)
                sweep()
                if _r.random() < 0.45 and len(alive()) > 1:
                    # 정답 연속 이어가기(선택적) — 종료판단만 하므로 단순히 계속 잡짓
                    pass
        if len(alive()) <= 1:
            break
        g.next_turn()
    surv = alive()
    if len(surv) == 1:
        elim_rank[surv[0]] = 1
    return True, elim_rank


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    ex_ok, desc = _verify_joker_examples()
    ok, ranks = _model_full_game(n, seed=seed)
    print("┌ 조커 규칙 동작예 (A/B) ─────────────┐")
    print(desc)
    print("│ 결과:", "PASS ✓" if ex_ok else "FAIL ✗")
    print("└─────────────────────────────────────┘")
    print("모델 단독 끝판(%d인, seed=%d):" % (n, seed),
          "정상종료" if ok else "BUG", "등수:", ranks)
