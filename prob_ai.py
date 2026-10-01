# -*- coding: utf-8 -*-
"""다빈치 코드 — 확률 추론 CPU AI (prob_ai).

설계 원칙
=========
- 부정행위 금지: 오직 '공개 정보(공개 카드·추측 이력)' + '공격자 자기 패'만 쓴다.
  상대의 비공개 카드 값/색/순서는 절대 읽지 않는다.
- 인터페이스 호환: run_game.random_guess_for(game, attacker_idx) 와 동일 형태의
  (tidx, pos, val) | None 을 반환한다.
- 순수 계산: print/input 없음. rng 는 선택 주입.

추론 모델
=========
상대 라인의 비밀 자리들은 정렬 규칙을 만족한다:
  - 숫자 카드는 값 오름차순(동값이면 흑이 왼쪽). 조커는 벽(고정).
  - 조커로 나뉜 각 구간에서 자리들의 값은 '비내림차순'이다.

[자리 → 값 확률] 중복조합 모델 (실측 분포와 정확히 일치함을 검증)
  구간에 값 후보가 V종 있고 자리가 n개(비밀 L/R)일 때,
      자리 i(왼쪽 L개, 오른쪽 R개)에 값 v 가 올 경우의 수
        = C(L + n_le - 1, L) × C(R + n_ge - 1, R)
          (n_le = v 이하 후보 종류 수, n_ge = v 이상 후보 종류 수)
  이 경우의 수를 구간 전체 합으로 정규화하면 자리별 값 확률이 된다.
  (itertools.combinations_with_replacement 실측과 1e-9 오차로 일치 검증)

[값 → 색 확률] 값이 정해진 뒤 흑/백은 남은 카드 풀 기준으로 나눈다.
  - 후보 값 v 에 흑/백이 각각 풀에 남아 있는지 보고 가중.
"""

import math

from DavinciCode import Card

# ---------------------------------------------------------------------------
# 표기 유틸 (모델 display 규칙과 동일)
# ---------------------------------------------------------------------------
_CHAR_TO_VAL = {c: i for i, c in enumerate("0123456789ab")}
_ALL_SPECS = [Card(v, b).display() for v in range(12) for b in (True, False)]
_ALL_SPECS += ["Jb", "Jw"]

NUM_VALUES = list(range(12))          # 값 종류 12개

# 조커(값 아님) 처리 (EHone 규칙):
#   "조커로 판단하는 건, 내가 찍거나 남이 지목해서 틀린 정보로
#    추리확률이 0%에 근접할 때."
#   → 그 자리에 올 숫자 후보가 남아 있으면 조커는 '거의 안 찍는다'.
#     숫자 후보가 전부 배제됐을 때만 조커를 후보로 올린다.
JOKER_LOW_PRIOR = 0.02      # 숫자 후보가 남아 있을 때 조커의 낮은 사전확률
JOKER_CONFIRM_P = 0.90      # 숫자 후보가 전무할 때 조커 확률(사실상 확정)

# ---- 연속 지목 기대값 판단 상수 -------------------------------------------
#   확률이 이 값 이상이면 '정답이 훤히 보이는' 것으로 보고 즉시 이어간다.
CONFIDENT_THRESHOLD = 0.75
#   위험 계수: 오답 시 어떤 카드가 공개되느냐에 따른 손실 비중
DECK_LEFT_RISK = 0.6      # 덱 남음 → '방금 뽑은 카드' 공개 (상대가 짐작했을 것 → 손실 작음)
DECK_EMPTY_RISK = 1.0     # 덱 소진 → 내 패 중 임의 1장 공개 (통제 불가 → 손실 큼)


def spec_value(spec):
    """표기 문자열 -> (value, is_black). 조커면 value=None.

    '3b' -> (3, True) / 'Jw' -> (None, False).
    ※ 게임 모델(DavinciCode.Card)에서는 조커가 value=None 이다.
      'Jb'/'Jw' 는 View 표기일 뿐이므로, 내부 계산은 항상 value 기준으로 다룬다.
    """
    is_black = spec[-1] == "b"
    ch = spec[0]
    if ch == "J":
        return None, is_black
    return _CHAR_TO_VAL[ch], is_black


def spec_display(value, is_black):
    """(value, is_black) -> View 표기 문자열. (표시 직전에만 변환)"""
    return Card(value, is_black).display()


def spec_is_joker(spec):
    """표기 문자열이 조커인지."""
    return spec[0] == "J"


def _multicomb(n, k):
    """n종류에서 k개 중복조합 C(n+k-1, k)."""
    if k < 0:
        return 0
    if k == 0:
        return 1
    if n <= 0:
        return 0
    return math.comb(n + k - 1, k)


# ---------------------------------------------------------------------------
# 남은 카드 풀 (정당한 정보만)
# ---------------------------------------------------------------------------
def hidden_card_pool(game, attacker_idx):
    """공격자가 정당하게 아는 '상대 미공개 카드' 후보 풀.

    전체 26장
      - 내 손패 (내가 아는 카드)
      - 공개 카드 (전원 아는 카드)
      - **다른 상대**가 지목으로 보유를 확정한 값
        (3인 이상: A가 값 X 를 지목했다면 X 는 A 패에 있고, 카드는 1장뿐이므로
         X 는 B 의 패에도 없다 → B 의 풀에서 제거)

    ★ 주의: '이 함수가 대상으로 삼는 상대' 자신이 보유 확정한 값은 빼지 않는다.
      (그 값은 그 상대에게 '있다'가 확정된 정보 → 오히려 자리 추론에 써야 한다)
      → 그래서 풀은 '지목 확정 값'을 제외하지 않고, 대신
        position_value_probabilities 가 claimed 값을 고정 확률로 반영한다.
    """
    pool = list(_ALL_SPECS)
    me = game.players[attacker_idx]
    for c in me.own_cards:
        try:
            pool.remove(c.display())
        except ValueError:
            pass
    for c in game.table.public:
        try:
            pool.remove(c.display())
        except ValueError:
            pass
    return pool


