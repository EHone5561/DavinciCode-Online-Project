# -*- coding: utf-8 -*-
"""다빈치 코드 — 텍스트 콘솔 실행기 (사람 1명 + CPU) — 조커 철학 라인 모델 반영.

책임 분리:
  ConsoleView : 터미널 출력(print) 및 사람 입력(input) 전담  [이 파일내 유일 print/input]
  main()      : 한 판 진행(Controller). 순수 모델 DavinciCode.Game 을 굴리고
                표시·입력은 전부 ConsoleView 에게 위임한다. 모델은 print/input 금지.

조커 반영 요약:
  [A] 일반 숫자 삽입 : 조커(벽)에 걸리면 사람(ConsoleView)이 '앞/뒤'를,
      CPU/자동은 랜덤(연쇄 최대 k회)으로 결정한다.
  [B] 조커 삽입     : 사람이 슬롯 0..M 을 ConsoleView 로, CPU/자동은 랜덤 슬롯으로 결정.
  [C] 추측값        : 파서·판정 양쪽에서 Jb/Jw 를 허용한다.

실행 예:
  python -E run_game.py 2                 # 인원 2 고정(사람 1+CPU 1)
  AUTOHUMAN=1 python -E run_game.py 2     # 사람조차도 자동 응답
"""
import os
import random
import sys
import time
import DavinciCode as md  # 순수 모델

BLACK_BOX = "\u25a0"
WHITE_BOX = "\u25a1"
AUTOHUMAN = os.environ.get("AUTOHUMAN") == "1"
# 디버그 모드: 상대(CPU)의 비밀(뽑은 값·라인 배치 등)을 화면에 노출.
# 기본값은 사람이 보는 '정상 화면'(기밀 가림)이고, 검사용으로만 True 로 켠다.
DEBUG_REVEAL = os.environ.get("DEBUG_REVEAL") == "1"

# 디버깅/빠른 실행용 무지연 버전. (일반 run_game.py 는 0.9초 지연 시연판)
RESULT_DELAY = float(os.environ.get("RESULT_DELAY", "0"))


def value_set():
    """추측값 후보 전체 ('0b'..'bw' + 조커 'Jb'/'Jw')."""
    vals = {md.Card(v, b).display() for v in range(12) for b in (True, False)}
    vals |= {"Jb", "Jw"}
    return vals


class ConsoleView:
    """표시·사람 입력 전담 (View). 삽입/앞뒤/슬롯/추측 입력을 제공한다."""

    def __init__(self, game):
        self.game = game
        self.human = game.human()

    # ================= 표시 =================
    def _cell(self, card, show_value, star=False):
        s = card.display() if show_value else (
            BLACK_BOX if card.is_black else WHITE_BOX)
        return s + ("*" if star else "")

    def result_line(self, text):
        print("  " + text)
        # 결과 문구는 자동으로 연속 이어지므로 읽을 여유를 둔다. (RESULT_DELAY=0 시 무지연)
        if RESULT_DELAY:
            time.sleep(RESULT_DELAY)

    def pause(self, sec=None):
        """화면 전환 간 여유. sec 생략 시 RESULT_DELAY 만큼 (0이면 즉시)."""
        sec = RESULT_DELAY if sec is None else sec
        if sec:
            time.sleep(sec)

    def notice(self, text):
        print(text)

    def invalid(self, why):
        print(f"   [!] {why}")

    def begin(self, n):
        print("=" * 52)
        print("   다빈치 코드 (Davinci Code) — 텍스트 뼈대 (조커 라인 모델)")
        print(f"   인원 {n} (사람 1 + CPU {n-1})")
        print("=" * 52)

    def show_deal(self):
        h = self.human
        print("\n---- 내 시작 패 (값 다 보임) ----")
        for i, c in enumerate(h.own_cards, 1):
            tag = BLACK_BOX if c.is_black else WHITE_BOX
            print(f"  자리{i}: {c.display()}  ({tag})")
        print(f"---- 분배 완료 · 공용 덱 {len(self.game.table.deck)}장 ----")
        print()

    def _line_of(self, viewer, owner, drawn=None):
        out = []
        for i, c in enumerate(owner.own_cards, 1):
            show = (c in owner.revealed_cards) or (owner is viewer)
            star = (owner is viewer and drawn is not None and c is drawn)
            out.append(f"{i}:{self._cell(c, show, star)}")
        return "  ".join(out)

    def board_for_human(self, drawn, just_drew):
        """사람이 결정할 때 정밀 화면. (상대 정보는 색/공개만, 기밀 비노출)"""
        h = self.human
        print(f"\n──── 턴(라운드 {self.game.round_number}) · 차례: {h.name} ────")
        print(f"   공용 덱 {len(self.game.table.deck)}장"
              + (f" · 방금 뽑은 카드를 배치했음" if just_drew else ""))

        print("\n----- 상대 패 -----")
        opponents = [p for p in self.game.players
                     if p is not h and not p.is_eliminated()]
        if not opponents:
            print("   (남은 상대 없음)")
        else:
            for i, p in enumerate(self.game.players):
                if p is h or p.is_eliminated():
                    continue
                hidden = sum(1 for c in p.own_cards if c not in p.revealed_cards)
                print(f"  [#{i+1}] {p.name}  (비밀 {hidden} · 공개 {len(p.revealed_cards)})")
                print("      " + self._line_of(h, p))

        print("\n----- 내 패 (값 전부 보임, * = 방금 뽑음) -----")
        print("      " + self._line_of(h, h, drawn))

        self.show_public()

    def cpu_turn_intro(self, cur, drew):
        """상대(CPU) 차례 안내 (사람 관점 — 기밀은 노출하지 않는다).

        - 사람은 상대인 cur 의 라인 실제 값 / 뽑은 카드 값을 모른다.
        - 상대 차례가 시작됐고 카드를 몇 장 배치했는지만 전한다.
        - DEBUG_REVEAL=1 이면 (검사용으로) 상세(값·배치)까지 함께 보여준다.
        """
        if drew is not None:
            head = f"[{cur.name}의 턴] 라운드 {self.game.round_number} · " \
                   f"덱 {len(self.game.table.deck)}장 · " \
                   f"(카드 1장을 뽑아 배치함)"
        else:
            head = f"[{cur.name}의 턴] 라운드 {self.game.round_number} · " \
                   f"덱 0장 (덱 소진, 뽑기 없음)"
        print("\n" + head)
        if DEBUG_REVEAL and drew is not None:
            # 검사용 상세 (일반 사람 화면에선 출력 금지)
            print(f"   [debug] 뽑음({drew.display()})  "
                  f"배치={[c.display() for c in cur.own_cards]}")

    def show_public(self):
        pubs = self.game.table.public
        if pubs:
            print("   [공개] " + ", ".join(c.display() for c in pubs))

    def my_line_before_insert(self):
        """삽입 질문 직전에 사람에게 자기 현재 라인을 알려 이해 돕는다."""
        print(f"   <내 라인(현재)> {[c.display() for c in self.human.own_cards]}")

    # ================= 사람 입력 =================
    def read_line(self, prompt):
        return input(prompt).strip()

    def ask_player_count(self):
        while True:
            s = self.read_line("인원 수(2~4, 사람 1+CPU 그 외) : ") if not AUTOHUMAN \
                else str(random.randint(2, 4))
            if s.isdigit() and 2 <= int(s) <= 4:
                return int(s)
            print("2~4 사이 정수 입력.")

    def ask_black_count(self, per):
        """사람 기본분배의 검은 카드 수. AUTOHUMAN이면 랜덤."""
        if AUTOHUMAN:
            return random.randint(0, per)
        while True:
            s = self.read_line(f"받을 '검은 카드' 수 (0~{per}) : ")
            if s.isdigit() and 0 <= int(s) <= per:
                return int(s)
            print(f"0~{per} 사이 정수.")

    def ask_guess(self):
        """사람 추측 3-튜플 또는 None(멈춤). 여기선 문법(조커 포함)만 검사."""
        guessable = value_set()
        while True:
            if AUTOHUMAN:
                return random_guess_for(self.game, self.game.turn_index) \
                    if random.random() < 0.5 else None
            s = input(
                ">> 추측: [상대#] [자리] [값(3b/aw/Jb/Jw)]   q=멈춤: ").strip()
            low = s.lower()
            if low in ("q", "quit", "그만", "종료"):
                return None
            parts = s.split()
            if len(parts) != 3:
                print("   3개 항목을 띄어 쓰세요. 예: 2 3 Jb")
                continue
            num, pos, val = parts
            n = len(self.game.players)
            if not num.isdigit() or not (1 <= int(num) <= n):
                print(f"   상대번호는 1~{n} 범위.")
                continue
            if not pos.isdigit() or int(pos) < 1:
                print("   자리번호는 1 이상 정수.")
                continue
            # 값 정규화: 숫자 색은 소문자(3b·aw), 조커는 대문자 Jb/Jw 로 통일.
            raw = val.strip().lower()
            if raw[:1] == "j":          # jb/jw → Jb/Jw (display()와 동일하게)
                raw = "J" + raw[1:]
            if raw not in guessable:
                print("   값 형식 오류 (예 3b·aw·Jb·Jw).")
                continue
            return int(num) - 1, int(pos), raw

    def ask_more_guess(self):
        if AUTOHUMAN:
            return random.random() < 0.4
        while True:
            s = input("   연속 지목? (Enter=계속 / q=그만) : ").strip().lower()
            if s in ("q", "quit", "그만", "종료"):
                return False
            if s == "":
                return True
            print("   Enter 나 q 만 입력.")

    def ask_fail_reveal_pos(self, owner):
        hidden = [i for i, c in enumerate(owner.own_cards, 1)
                  if c not in owner.revealed_cards]
        if AUTOHUMAN:
            return random.choice(hidden) if hidden else None
        while True:
            s = input(f"   벌칙: 공개할 자리 {hidden} 중 1 : ").strip()
            if s.isdigit() and int(s) in hidden:
                return int(s)
            print(f"   {hidden} 중 입력.")

    # ---------------- 사람 차례 조커 삽입 콜백 (HumanDecider 용) --------------
    def ask_joker_insert_slot(self, card, M):
        """[B] 조커 삽입 — 슬롯 0..M. 범위 밖이면 재입력."""
        if AUTOHUMAN:
            return random.randint(0, M)
        self.notice(f"\n★ 조커({card.display()}) 를 뽑았습니다! "
                    f"삽입 슬롯을 고르세요 (현재 {len(self.human.own_cards)}장).")
        self.my_line_before_insert()
        while True:
            s = input(f"   슬롯 0~{M} (0=맨앞, n=n번째 뒤, {M}=맨뒤) : ").strip()
            if s.isdigit():
                i = int(s)
                if 0 <= i <= M:
                    return i
                self.invalid(f"범위 {0}~{M} 밖. 다시.")
            else:
                self.invalid("정수만.")

    def ask_joker_side(self, display):
        """[A] 숫자가 조커(벽)에 걸렸을 때 '앞/뒤' 답. (현재 내 라인 표시 후 질문)"""
        if AUTOHUMAN:
            return random.choice(["front", "back"])
        # 물어보기 전, 지금 내 패의 상황(라인)을 보여줘 위치를 알게 한다.
        print()
        print("   현재 내 패: " + self._line_of(self.human, self.human))
        print("")
        print()
        while True:
            s = input(
                f"   가로막는 조커({display}) — 새 카드를 '앞(왼쪽)'이나 '뒤(오른쪽)' "
                f"중 어느 쪽에? (앞=0/front  뒤=1/back) : ").strip().lower()
            if s in ("앞", "왼쪽", "0", "front", "f"):
                return "front"
            if s in ("뒤", "오른쪽", "1", "back", "b", ""):
                return "back"
            self.invalid("앞(0) 또는 뒤(1) 입력.")