def opp_hidden_count(game, attacker_idx):
    n = 0
    for i, p in enumerate(game.players):
        if i == attacker_idx or p.is_eliminated():
            continue
        n += sum(1 for c in p.own_cards if c not in p.revealed_cards)
    return n


# ---------------------------------------------------------------------------
# 라인 구조 분석
# ---------------------------------------------------------------------------
def analyze_line(opponent):
    """상대 라인 → (segments, joker_slots, bounds).

    segments    : 조커로 분리된 숫자 구간의 자리 인덱스 리스트들
    joker_slots : 공개된 조커 자리
    bounds      : 자리별 (low, high) — 공개 숫자 기준 값 범위
    """
    n = len(opponent.own_cards)
    joker_slots = set()
    for i, c in enumerate(opponent.own_cards):
        if c in opponent.revealed_cards and c.is_joker:
            joker_slots.add(i)

    segments = []
    cur = []
    for i in range(n):
        if i in joker_slots:
            if cur:
                segments.append(cur)
            cur = []
        else:
            cur.append(i)
    if cur:
        segments.append(cur)

    bounds = [None] * n
    for seg in segments:
        known = []
        for i in seg:
            c = opponent.own_cards[i]
            if c in opponent.revealed_cards and not c.is_joker:
                known.append((spec_value(c.display())[0], i))
        known.sort()
        for i in seg:
            low = None
            high = None
            for v, idx in known:
                if idx < i:
                    low = v if low is None else max(low, v)
                elif idx > i:
                    high = v if high is None else min(high, v)
            bounds[i] = (low, high)

    return segments, joker_slots, bounds


# ---------------------------------------------------------------------------
# 핵심: 자리-값 확률 (중복조합 모델)
# ---------------------------------------------------------------------------
def _available_specs(pool, low=None, high=None, absent_specs=None, color=None):
    """풀에 남아 있는 숫자 '스펙(값, is_black)' 집합.

    - 경계(low/high)는 '값' 기준으로 필터.
    - absent_specs: (value, is_black) 튜플 집합 → 정확히 그 스펙만 배제.
      ★ 값 단위로 배제하면 같은 값의 반대 색까지 사라지므로 반드시 스펙 단위로.
    - color: 이 자리의 실제 색 (True=흑, False=백, None=제한 없음).
      ★ 카드 색은 항상 공개 정보(■/□) → 그 자리에는 그 색만 올 수 있다.
        (실측: 색 제약 없으면 후보가 2배 → 낭비)
    """
    absent_specs = absent_specs or set()
    out = set()
    for spec in pool:
        v, b = spec_value(spec)
        if v is None:
            continue
        if low is not None and v < low:
            continue
        if high is not None and v > high:
            continue
        if color is not None and b != color:
            continue                      # ★ 색 제약: 그 자리 색과 다르면 배제
        if (v, b) in absent_specs:
            continue
        out.add((v, b))
    return out