class HumanDecider:
    """사람 차례: ConsoleView 로 슬롯/앞뒤를 물어 모델 decide 콜백 역할을 한다.

    Game.draw_and_insert(player, decide) 에 넘겨 게임이 이 콜백을 호출한다.
    """
    def __init__(self, view):
        self.view = view

    def select_joker_slot(self, card, M):
        return self.view.ask_joker_insert_slot(card, M)

    def ask_joker_side(self, display):
        return self.view.ask_joker_side(display)


def random_guess_for(game, attacker_idx):
    """CPU(및 자동응답 사람)용 유효 추측 (상대, 미공개 자리, 값) 하나 생성.

    공개 정보 + 본인 패만 보는 '정당한' 선택. 값 후보는 조커 포함 전체.
    Returns: (tidx, pos, val) or None.
    """
    guessable = sorted(value_set())
    opps = [(i, p) for i, p in enumerate(game.players)
            if i != attacker_idx and not p.is_eliminated()]
    cands = []
    for ti, tp in opps:
        for c in tp.own_cards:
            if c in tp.revealed_cards:
                continue
            cands.append((ti, tp.pos_of(c)))     # (상대, 미공개 자리)
    if not cands:
        return None
    # 반칙 금지: 본인 공개정보+자기패로만 '유효 미공개 자리'에 대해 값을 전역 랜덤으로 제안.
    ti, pos = random.choice(cands)
    return ti, pos, random.choice(guessable)     # 전체 26종(조커 포함) 중 균일 선택


def _main(player_count=None):
    game0 = md.Game(2)
    tmpv = ConsoleView(game0)
    if player_count is None:
        player_count = tmpv.ask_player_count()
    if not (2 <= player_count <= 4):
        print("인원은 2~4.")
        return 1

    game = md.Game(player_count, human_name="나")
    view = ConsoleView(game)
    view.begin(player_count)

    per = game.per
    hum = game.human()
    hum.black_deal_count = view.ask_black_count(per)
    for p in game.players:
        if not p.is_human:
            p.black_deal_count = random.randint(0, per)
    game.deal()
    for p in game.players:
        p.sort_hand()
    view.show_deal()

    next_rank = player_count
    elim_rank = {}

    def sweep():
        nonlocal next_rank
        for i2, pp in enumerate(game.players):
            if i2 not in elim_rank and pp.is_eliminated():
                elim_rank[i2] = next_rank
                view.result_line(f"★ {pp.name} 탈락 → {next_rank}등 확정")
                next_rank -= 1

    def alive():
        return [i for i, p in enumerate(game.players) if not p.is_eliminated()]

    game.start_first_turn()
    sweep()

    guard = 0
    max_guard = 4000
    while len(alive()) > 1 and guard < max_guard:
        guard += 1
        cur = game.players[game.turn_index]

        # (1) 의무 뽑기 + 규칙 삽입 (조커=슬롯 / 숫자=벽 앞뒤 연쇄)
        dec = HumanDecider(view) if (cur.is_human and not AUTOHUMAN) \
            else md.RandomDecider(random)
        drew = None
        if game.table.deck:
            drew = game.draw_and_insert(cur, dec)
            # 뽑기/배치 상세는 사람/CPU 전용 화면 함수에서 적절히 처리
            # (사람: board_for_human 으로 자기 값 표시 / CPU: cpu_turn_intro 로 기밀 비노출)

        if cur.is_human:
            view.board_for_human(drew, drew is not None)
        else:
            view.cpu_turn_intro(cur, drew)

        # (2) 추측 반복
        keep = True
        while keep and len(alive()) > 1:
            cur_id = game.turn_index
            cur_p = game.players[cur_id]
            opps = [(i, p) for i, p in enumerate(game.players)
                    if i != cur_id and not p.is_eliminated()]
            if not opps:
                break
            if cur_p.is_human and not AUTOHUMAN:
                g = view.ask_guess()
                if g is None:
                    break
                tidx, pos, val = g
                if tidx == cur_id:
                    view.invalid("자기 자신 지목 불가. 다시.")
                    continue
                tgt = game.players[tidx]
                card = tgt.card_at_pos(pos)
                if card is None:
                    view.invalid(f"{tgt.name} 는 자리가 {len(tgt.own_cards)} 개뿐.")
                    continue
                if card in tgt.revealed_cards:
                    view.invalid("그 자리는 이미 공개. 다시.")
                    continue
            else:
                cand = random_guess_for(game, cur_id)
                if cand is None:
                    break
                tidx, pos, val = cand
                tgt = game.players[tidx]

            actual = tgt.card_at_pos(pos)
            hit = (actual is not None and actual.display() == val)  # Jb/Jw 포함
            if hit:
                rc = tgt.reveal_attacked(pos)
                if rc is not None and rc not in game.table.public:
                    game.table.public.append(rc)
                view.result_line("✔ 정답! %s → %s 자리%d = %s (%s) 정답·공개."
                                 % (cur_p.name, tgt.name, pos, val, rc.display()))
                view.show_public()
                sweep()
                if len(alive()) <= 1:
                    keep = False
                    break
                if cur_p.is_human:
                    if not view.ask_more_guess():
                        keep = False
                else:
                    if random.random() < 0.45:
                        keep = False
            else:
                if drew is not None and drew not in cur_p.revealed_cards:
                    cur_p.reveal(drew)
                    if drew not in game.table.public:
                        game.table.public.append(drew)
                    # 뽑았던 그 카드가 공개된다(전원 공개 정보). 전체 배치 구성은
                    # 더 이상 노출하지 않는다(상대 관점 기밀).
                    view.result_line(
                        "✘ 오답! 벌칙: 방금 뽑은 %s 카드가 공개됨." % drew.display())
                else:
                    if cur_p.is_human and not AUTOHUMAN:
                        hpos = view.ask_fail_reveal_pos(cur_p)
                    else:                       # CPU 와 AUTOHUMAN 은 랜덤
                        hpos = None
                    if hpos:
                        pen = cur_p.own_cards[hpos - 1]
                        cur_p.reveal(pen)
                    else:
                        pen = cur_p.reveal_failed(None)
                    if pen is not None and pen not in game.table.public:
                        game.table.public.append(pen)
                    view.result_line("✘ 오답! 벌칙 공개: %s %s" % (
                        cur_p.name, (pen.display() if pen else "(없음)")))
                view.show_public()
                sweep()
                keep = False
        # end 추측 루프

        if len(alive()) <= 1:
            break
        game.next_turn()
    # end 전체 루프

    surv = alive()
    print("\n" + "=" * 52)
    shown = {}
    for i2, p in enumerate(game.players):
        shown[i2] = elim_rank.get(i2)
    if len(surv) == 1:
        shown[surv[0]] = 1
        print(f"🏆 1등 : {game.players[surv[0]].name}")
    else:
        print("게임이 정상 종료되지 못함 (승자 없음).")
    print("  최종 순위:")
    for i2, p in enumerate(game.players):
        r = shown[i2]
        if r:
            tag = " (사람)" if p.is_human else ""
            print(f"    {r}등  {p.name}{tag}")
    print("=" * 52)
    return 0


def main(player_count=None):
    try:
        return _main(player_count)
    except EOFError:
        print("\n[입력 종료(EOF) — 세션을 여기서 중단합니다]")
        return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