def position_spec_probabilities(opp, pool, absent=None):
    """(pos_1based, (value, is_black)) -> 확률 dict. value=None 이면 조커.

    ★ spec 단위로 확률을 계산한다 (값 단위 아님).
      카드 색은 항상 공개 정보(■/□)이므로, 각 자리에는 그 색의 스펙만 올 수 있다.
      값 단위로 합산하면 색 정보가 뭉개지므로 spec 단위로 유지한다.

    absent: 이 상대의 패에 '없음'이 확정된 값 spec 집합 (표기 문자열, 예 {'bw'}).
      ★ 상대가 val_spec 을 지목했다 = 그 값은 자기 패에 없다는 뜻이다.
      ★ 배제는 반드시 spec(값+색) 단위 (값 단위로 하면 반대 색까지 사라짐).
    """
    segments, joker_slots, bounds = analyze_line(opp)
    probs = {}

    # '상대 패에 없음'이 확정된 spec 집합 (값, is_black) 튜플
    absent_specs = set()
    if absent:
        for spec in absent:
            absent_specs.add(spec_value(spec))      # (value, is_black)

    for seg in segments:
        secret = [i for i in seg if opp.own_cards[i] not in opp.revealed_cards]
        if not secret:
            continue

        # 각 비밀 자리의 허용 스펙 집합: {(value, is_black)}
        #   ★ color=그 자리의 실제 색(공개 정보) → 반대 색은 후보에서 제외
        allowed_specs = {}
        for i in secret:
            low, high = bounds[i]
            color = opp.own_cards[i].is_black
            allowed_specs[i] = _available_specs(pool, low, high, absent_specs, color)

        # 중복조합 모델 (스펙 단위)
        #   왼쪽 L개는 전부 '값 ≤ v' 인 스펙에서, 오른쪽 R개는 '값 ≥ v' 에서 뽑는다.
        raw = {}
        for i in secret:
            L = sum(1 for j in secret if j < i)
            R = sum(1 for j in secret if j > i)
            for spec in allowed_specs[i]:
                v = spec[0]
                n_le = sum(1 for x in allowed_specs[i] if x[0] <= v)
                n_ge = sum(1 for x in allowed_specs[i] if x[0] >= v)
                ways = _multicomb(n_le, L) * _multicomb(n_ge, R)
                raw[(i, spec)] = raw.get((i, spec), 0) + ways

        tot = sum(raw.values())
        if tot <= 0:
            n_sec = max(1, sum(len(allowed_specs[j]) for j in secret))
            for i in secret:
                for spec in allowed_specs[i]:
                    probs[(i + 1, spec)] = probs.get((i + 1, spec), 0.0) + 1.0 / n_sec
        else:
            for (i, spec), ways in raw.items():
                probs[(i + 1, spec)] = ways / tot

    # ---------------------------------------------------------------------
    # 조커 처리 (EHone 규칙):
    #   "조커로 판단하는 건, 내가 찍거나 남이 지목해서 틀린 정보로
    #    추리확률이 0%에 근접할 때."
    #
    #   → 조커는 무정보 카드다. 그 자리에 올 '숫자'가 남아 있으면 숫자를 찍는다.
    #     숫자 후보가 전부 배제되어 남은 가능성이 조커뿐일 때만 조커를 올린다.
    #
    #   ★ 정규화 주의: 조커를 사후 추가하면 자리별 확률 합이 1을 넘는다.
    #     따라서 조커를 넣은 뒤 그 자리 숫자 확률을 함께 재정규화한다.
    # ---------------------------------------------------------------------
    jokers_in_pool = [s for s in pool if spec_is_joker(s)]
    joker_avail = {b: any(spec_value(s) == (None, b) for s in jokers_in_pool)
                   for b in (True, False)}

    if jokers_in_pool:
        secret_all = [i for i in range(len(opp.own_cards))
                      if opp.own_cards[i] not in opp.revealed_cards]
        # 자리별 숫자 확률 합
        num_sum = {}
        for (pos, spec), p in probs.items():
            if spec[0] is not None:
                num_sum[pos] = num_sum.get(pos, 0.0) + p

        # 1) 조커를 넣을 자리/확률 결정
        #    ★ 조커는 자리 간 배타적이다 (조커 1장은 한 자리에만).
        #      여러 자리에 '확정(1.0)'을 동시에 주면 논리 모순이므로,
        #      확정 후보가 여럿이면 그 자리들끼리 확률을 나눠 갖게 한다.
        joker_add = {}
        confirm_slots = []
        for i in secret_all:
            pos = i + 1
            color = opp.own_cards[i].is_black
            if not joker_avail.get(color):
                continue
            if (None, color) in absent_specs:
                continue
            low, high = bounds[i]
            num_specs = _available_specs(pool, low, high, absent_specs, color)
            if not num_specs:
                confirm_slots.append(pos)     # 숫자 가능성 0 → 조커 후보
            else:
                joker_add[pos] = JOKER_LOW_PRIOR

        # 확정 슬롯이 여럿이면 그 색 조커 장수만큼만 1.0 권한을 나눈다.
        n_confirm = len(confirm_slots)
        if n_confirm:
            # 그 색 조커가 풀에 몇 장인지
            for pos in confirm_slots:
                color = opp.own_cards[pos - 1].is_black
                n_jok = sum(1 for s in jokers_in_pool if spec_value(s) == (None, color))
                if n_jok <= 0:
                    continue
                # 확정 슬롯이 조커 장수보다 많으면 확률을 나눠 갖는다
                share = min(1.0, n_jok / n_confirm)
                joker_add[pos] = max(joker_add.get(pos, 0.0), share * JOKER_CONFIRM_P)

        # 2) 자리별로 (숫자 + 조커) 합이 1이 되도록 재정규화
        for pos, jp in joker_add.items():
            ns = num_sum.get(pos, 0.0)
            if ns <= 0.0:
                # 숫자 확률이 전무 → 이 자리 확률을 조커에 전부 준다.
                #   (jp 는 배타성을 반영한 값. 여럿이면 나눠 갖는다)
                probs[(pos, (None, opp.own_cards[pos - 1].is_black))] = 1.0 if jp >= 1.0 else jp
                continue
            total = ns + jp
            scale = 1.0 / total
            for (p2, spec2) in list(probs.keys()):
                if p2 == pos and spec2[0] is not None:
                    probs[(p2, spec2)] *= scale
            probs[(pos, (None, opp.own_cards[pos - 1].is_black))] = jp * scale

    return probs


def spec_to_display(spec):
    """(value, is_black) -> View 표기 문자열. (표시 직전 변환)"""
    v, b = spec
    return spec_display(v, b)


# ---------------------------------------------------------------------------
# AI 기억 (한 번 추론한 내용은 다시 추론하지 않는다)
# ---------------------------------------------------------------------------
#  모델(DavinciCode.py)을 건드리지 않기 위해, 기억은 game 객체에 붙여 둔다.
#
#  기억은 3층으로 나눈다 (정확도 향상의 핵심):
#    (1) 실패 조합 집합   : (tidx, pos, val) — 그 자리에 그 값은 아니다.
#    (2) 값별 실패 집합   : (tidx, val)      — 그 상대에게 그 값은 '없을 가능성'.
#                           ★ 같은 값을 자리만 바꿔 반복 시도하는 낭비를 막는다.
#    (3) 성공/공개 카드   : game.table.public / revealed_cards 에서 자동 반영.
#
#  (2)가 없으면 AI 는 '자리5에 ab는 아니다' 를 배우고 나서도 '자리6에 ab' 를
#  다시 시도한다. (2) 는 "이미 여러 자리에서 ab 가 아니었다" 를 누적해
#  '이 상대에게 ab 는 없다' 는 판단으로 이어 준다.
_MEM_ATTR = "_ai_prob_memory"          # (1) 실패 조합
_VALFAIL_ATTR = "_ai_value_fail"       # (2) 값별 실패 횟수


def _memory_for(game, attacker_idx):
    """(1) 공격자별 '이미 찍어 틀린 조합' 집합."""
    store = getattr(game, _MEM_ATTR, None)
    if store is None:
        store = {}
        setattr(game, _MEM_ATTR, store)
    if attacker_idx not in store:
        store[attacker_idx] = set()
    return store[attacker_idx]


def _valfail_for(game, attacker_idx):
    """(2) 공격자 -> {상대idx: {val_spec: set(실패한 자리)}}.

    ★ 실패한 '자리'의 집합으로 저장한다 — 같은 자리를 여러 번 찍은 실패는
      중복이므로 하나로 센다. (값 소진 판정의 정확도에 직접 영향)
    """
    store = getattr(game, _VALFAIL_ATTR, None)
    if store is None:
        store = {}
        setattr(game, _VALFAIL_ATTR, store)
    if attacker_idx not in store:
        store[attacker_idx] = {}
    return store[attacker_idx]


def remember_failure(game, attacker_idx, move, target_hidden=None):
    """오답 조합을 기억한다.

    move = (tidx, pos, val)  — 실패한 조합

    저장:
      (1) 실패 조합 (tidx, pos, val) → 그 자리에 그 값은 아님
      (2) 값별 실패 (tidx, val) → 실패한 자리 집합에 pos 추가
          → '서로 다른 자리 전부에서 실패 = 그 값은 없음' 판정에 쓰인다.
    """
    if move is None:
        return
    tidx, pos, val = tuple(move)
    _memory_for(game, attacker_idx).add((tidx, pos, val))
    vf = _valfail_for(game, attacker_idx)
    vf.setdefault(tidx, {})
    vf[tidx].setdefault(val, set()).add(pos)


def value_failure_penalty(game, attacker_idx, tidx, val):
    """값별 실패를 확률 감쇠 계수로 환산.

    논리:
      어떤 값이 그 상대의 '아직 비밀인 자리' 전부에서 실패했다면,
      그 값이 있을 자리는 남아 있지 않다 → 그 값은 '없다'고 본다.
      일부 자리에서만 실패했다면 → 아직 가능하지만 확률은 낮춘다.

    반환: 곱셈 계수 (1.0 = 페널티 없음, 0.0 = 확정 배제)
    """
    vf = getattr(game, _VALFAIL_ATTR, None)
    if not vf or attacker_idx not in vf:
        return 1.0
    tried = vf[attacker_idx].get(tidx, {}).get(val)
    if not tried:
        return 1.0
    if tidx >= len(game.players):
        return 1.0

    opp = game.players[tidx]
    # 아직 비밀인 자리들 (pos 는 1부터)
    hidden_pos = {i + 1 for i, c in enumerate(opp.own_cards)
                  if c not in opp.revealed_cards}
    if not hidden_pos:
        return 1.0

    tried_hidden = tried & hidden_pos       # 아직 비밀인데 시도해 본 자리
    if not tried_hidden:
        return 1.0

    # 비밀 자리 전부를 시도했는데 실패 → 그 값은 없다 (확정 배제)
    if tried_hidden >= hidden_pos:
        return 0.0
    # 일부만 시도 → 시도 비율만큼 지수 감쇠 (1자리 실패당 0.3배)
    return 0.3 ** len(tried_hidden)


def reset_memory(game):
    """기억 초기화 (새 판 시작 시)."""
    for attr in (_MEM_ATTR, _VALFAIL_ATTR, _CLAIM_ATTR):
        if hasattr(game, attr):
            delattr(game, attr)


# ---------------------------------------------------------------------------
# 상대의 '지목 이력' 학습  ★ 정보 활용의 핵심 (+ 수명 관리)
# ---------------------------------------------------------------------------
#  ★ 규칙 (EHone 확정):
#    지목은 **"내 패에는 이 값이 없으니, 네 패에 있을 것이다"** 라는 추리다.
#    예) "2 2 3b" 지목 = 지목자의 패에 3b 는 없고, 상대 2번 자리가 3b 라는 추리.
#
#    근거: 패는 유일하다. 지목자가 자기 패에 그 값을 들고 있으면
#          '남의 패에 그 값이 있다'고 지목할 의미가 없다.
#
#  ★ 수명 관리 (EHone 확정):
#    "지목자 패에 그 값이 없다"는 **지목한 그 시점의 사실**일 뿐이다.
#    지목자가 이후 카드를 뽑으면, 뽑은 카드가 그 값일 수 있다 → 지목은 무효.
#      예) t15 위반 사례: 지목자 패에 7b 가 있는데, 예전 지목 이력이 살아 있어
#          '7b 없음'으로 잘못 확정 → 추론 오염.
#
#    판정: 지목 시점의 **지목자 라인 길이**를 함께 저장하고,
#          나중에 라인 길이가 달라졌으면 그 지목을 무효로 본다.
#          (카드를 뽑으면 라인이 1장 늘어난다. 조커 삽입·공개는 길이를 안 바꾼다.)
#
#  저장: _ai_claims[attacker_idx] = {상대idx: {val_spec: 지목시점_라인길이}}
_CLAIM_ATTR = "_ai_claims"


def _claims_for(game, attacker_idx):
    """공격자 -> {상대idx: {값 spec: 지목 시점의 그 상대 라인 길이}}."""
    store = getattr(game, _CLAIM_ATTR, None)
    if store is None:
        store = {}
        setattr(game, _CLAIM_ATTR, store)
    if attacker_idx not in store:
        store[attacker_idx] = {}
    return store[attacker_idx]


def note_claim(game, attacker_idx, claimer_idx, val_spec):
    """상대(claimer_idx)가 val_spec 을 지목했다 = 그 상대의 패에 val_spec 은 없다.

    ★ 의미: 지목은 "내 패에 이 값이 없으니 네 패에 있을 것"이라는 추리다.
      (패는 유일하므로, 자기 패에 그 값이 있으면 그런 지목을 할 이유가 없다)
      → claimer 의 패 후보에서 val_spec 을 제거한다.

    ★ 수명: 지목 시점의 claimer 라인 길이를 함께 저장한다. 이후 claimer 가
      카드를 뽑아 라인이 길어지면 이 지목은 무효가 된다.
    """
    if val_spec is None or claimer_idx is None:
        return
    if claimer_idx == attacker_idx:
        return                      # 자기 자신의 지목은 정보가 아님
    try:
        line_len = len(game.players[claimer_idx].own_cards)
    except (IndexError, AttributeError):
        line_len = -1
    _claims_for(game, attacker_idx).setdefault(claimer_idx, {})[val_spec] = line_len


def claimed_values_of(game, attacker_idx, tidx):
    """상대 tidx 의 패에 '없음'이 확정된(=그가 지목했던) 값 spec 집합.

    ★ 수명 필터: 지목 시점보다 그 상대의 라인이 길어졌으면(=카드를 뽑았으면)
      그 지목은 무효로 보고 제외한다.
    """
    store = getattr(game, _CLAIM_ATTR, None)
    if not store or attacker_idx not in store:
        return set()
    entries = store[attacker_idx].get(tidx)
    if not entries:
        return set()
    try:
        cur_len = len(game.players[tidx].own_cards)
    except (IndexError, AttributeError):
        return set(entries.keys())
    # ★ 라인 길이가 지목 시점과 같을 때만 유효
    return {spec for spec, when_len in entries.items() if when_len == cur_len}


def broadcast_claim(game, claimer_idx, val_spec):
    """어떤 플레이어(claimer_idx)가 val_spec 을 지목했다 → 모든 AI 시점에 반영.

    ★ 규칙 근거 (EHone 확정):
      지목은 "내 패에는 이 값이 없으니, 네 패에 있을 것이다" 라는 추리다.
      → claimer 의 패에는 val_spec 이 **없다** (확정).
      → 따라서 claimer 의 패를 추론하는 모든 AI 는 val_spec 을 후보에서 제외한다.

    ★ 수명: 지목 시점의 claimer 라인 길이와 함께 저장되며, claimer 가 이후
      카드를 뽑아 라인이 길어지면 그 지목은 자동 무효가 된다 (claimed_values_of).

    run_game 쪽에서 '지목이 발생할 때마다' 한 번만 호출하면 된다.
    """
    if val_spec is None:
        return
    for idx in range(len(game.players)):
        if idx == claimer_idx:
            continue
        if game.players[idx].is_human:
            continue        # 사람에게는 AI 기억을 만들 필요 없음
        note_claim(game, idx, claimer_idx, val_spec)


def note_reveal(game, tidx, card_spec):
    """카드가 공개됐다 → 모든 AI 의 후보 풀에서 제거된다.

    (별도 저장 없이도 game.table.public 로 자동 반영되지만,
     값 페널티/지목 기억과의 일관성을 위해 명시적으로 알려줄 수 있게 둔다.)
    """
    return card_spec


# ---------------------------------------------------------------------------
# 후보 생성 / 선택
# ---------------------------------------------------------------------------
def score_candidates(game, attacker_idx, rng=None, include_joker=False):
    """(tidx, pos, val, prob) 리스트 반환. val 은 View 표기 문자열.

    적용 제약/필터:
      1) 색 제약: 각 자리에는 그 자리의 공개 색(■/□)의 스펙만 온다
      2) 이미 찍어서 틀린 조합(기억)은 제외 → 같은 추론 반복 금지
      3) 값별 실패 페널티 → '그 상대에게 그 값은 없다'를 누적 반영
      4) 지목 이력(absent, 수명 반영) → 상대가 지목한 값은 그 상대 패에 없다
      5) include_joker=False (기본) 이면 조커 제외
    """
    pool = hidden_card_pool(game, attacker_idx)
    memory = _memory_for(game, attacker_idx)
    out = []
    for ti, opp in enumerate(game.players):
        if ti == attacker_idx or opp.is_eliminated():
            continue
        # ★ 이 상대가 지목했던 값 = 자기 패에 '없음'이 확정된 값 (수명 반영)
        absent = claimed_values_of(game, attacker_idx, ti)
        probs = position_spec_probabilities(opp, pool, absent=absent)
        for (pos, spec), p in probs.items():
            disp = spec_to_display(spec)        # (value, is_black) -> '3b'
            if spec_is_joker(disp) and not include_joker:
                continue
            if (ti, pos, disp) in memory:
                continue                        # (2) 이미 틀린 조합
            pen = value_failure_penalty(game, attacker_idx, ti, disp)
            if pen <= 0.0:
                continue                        # (3) 그 값은 없다 (확정 배제)
            out.append((p * pen, ti, pos, disp))
    if rng is not None:
        out = [(p + rng.random() * 1e-12, ti, pos, val) for p, ti, pos, val in out]
    return out


def prob_guess_for(game, attacker_idx, rng=None, top_k=1):
    """확률 추론으로 (tidx, pos, val) 선택. 지목 가능 자리 없으면 None.

    run_game.random_guess_for 대체용 (동일 인터페이스).

    top_k > 1 : 상위 k개 중 무작위 (예측 불가성)

    ★ 조커 (EHone 규칙):
      별도 확률로 '대충 섞지' 않는다. position_spec_probabilities 가
      '그 자리에 올 숫자가 전무할 때'만 조커를 높은 확률로 올려 주므로,
      조커는 자연히 '추리확률 0% 근접' 상황에서만 후보가 된다.
    """
    cands = score_candidates(game, attacker_idx, rng=rng, include_joker=True)
    if not cands:
        return _fallback(game, attacker_idx, rng)
    cands.sort(key=lambda x: x[0], reverse=True)
    k = max(1, min(top_k, len(cands)))
    pick = rng.randint(0, k - 1) if (rng is not None and k > 1) else 0
    _, ti, pos, spec = cands[pick]
    return ti, pos, spec


def _fallback(game, attacker_idx, rng):
    """확률 후보가 0일 때의 최후 수단 (지목 가능 자리 + 임의값).

    기억(실패 조합)과 값 페널티를 반영해 아직 안 찍어본 값을 우선한다.
    """
    import random
    rng = rng or random
    memory = _memory_for(game, attacker_idx)
    spots = []
    for ti, p in enumerate(game.players):
        if ti == attacker_idx or p.is_eliminated():
            continue
        for c in p.own_cards:
            if c not in p.revealed_cards:
                spots.append((ti, p.pos_of(c)))
    if not spots:
        return None
    rng.shuffle(spots)
    best = None
    for ti, pos in spots:
        choices = []
        for s in _ALL_SPECS:
            if (ti, pos, s) in memory:
                continue
            if value_failure_penalty(game, attacker_idx, ti, s) <= 0.0:
                continue
            choices.append(s)
        if choices:
            return ti, pos, rng.choice(choices)
        if best is None:
            best = (ti, pos)
    if best is not None:
        return best[0], best[1], rng.choice(_ALL_SPECS)
    return None


def continue_decision(game, attacker_idx, rng=None, verbose=False):
    """연속 지목 여부를 **기대값**으로 판단한다 (정답 직후 호출).

    설계 (EHone 요청: "정답이 훤히 보이는 패는 반드시 이어가야 한다")
    ------------------------------------------------------------------
    이 게임의 승패는 '내 카드가 언제 다 공개되느냐' 싸움이다.
    따라서 정답/오답의 가치는 둘 다 **탈락 진행도**로 대칭적으로 본다.

      · 정답 이득(gain)  : 상대 카드 1장 공개 → 상대 탈락 진행
                           = 1 / (상대 비밀 카드 수)
                           (상대가 탈락 직전일수록 1장이 결정적 → 이득 큼)
      · 오답 손실(loss)  : 내 카드 1장 공개 → 내 탈락 진행
                           = 1 / (내 비밀 카드 수) × 위험 계수
                           (내가 탈락 직전이면 1장이 치명적 → 손실 큼)

      · 위험 계수: 어느 카드가 공개되느냐에 따라 다르다.
          - 덱 남음  : '방금 뽑은 카드'만 공개 → 그 카드는 상대가 이미
                       위치를 짐작했을 가능성이 높아 손실이 작다 (0.6배)
          - 덱 소진  : 내 패 중 '임의' 1장이 공개 → 통제 불가 (1.0배)

      기대값:  EV = p·gain - (1-p)·loss·risk
      →  EV > 0 이면 계속.

    ★ 확정 정답 처리:
      최고 후보 확률이 CONFIDENT(기본 0.75) 이상이면 기대값 계산 없이 즉시 계속.
      ("훤히 보이는 패는 반드시 이어간다") — 확률 1.0 이면 당연히 포함.

    Returns: (계속할지 bool, 진단 dict)
    """
    cands = score_candidates(game, attacker_idx, rng=None)
    if not cands:
        return False, {"reason": "no_candidates"}

    cands.sort(key=lambda x: x[0], reverse=True)
    top_prob, ti, pos, val = cands[0]

    # ★ 확정에 가까운 정답 → 무조건 계속
    if top_prob >= CONFIDENT_THRESHOLD:
        return True, {"reason": "confident", "p": round(top_prob, 4)}

    # 남은 비밀 카드 수 (탈락 진행도 기준)
    opp = game.players[ti]
    opp_hidden = max(1, sum(1 for c in opp.own_cards if c not in opp.revealed_cards))
    me = game.players[attacker_idx]
    my_hidden = max(1, sum(1 for c in me.own_cards if c not in me.revealed_cards))

    gain = 1.0 / opp_hidden                 # 상대 카드 1장 공개의 가치
    loss = 1.0 / my_hidden                  # 내 카드 1장 공개의 손실
    risk = DECK_LEFT_RISK if game.table.deck else DECK_EMPTY_RISK

    p = top_prob
    ev = p * gain - (1.0 - p) * loss * risk
    info = {"reason": "ev", "p": round(p, 4), "gain": round(gain, 4),
            "loss": round(loss, 4), "risk": risk, "ev": round(ev, 4),
            "move": (ti, pos, val)}
    if verbose:
        print(f"    [연속판단] p={p:.3f} gain={gain:.3f} loss={loss:.3f} "
              f"risk={risk} EV={ev:+.4f} → {'계속' if ev > 0 else '중단'}")
    return ev > 0, info


def should_continue(game, attacker_idx, hit, rng=None, min_prob=None):
    """정답 후 연속 지목 여부 (기존 인터페이스 유지).

    hit=True 이면 기대값 기반 판단(continue_decision)으로 위임한다.
    min_prob 를 주면 예전 방식(최고 확률 임계)으로 동작한다.
    """
    if not hit:
        return False
    if min_prob is not None:
        cands = score_candidates(game, attacker_idx, rng=rng)
        if not cands:
            return False
        cands.sort(key=lambda x: x[0], reverse=True)
        return cands[0][0] >= min_prob
    return continue_decision(game, attacker_idx, rng=rng)[0]


def choose_joker_slot(player, jcard, rng=None, top_k=1, verbose=False):
    """조커를 놓을 슬롯(0..M)을 **전략적으로** 고른다 (EHone 규칙).

    전략 (EHone 지시): "경험상 2b 7w 처럼 간격이 넓은 쪽으로 삽입하자"
    ------------------------------------------------------------------
    조커는 '벽'이 되어 라인을 좌/우 구간으로 가른다. 조커를 값 간격이
    넓은 자리에 세울수록 상대가 추리해야 할 빈 구간이 커져 헷갈린다.

    측정: 각 슬롯 s(0..M)에 조커를 넣었을 때,
      · 조커 왼쪽 카드의 값(없으면 -1)과 오른쪽 카드의 값(없으면 12)을 보고
      · 그 조커가 감추는 구간의 '폭' = (오른쪽 값 - 왼쪽 값 - 1)
        (사이에 들어갈 수 있는 서로 다른 값의 개수)
      폭이 큰 슬롯을 고른다.

      예) 라인 [2b, 5w, 7b] (값 2,5,7)
          슬롯0(맨앞)   : 왼쪽=-1, 오른쪽=2 → 폭 = 2-(-1)-1 = 2   (0,1)
          슬롯1(2|5)    : 왼쪽=2,  오른쪽=5 → 폭 = 5-2-1   = 2   (3,4)
          슬롯2(5|7)    : 왼쪽=5,  오른쪽=7 → 폭 = 7-5-1   = 1   (6)
          슬롯3(맨뒤)   : 왼쪽=7,  오른쪽=12→ 폭 = 12-7-1  = 4   (8..11)
        → 맨뒤(4) 또는 슬롯0/1(2) 중에서 고른다.
      동점이면 rng 로 무작위 (예측 불가성).

    top_k > 1 이면 상위 k개 슬롯 중 무작위로 고른다 (덜 뻔하게).

    Returns: 슬롯 번호 int
    """
    import random as _random
    rng = rng or _random

    line = player.own_cards
    M = len(line)
    # 각 카드의 값 (조커는 None → 벽 계산에서 제외)
    vals = []
    for c in line:
        vals.append(c.value)

    scored = []
    for s in range(M + 1):                      # 슬롯 0..M
        # 왼쪽 이웃 값 (조커 건너뛰며 가장 가까운 숫자)
        left_val = -1
        for i in range(s - 1, -1, -1):
            if vals[i] is not None:
                left_val = vals[i]
                break
        # 오른쪽 이웃 값
        right_val = 12
        for i in range(s, M):
            if vals[i] is not None:
                right_val = vals[i]
                break
        width = max(0, right_val - left_val - 1)   # 감출 수 있는 값 개수
        # 같은 색 조커는 그 색 값 근처가 자연스러우니, 색 일치 보너스(약)
        scored.append((width, s))

    scored.sort(key=lambda x: -x[0])
    k = max(1, min(top_k, len(scored)))
    pick = rng.randint(0, k - 1) if k > 1 else 0
    width, slot = scored[pick]
    if verbose:
        print(f"    [조커슬롯] 라인={[c.display() for c in line]} "
              f"→ 후보(폭,슬롯)={scored[:4]} 선택={slot}")
    return slot


def choose_joker_side(player, display, ncard, rng=None, verbose=False):
    """숫자 카드가 조커(벽)에 걸렸을 때 '앞(front)/뒤(back)'를 고른다.

    전략: 조커를 기준으로 '값 간격이 넓은 쪽'에 새 카드를 두어,
          남는 빈 구간이 넓게 유지되도록 한다.
      · 새 카드 값을 v, 벽 왼쪽 이웃 값 lo, 오른쪽 이웃 값 hi 라 하면
        - front 로 놓으면 (lo, v) 구간이, back 이면 (v, hi) 구간이 남는다.
      · 더 넓은 간격을 남기는 쪽을 고른다.

    Returns: "front" | "back"
    """
    import random as _random
    rng = rng or _random

    v = ncard.value
    if v is None:
        return rng.choice(["front", "back"])

    # 벽(조커)의 위치 찾기
    line = player.own_cards
    wall_idx = None
    for i, c in enumerate(line):
        if c.display() == display and c.is_joker:
            wall_idx = i
            break
    if wall_idx is None:
        return rng.choice(["front", "back"])

    # 벽 좌우의 가장 가까운 숫자 값
    lo = -1
    for i in range(wall_idx - 1, -1, -1):
        if line[i].value is not None:
            lo = line[i].value
            break
    hi = 12
    for i in range(wall_idx + 1, len(line)):
        if line[i].value is not None:
            hi = line[i].value
            break

    front_width = max(0, v - lo - 1)     # front 로 놓으면 남는 왼쪽 간격
    back_width = max(0, hi - v - 1)      # back 으로 놓으면 남는 오른쪽 간격
    if front_width > back_width:
        pick = "front"
    elif back_width > front_width:
        pick = "back"
    else:
        pick = rng.choice(["front", "back"])
    if verbose:
        print(f"    [조커앞뒤] 벽={display} 새카드값={v} lo={lo} hi={hi} "
              f"front폭={front_width} back폭={back_width} → {pick}")
    return pick


class StrategicDecider:
    """CPU/자동응답용 결정자: 조커 삽입·앞뒤에 '간격 넓은 쪽' 전략을 쓴다.

    Game.draw_and_insert(player, decide) 는 decide.select_joker_slot(card, M) /
    ask_joker_side(display) 만 호출하고 **player 를 넘겨주지 않는다**.
    그래서 전략 계산에 필요한 player 를 얻기 위해, run_game 쪽에서
    `dec.bind_player(player)` 를 먼저 호출해 둔다.

    사용 (run_game):
        dec = prob_ai.StrategicDecider(random)
        ...
        dec.bind_player(cur)
        drew = game.draw_and_insert(cur, dec)
    """

    def __init__(self, rng=None, top_k=1, verbose=False):
        import random
        self.rng = rng or random
        self.top_k = top_k
        self.verbose = verbose
        self._player = None
        self._pending_joker = None      # 이번 draw 에서 뽑힌 조커 (참고용)

    # --- player 바인딩 ---------------------------------------------------
    def bind_player(self, player):
        """이번 draw 의 주체를 알려준다 (전략 계산용)."""
        self._player = player
        return self

    # --- Game 이 호출하는 인터페이스 --------------------------------------
    def select_joker_slot(self, card, M):
        """조커 삽입 슬롯. player 가 바인딩돼 있으면 '간격 넓은 쪽' 전략."""
        if self._player is not None:
            return choose_joker_slot(self._player, card, rng=self.rng,
                                     top_k=self.top_k, verbose=self.verbose)
        return self.rng.randint(0, M)

    def ask_joker_side(self, display):
        """(구형 호환) 숫자 카드 정보 없이 앞/뒤. player 알면 임시로 처리."""
        return self.rng.choice(["front", "back"])

    def ask_joker_side_full(self, display, ncard):
        """★ Game 이 실제로 호출하는 버전: 벽 표시 + 새 카드까지 받는다.

        → '간격 넓은 쪽' 전략을 정확히 계산할 수 있다.
        """
        if self._player is not None:
            return choose_joker_side(self._player, display, ncard,
                                     rng=self.rng, verbose=self.verbose)
        return self.rng.choice(["front", "back"])


# ---------------------------------------------------------------------------
# 자체 점검
# ---------------------------------------------------------------------------
def _selftest():
    import random as _r
    import DavinciCode as md

    print("=== prob_ai 자체 점검 ===")

    _r.seed(3)
    g = md.Game(2, human_name="나")
    for p in g.players:
        p.black_deal_count = _r.randint(0, g.per)
    g.deal()
    for p in g.players:
        p.sort_hand()
    g.start_first_turn()

    pool = hidden_card_pool(g, 0)
    print("남은 풀:", len(pool), "상대 미공개:", opp_hidden_count(g, 0))

    opp = g.players[1]
    probs = position_spec_probabilities(opp, pool)
    by_pos = {}
    for (pos, spec), p in probs.items():
        by_pos.setdefault(pos, 0.0)
        by_pos[pos] += p
    print("자리별 확률합:", {k: round(v, 3) for k, v in sorted(by_pos.items())})

    print("실제값 순위(점검용, AI는 안 씀):")
    for i, c in enumerate(opp.own_cards):
        if c in opp.revealed_cards:
            continue
        rank = sorted([(p, spec) for (pos, spec), p in probs.items() if pos == i + 1],
                      reverse=True)
        actual_spec = (c.value, c.is_black)
        pos_actual = next((r for r, (p, s) in enumerate(rank, 1) if s == actual_spec), None)
        top = [spec_to_display(s) for _, s in rank[:5]]
        print(f"  자리{i+1} 실제={c.display()} (색={'흑' if c.is_black else '백'}) "
              f"→ 순위 {pos_actual}/{len(rank)} 상위5={top}")

    def measure(use_prob, games=40, turns_per=150):
        hits = tot = 0
        for gs in range(games):
            _r.seed(100 + gs)
            gg = md.Game(2, human_name="나")
            for p in gg.players:
                p.black_deal_count = _r.randint(0, gg.per)
            gg.deal()
            for p in gg.players:
                p.sort_hand()
            gg.start_first_turn()
            dec = md.RandomDecider(_r)
            for _ in range(turns_per):
                cur = gg.turn_index
                if gg.table.deck:
                    gg.draw_and_insert(gg.players[cur], dec)
                opps = [(i, p) for i, p in enumerate(gg.players)
                        if i != cur and not p.is_eliminated()]
                if not opps:
                    break
                if use_prob:
                    gv = prob_guess_for(gg, cur, rng=_r)
                else:
                    spots = []
                    for ti, p in opps:
                        for c in p.own_cards:
                            if c not in p.revealed_cards:
                                spots.append((ti, p.pos_of(c)))
                    if not spots:
                        break
                    ti, pos = _r.choice(spots)
                    gv = (ti, pos, _r.choice(_ALL_SPECS))
                if gv is None:
                    break
                ti, pos, val = gv
                tgt = gg.players[ti]
                actual = tgt.card_at_pos(pos)
                tot += 1
                if actual is not None and actual.display() == val:
                    hits += 1
                    tgt.reveal_attacked(pos)
                    if actual not in gg.table.public:
                        gg.table.public.append(actual)
                else:
                    # ★ 오답 조합은 기억 → 같은 추론 반복 금지
                    if use_prob:
                        remember_failure(gg, cur, gv)
                    pen = gg.players[cur].reveal_failed(None)
                    if pen is not None and pen not in gg.table.public:
                        gg.table.public.append(pen)
                if len([1 for p in gg.players if not p.is_eliminated()]) <= 1:
                    break
                gg.next_turn()
        return hits, tot

    h1, t1 = measure(False)
    h2, t2 = measure(True)
    print(f"랜덤 적중: {h1}/{t1} = {h1/max(1,t1):.1%}")
    print(f"추론 적중: {h2}/{t2} = {h2/max(1,t2):.1%}")
    print("=== 점검 끝 ===")


if __name__ == "__main__":
    _selftest()
