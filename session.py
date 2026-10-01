# -*- coding: utf-8 -*-
"""다빈치 코드 — 게임 세션 (터미널/네트워크 무관).

run_game.py 의 while 루프를 '출력 대상'과 분리한 것.
세션은 게임을 굴리면서, 화면에 뭘 보여줄지/입력을 받을지를
**Output 인터페이스** 에게 위임한다.

Output 인터페이스 (구현체가 채워야 할 메서드)
-------------------------------------------
  show(text)                  모두에게 보이는 출력
  show_me(seat, text)         seat 에게만 보이는 출력 (비밀)
  ask(seat, prompt) -> str    seat 에게 입력 요청, 한 줄 응답
  wait(seat, text)            seat 에게 대기 안내 (선택중...)
  finish(text)                종료

구현체 예:
  - TerminalOutput : 로컬 단일 터미널 (run_local.py)
  - RelayOutput    : 네트워크 소켓 (relay.py)
  - SilentOutput   : 검증용 (출력 버리고 자동응답)

부정행위 방지:
  - 세션은 '좌석(seat) 기준'으로만 비밀을 나눈다. HumanDecider 는
    자기 좌석의 뷰만 보므로 남의 패를 볼 수 없다.
  - CPU 는 prob_ai 로만 결정 (공개 정보 + 자기 패).
"""

import random

import DavinciCode as md
import prob_ai

BLACK_BOX = "\u25a0"
WHITE_BOX = "\u25a1"


def value_set():
    """추측값 후보 전체 ('0b'..'bw' + 조커 'Jb'/'Jw')."""
    vals = {md.Card(v, b).display() for v in range(12) for b in (True, False)}
    vals |= {"Jb", "Jw"}
    return vals


class Output:
    """출력/입력 인터페이스 (추상). 실제 구현은 서브클래스가 채운다."""

    def show(self, text):
        raise NotImplementedError

    def show_me(self, seat, text):
        raise NotImplementedError

    def ask(self, seat, prompt, mode=None, data=None):
        """입력 요청.

        mode/data 는 GUI(웹) 클라이언트가 클릭 UI 를 그리기 위한 힌트다.
        터미널 클라이언트는 prompt 만 쓰면 되므로 무시해도 된다(하위호환).
          mode : 'guess' | 'black_count' | 'joker_slot' | 'joker_side'
                 | 'more_guess' | 'fail_reveal' | None(일반 입력)
          data : 모드별 부가 정보 dict
        """
        raise NotImplementedError

    def wait(self, seat, text):
        raise NotImplementedError

    def is_connected(self, seat):
        """이 좌석이 아직 연결돼 있는가.

        네트워크(relay) 모드에서는 클라이언트 소켓 상태를 보고,
        터미널 모드에서는 항상 True (끊길 개념이 없음).
        기권 판정에 쓰인다.
        """
        return True

    def on_forfeit(self, seat, text):
        """좌석 기권을 알린다 (기본: 모두에게 알림)."""
        self.show(text)

    def update_state(self, seat, state):
        """좌석의 구조화 상태(dict)를 알린다 — GUI 클라이언트용.

        기본 구현은 아무것도 하지 않는다(터미널 모드는 텍스트만 씀).
        RelayOutput 이 이걸 JSON 으로 중계하고, GUI 가 그걸로 화면을 그린다.
        """
        return

    def finish(self, text):
        raise NotImplementedError


# =============================================================================
class _SeatDecider:
    """사람 좌석(seat)의 삽입 결정자. 세션의 Output 을 통해 물어본다.

    ★ 조커 관련 결정(조커 슬롯 / 조커 앞뒤)을 물을 때는
      먼저 '현재 내 패'를 그 좌석에게만 보여준다.
      → 조커가 어디 끼어 있는지 눈으로 확인하고 답할 수 있게.
    """

    def __init__(self, session, seat):
        self.session = session
        self.seat = seat

    def _show_my_line(self, mark=None, slots=False):
        """현재 내 패를 이 좌석에게만 표시.

        mark  : 이 카드에 * 표시 (방금 뽑은 카드 강조)
        slots : True 면 삽입 슬롯 번호를 함께 표시 (조커 슬롯 선택용)
                예) 슬롯0 [2b] 슬롯1 [5w] 슬롯2
        """
        p = self.session.game.players[self.seat]
        if not p.own_cards:
            self.session.io.show_me(self.seat, "   <내 패(현재)> (빈 패)")
            return
        if slots:
            parts = ["슬롯0"]
            for i, c in enumerate(p.own_cards):
                parts.append(f"[{c.display()}]")
                parts.append(f"슬롯{i+1}")
            body = " ".join(parts)
        else:
            parts = []
            for i, c in enumerate(p.own_cards, 1):
                star = "*" if (mark is not None and c is mark) else ""
                parts.append(f"{i}:{c.display()}{star}")
            body = "  ".join(parts)
        self.session.io.show_me(self.seat, f"   <내 패(현재)> {body}")

    def _ask_slot(self, card, M):
        self.session.io.show_me(
            self.seat,
            f"\n★ 조커({card.display()}) 를 뽑았습니다! "
            f"삽입 슬롯을 고르세요 (현재 {M}장).")
        self._show_my_line(slots=True)
        s = self.session._human_ask(
            self.seat,
            f"   슬롯 0~{M} (0=맨앞, n=n번째 뒤, {M}=맨뒤) : ",
            mode="joker_slot",
            data={"slots": M, "joker": card.display(),
                  "cards": [c.display() for c in self.session.game.players[self.seat].own_cards]})
        try:
            i = int(s.strip())
        except (ValueError, AttributeError):
            return 0
        return max(0, min(M, i))

    def select_joker_slot(self, card, M):
        return self._ask_slot(card, M)

    def ask_joker_side(self, display):
        self._show_my_line()
        s = self.session._human_ask(
            self.seat,
            f"   가로막는 조커({display}) — 새 카드를 '앞(왼쪽)=0' / "
            f"'뒤(오른쪽)=1' 중? : ",
            mode="joker_side",
            data={"wall": display,
                  "cards": [c.display() for c in self.session.game.players[self.seat].own_cards]})
        return "front" if str(s).strip().lower() in ("0", "앞", "f", "front") else "back"

    def ask_joker_side_full(self, display, ncard):
        """확장 시그니처 (조커 뒤에 새 숫자 카드가 있는 상황).

        사람에게는 어차피 '앞/뒤'만 물으면 되므로 ncard 는 안내에만 쓴다.
        """
        self._show_my_line(mark=ncard)
        s = self.session._human_ask(
            self.seat,
            f"   가로막는 조커({display}) — 새 카드({ncard.display()}) 를 "
            f"'앞(왼쪽)=0' / '뒤(오른쪽)=1' 중? : ",
            mode="joker_side",
            data={"wall": display, "ncard": ncard.display(),
                  "cards": [c.display() for c in self.session.game.players[self.seat].own_cards]})
        return "front" if str(s).strip().lower() in ("0", "앞", "f", "front") else "back"


# =============================================================================
class Session:
    """한 판의 상태 + 턴 진행. 출력은 전부 io(Output)에게 위임.

    seat(좌석) = players 리스트의 인덱스. 좌석마다 이름이 붙는다.
    """

    def __init__(self, io, player_count, names=None, human_seats=None,
                 rng=None, delay=0.0):
        """
        io          : Output 구현체
        player_count: 2~4
        names       : 좌석별 이름 리스트 (없으면 자동)
        human_seats : 사람이 앉은 좌석 집합. None이면 전부 사람.
                      CPU 좌석은 prob_ai 가 플레이한다.
        """
        self.io = io
        self.rng = rng or random.Random()
        self.delay = delay
        self.game = md.Game(player_count)
        self.n = player_count

        # 이름/사람여부 배정
        if human_seats is None:
            human_seats = set(range(player_count))
        self.human_seats = set(human_seats)
        if names is None:
            # 사람 좌석은 'P숫자', CPU 좌석은 'CPU숫자' (CPU 번호는 1부터 순차)
            names = []
            cpu_no = 0
            for i in range(player_count):
                if i in self.human_seats:
                    names.append(f"P{i+1}")
                else:
                    cpu_no += 1
                    names.append(f"CPU{cpu_no}")

        for i, p in enumerate(self.game.players):
            p.name = names[i]
            p.is_human = (i in self.human_seats)

        self.elim_rank = {}
        self.next_rank = player_count
        self.used_names = set()

    # ---------------- 표시 헬퍼 ----------------
    def _cell(self, card, show_value, star=False):
        s = card.display() if show_value else (
            BLACK_BOX if card.is_black else WHITE_BOX)
        return s + ("*" if star else "")

    def _line_of(self, viewer, owner, drawn=None):
        out = []
        for i, c in enumerate(owner.own_cards, 1):
            show = (c in owner.revealed_cards) or (owner is viewer)
            star = (owner is viewer and drawn is not None and c is drawn)
            out.append(f"{i}:{self._cell(c, show, star)}")
        return "  ".join(out)

    # 공개 목록 한 줄에 넣을 카드 수 — 넘어가면 줄바꿈한다.
    PUBLIC_PER_LINE = 13

    def _public_lines(self, indent="   "):
        """지금까지 공개된 카드를 줄바꿈해 만든 줄 목록 (없으면 빈 리스트).

        13개(PUBLIC_PER_LINE)까지는 한 줄, 그 이상이면 이어지는 줄은
        들여쓰기만 맞춰 정렬한다.
        """
        pubs = self.game.table.public
        if not pubs:
            return []
        names = [c.display() for c in pubs]
        head = indent + "[공개] "
        cont = " " * len(head)
        lines = []
        cur = head
        for i, nm in enumerate(names):
            piece = nm + ("" if i == len(names) - 1 else ", ")
            if i and i % self.PUBLIC_PER_LINE == 0:
                lines.append(cur.rstrip())
                cur = cont + piece
            else:
                cur += piece
        lines.append(cur.rstrip())
        return lines

    def _show_public(self):
        lines = self._public_lines()
        if lines:
            self.io.show("\n" + "\n".join(lines))
        # 공개 카드가 바뀌었으니 GUI 상태도 전원 갱신한다.
        self._push_state_all()

    def _human_ask(self, seat, prompt, mode=None, data=None):
        """사람 좌석 입력 요청 — ★ ask 전에 상태를 한 번 밀어 GUI 클릭 UI 를 띄운다.

        ask() 는 응답이 올 때까지 블록되므로, 그 전에 이 좌석의 상태
        (ask.mode/data 포함)를 발행하지 않으면 브라우저가 '입력 중'을 모른다.
        """
        self.io.update_state(
            seat, self._state_dict(seat, pending_ask=(mode, data, prompt)))
        return self.io.ask(seat, prompt, mode=mode, data=data)

    def _push_state_all(self, waiting_name="__auto__"):
        """사람 좌석 전원에게 구조화 상태를 발행 (GUI 갱신용).

        ★ 터미널 클라이언트는 STATE 를 모르고 WAIT(텍스트 대기/관전 화면)만 안다.
          그래서 waiting_name 이 있는 '남의 턴' 상황이면 텍스트 대기 화면도
          함께 보낸다. (GUI 는 STATE 로만 그리고 WAIT 는 무시한다.)
          이게 없으면 턴이 넘어가도 터미널 화면이 갱신되지 않고,
          탈락자(관전자)는 진행 상황을 아예 못 받는다.

        waiting_name :
          "__auto__" (기본) — 현재 턴 주인 이름을 자동으로 쓴다.
                              인자 없이 부른 곳(_show_public 등)에서도
                              대기/관전 화면이 나가게 한다.
          None              — 대기 화면을 보내지 않는다(내 턴 화면).
          "<이름>"          — 그 사람이 턴 주인이라고 알린다.
        """
        if waiting_name == "__auto__":
            cur = self.game.current_player()
            waiting_name = cur.name if cur is not None else None
        cur = self.game.current_player()
        for i in range(self.n):
            p = self.game.players[i]
            if not p.is_human:
                continue
            self.io.update_state(
                i, self._state_dict(i, waiting_name=waiting_name))
            # 남의 턴 → 이 좌석은 기다린다(탈락자는 관전 화면).
            # ★ 좌석으로 비교한다(이름 중복에 영향받지 않게).
            # ★ 탈락자는 자기 턴이 될 수 없으므로 항상 '기다리는' 화면을 받는다.
            is_my_turn = (cur is p) and not p.is_eliminated()
            if waiting_name is not None and not is_my_turn:
                txt = self._board_text(i, None, False, waiting_name=waiting_name)
                self.io.wait(i, txt)

    def guess_pause(self):
        """추리 페이즈가 끝나는 지점(정답/오답 직후)의 여유.

        결과 문구 → [공개] 목록까지 눈으로 확인할 시간을 준다.
        RESULT_DELAY 와 무관하게 GUESS_DELAY 만 쓴다(중복 지연 방지).
        GUESS_DELAY=0(자동검증)이면 즉시 진행.
        """
        if self.delay:
            import time
            time.sleep(self.delay)

    def _result_show(self, text):
        """추리 결과 문구를 앞뒤 빈 줄과 함께 모두에게 표시.

        입력 프롬프트에 답이 붙어 보이는 것을 막고,
        결과 문구가 눈에 띄게 한다. (예)
            >> 추측: ... : 3 2 1b
                                       ← 빈 줄
              ✔ 정답! ...
                                       ← 빈 줄
              [공개] ...
        """
        self.io.show("\n" + text)

    def _board_text(self, viewer_seat, drawn, just_drew, waiting_name=None):
        """특정 좌석 시점의 화면 텍스트 (다중 줄).

        waiting_name 이 주어지면 '대기 화면' 모드: 턴 주인은 남이고,
        이 좌석은 자기 패/상대 상황을 다시 확인하며 기다린다.

        ★ viewer 가 탈락자면 '관전 화면' 모드: 자기 패가 없으므로 생존자
          현황만 보여준다. 남의 비밀 정보는 그대로 ■/□ 로 가려진다.
        """
        game = self.game
        viewer = game.players[viewer_seat]
        spectating = viewer.is_eliminated()
        lines = []
        if waiting_name is None:
            lines.append(f"──── 턴(라운드 {game.round_number}) · 차례: {viewer.name} ────")
            lines.append(f"   공용 덱 {len(game.table.deck)}장"
                         + (" · 뽑은 카드를 배치했습니다" if just_drew else ""))
        else:
            tag = " (관전)" if spectating else ""
            lines.append(f"──── 라운드 {game.round_number} · "
                         f"지금 {waiting_name} 님의 차례입니다{tag} ────")
            lines.append(f"   공용 덱 {len(game.table.deck)}장 · "
                         + ("남은 대국을 지켜보는 중입니다" if spectating
                            else "상대를 기다리는 중입니다"))
        lines.append("")
        lines.append("----- 생존자 현황 -----" if spectating else "----- 상대 패 -----")
        any_opp = False
        losers = []
        for i, p in enumerate(game.players):
            if p is viewer:
                continue
            if p.is_eliminated():
                # ★ 패배자도 목록에 남긴다 — 손패가 전부 공개된 채로 보여야
                #   남은 사람들이 추리 재료로 쓸 수 있다.
                losers.append((i, p))
                continue
            any_opp = True
            hidden = sum(1 for c in p.own_cards if c not in p.revealed_cards)
            lines.append(f"  [#{i+1}] {p.name}  (비밀 {hidden} · 공개 {len(p.revealed_cards)})")
            lines.append("      " + self._line_of(viewer, p))
        if not any_opp:
            lines.append("   (남은 상대 없음)")
        for i, p in losers:
            lines.append(f"  [#{i+1}] {p.name}  (패배 — 손패 전부 공개)")
            lines.append("      " + self._line_of(viewer, p))
        lines.append("")
        if spectating:
            # 탈락자는 자기 패가 없다 — 자리만 남긴다.
            lines.append("----- 내 패 -----")
            lines.append("      (탈락 — 관전 중)")
        else:
            if waiting_name is None:
                lines.append("----- 내 패 (값 전부 보임, * = 방금 뽑은 카드) -----")
            else:
                lines.append("----- 내 패 (값 전부 보임) -----")
            lines.append("      " + self._line_of(viewer, viewer, drawn))

        # 지금까지 공개된 카드 요약도 함께 (추리 재료)
        #  — 내 턴 화면/대기 화면 **둘 다** 필요하다. 내가 추리할 때도
        #    공개 목록이 보여야 하고, 기다릴 때도 있어야 한다.
        #  (13개를 넘으면 자동 줄바꿈 — _public_lines 재사용)
        pub_lines = self._public_lines()
        if pub_lines:
            lines.append("")
            lines.extend(pub_lines)
        return "\n".join(lines)

    # ---------------- 구조화 상태 (GUI 용) ----------------
    def _state_dict(self, viewer_seat, drawn=None, waiting_name=None,
                    pending_ask=None):
        """GUI 가 그림을 그릴 수 있게 상태를 dict 로 뽑는다.

        ★ _board_text 와 **같은 정보원**을 쓴다(둘이 어긋나지 않게).
        비밀 정보 규칙도 동일: 남의 패는 공개된 카드만 값이 실리고,
        나머지는 색(is_black)만 실린다.

        pending_ask : (mode, data, prompt) — 이 좌석이 지금 입력 대기 중이면
                      그 정보를 상태에 실어 보낸다(클릭 UI 용).
        """
        game = self.game
        viewer = game.players[viewer_seat]
        spectating = viewer.is_eliminated()

        def card_entry(card, owner, is_viewer):
            """카드 한 장 → dict. 값은 (내 패 or 공개됨)일 때만 싣는다."""
            open_ = is_viewer or (card in owner.revealed_cards)
            return {
                "value": card.display() if open_ else None,
                "is_black": bool(card.is_black),
                # ★ 조커 여부도 '볼 수 있는 카드'에만 싣는다.
                #   안 그러면 남의 비밀 조커에 노란 테두리가 붙어 정체가 새어나간다.
                "is_joker": bool(card.is_joker) if open_ else False,
                "revealed": bool(card in owner.revealed_cards),
                "star": bool(is_viewer and drawn is not None and card is drawn),
            }

        players = []
        for i, p in enumerate(game.players):
            is_me = (i == viewer_seat)
            players.append({
                "seat": i,
                "name": p.name,
                "is_human": bool(p.is_human),
                "is_me": is_me,
                "is_eliminated": bool(p.is_eliminated()),
                "forfeited": bool(getattr(p, "forfeited", False)),
                "hidden_count": sum(1 for c in p.own_cards
                                    if c not in p.revealed_cards),
                "revealed_count": len(p.revealed_cards),
                "cards": [card_entry(c, p, is_me) for c in p.own_cards],
            })

        # ★ 클릭 UI 힌트: 지금 이 좌석이 '추측' 입력 중이면
        #   지목 가능한 (상대좌석, 자리) 목록과, 고를 수 있는 값 목록을 실어준다.
        targets = []
        if pending_ask and pending_ask[0] == "guess":
            for oi, opp in enumerate(game.players):
                if oi == viewer_seat or opp.is_eliminated():
                    continue
                for pos, c in enumerate(opp.own_cards, 1):
                    if c in opp.revealed_cards:
                        continue          # 이미 공개된 자리는 지목 불가
                    targets.append({"seat": oi, "pos": pos,
                                    "is_black": bool(c.is_black)})
        values = []
        if pending_ask and pending_ask[0] == "guess":
            # 지목 가능한 값 = '내 패에 없는 값' - '이미 공개된 패 값'
            #   ★ 공개된 카드는 아무도 지목할 수 없다(테이블에서 보이는 패).
            #     공개 정보가 쌓일수록 후보가 줄어야 추리 게임이 성립한다.
            unavailable = set(viewer.own_value_specs())
            unavailable |= {c.display() for c in game.table.public}
            values = sorted(value_set() - unavailable)

        ask_obj = None
        if pending_ask:
            mode, data_, prompt = pending_ask
            ask_obj = {"mode": mode, "prompt": prompt}
            if data_ is not None:
                ask_obj["data"] = data_
            if mode == "guess":
                ask_obj["targets"] = targets
                ask_obj["values"] = values

        return {
            "round": game.round_number,
            "deck": len(game.table.deck),
            "viewer": viewer_seat,
            "waiting_name": waiting_name,      # None 이면 내 턴
            "spectating": bool(spectating),
            "players": players,
            "public": [c.display() for c in game.table.public],
            "ranking": {str(k): v for k, v in self.elim_rank.items()},
            "ask": ask_obj,
        }

    # ---------------- 입력 검증 ----------------
    def _parse_guess(self, seat, raw):
        """입력 한 줄 → (tidx, pos, val) or None(멈춤) or ('ERR', 이유).

        검증은 서버(세션)에서 한다. 클라이언트는 문자열만 올려보낸다.
        """
        game = self.game
        s = (raw or "").strip()
        low = s.lower()
        # 멈춤은 'q' 계열만. 빈 Enter 는 실수일 수 있으므로 재질문한다.
        if low in ("q", "quit", "그만", "종료"):
            return None
        if not s:
            return ("ERR", "빈 입력입니다. 추측하거나 q(멈춤)를 입력하세요.")
        parts = s.split()
        if len(parts) != 3:
            return ("ERR", "3개 항목을 띄어 쓰세요. 예: 2 3 Jb")
        num, pos, val = parts
        if not num.isdigit() or not (1 <= int(num) <= self.n):
            return ("ERR", f"상대번호는 1~{self.n} 범위.")
        tidx = int(num) - 1
        if tidx == seat:
            return ("ERR", "자기 자신은 지목 불가.")
        tgt = game.players[tidx]
        if tgt.is_eliminated():
            return ("ERR", f"{tgt.name} 는 이미 탈락.")
        if not pos.isdigit() or int(pos) < 1:
            return ("ERR", "자리번호는 1 이상 정수.")
        p = int(pos)
        if p > len(tgt.own_cards):
            return ("ERR", f"{tgt.name} 는 자리가 {len(tgt.own_cards)} 개입니다.")
        if tgt.card_at_pos(p) in tgt.revealed_cards:
            return ("ERR", "그 자리는 이미 공개되었습니다. 다신 선택해주세요.")
        raw_val = val.strip().lower()
        if raw_val[:1] == "j":
            raw_val = "J" + raw_val[1:]
        if raw_val not in value_set():
            return ("ERR", "값 형식 오류 (예 3b·aw·Jb·Jw).")
        # 규칙: 지목값은 '내 패에 없는 값'
        if raw_val in game.players[seat].own_value_specs():
            return ("ERR", f"지목 불가: {raw_val} 는 내 패에 있는 값입니다. "
                           f"'내 패에 없는 값'만 지목할 수 있습니다.")
        # 규칙: 이미 공개된 카드 값은 지목 불가 (테이블에서 보이는 패)
        if raw_val in {c.display() for c in game.table.public}:
            return ("ERR", f"지목 불가: {raw_val} 는 이미 공개된 값입니다.")
        return (tidx, p, raw_val)

    # ---------------- 게임 진행 ----------------
    def run(self):
        # (1) 사람 좌석 이름 등록 + 검은 카드 수 결정 + 분배
        self.io.show("=" * 52)
        self.io.show("   다빈치 코드 (Davinci Code) — 멀티플레이")
        self.io.show(f"   인원 {self.n}")
        self.io.show("=" * 52)

        per = self.game.per
        for i, p in enumerate(self.game.players):
            if p.is_human:
                # ★ 재질문 상한 10회 — 잘못된 입력이 계속 들어와도 멈추지 않게.
                #   (초과 시 기본값 0장으로 진행)
                for _ in range(10):
                    s = self._human_ask(i, f"받을 '검은 카드' 수 (0~{per}) : ",
                                        mode="black_count", data={"max": per})
                    if s.strip().isdigit() and 0 <= int(s) <= per:
                        p.black_deal_count = int(s)
                        break
                    self.io.show_me(i, f"   [!] 0~{per} 사이 정수 입력.")
                else:
                    p.black_deal_count = 0
                    self.io.show_me(i, "   [!] 입력 실패 — 기본값 0장으로 진행합니다.")
            else:
                p.black_deal_count = self.rng.randint(0, per)
        self.game.deal()
        for p in self.game.players:
            p.sort_hand()

        # (2) 자기 시작 패 안내 (개인 전용)
        for i, p in enumerate(self.game.players):
            lines = ["", "---- 내 시작 패 (값 다 보임) ----"]
            for j, c in enumerate(p.own_cards, 1):
                tag = BLACK_BOX if c.is_black else WHITE_BOX
                lines.append(f"  자리{j}: {c.display()}  ({tag})")
            self.io.show_me(i, "\n".join(lines))
        # ★ 분배 직후 첫 상태를 보낸다 — GUI(웹)가 시작 패를 그릴 수 있게.
        #   (이게 없으면 검은 카드 수 단계 동안 화면이 비어 있다.)
        self._push_state_all()
        self.io.show(f"---- 분배 완료 · 공용 덱 {len(self.game.table.deck)}장 ----")

        def sweep():
            for i2, pp in enumerate(self.game.players):
                if i2 not in self.elim_rank and pp.is_eliminated():
                    self.elim_rank[i2] = self.next_rank
                    if getattr(pp, "forfeited", False):
                        self.io.show(f"★ {pp.name} 기권(연결 끊김) → {self.next_rank}등 확정")
                    else:
                        self.io.show(f"★ {pp.name} 탈락 → {self.next_rank}등 확정")
                    self.next_rank -= 1

        def alive():
            return [i for i, p in enumerate(self.game.players) if not p.is_eliminated()]

        def forfeit(seat, reason):
            """좌석 기권 처리 — 모든 패를 공개하고 순위를 확정한다.

            기권자의 패는 전부 공개된다(다른 사람의 추리 대상에서 제외).
            Returns: 처리했으면 True.
            """
            pp = self.game.players[seat]
            if pp.is_eliminated():
                return False
            pp.forfeited = True
            # ★ 모든 패 공개: 남은 비공개 카드를 전부 revealed 로.
            for c in pp.own_cards:
                pp.reveal(c)
                if c not in self.game.table.public:
                    self.game.table.public.append(c)
            self.io.on_forfeit(seat, reason)
            self.io.show(f"   ↳ {pp.name} 님의 모든 패를 공개합니다: "
                    + ", ".join(c.display() for c in pp.own_cards))
            sweep()
            return True

        def check_forfeit():
            """미탈락 좌석 중 연결이 끊긴 곳을 기권 처리한다.

            Returns: 기권이 발생했으면 True.
            """
            changed = False
            for i2, pp in enumerate(self.game.players):
                if pp.is_eliminated():
                    continue
                if not self.io.is_connected(i2):
                    forfeit(i2, f"⚠ {pp.name} 님의 연결이 끊겼습니다 "
                                f"— 기권 처리합니다.")
                    changed = True
            return changed

        self.game.start_first_turn()
        sweep()

        guard = 0
        prev_round = None
        while len(alive()) > 1 and guard < 4000:
            guard += 1
            # ★ 턴을 받기 전에 미탈락 플레이어의 연결을 확인한다.
            #   끊긴 사람은 기권패 처리(순위 확정) 후, 턴 주인이 바뀌었으면
            #   그 턴은 건너뛴다.
            before_turn = self.game.turn_index
            check_forfeit()
            if len(alive()) <= 1:
                break
            if self.game.turn_index != before_turn or self.game.players[self.game.turn_index].is_eliminated():
                # 기권으로 턴 주인이 탈락 → 다음 살아있는 사람으로 넘긴다
                self.game.turn_index = before_turn
                self.game.next_turn()
                continue
            cur_seat = self.game.turn_index
            cur = self.game.players[cur_seat]

            if prev_round is None or self.game.round_number != prev_round:
                if prev_round is not None:
                    self.io.show(f"\n  ═══ 라운드 {self.game.round_number} 시작 ═══")
                prev_round = self.game.round_number

            if cur.is_human:
                self.io.show(f"  ⇒ {cur.name} 님 턴 차례입니다.")

            # (3) 의무 뽑기 + 삽입
            drew = None
            if self.game.table.deck:
                if cur.is_human:
                    dec = _SeatDecider(self, cur_seat)
                else:
                    dec = prob_ai.StrategicDecider(self.rng)
                    if hasattr(dec, "bind_player"):
                        dec.bind_player(cur)
                drew = self.game.draw_and_insert(cur, dec)

            # (4) 턴 화면 — 자기 시점 board 는 본인에게만, 남들에겐 진행 안내
            if cur.is_human:
                self.io.show_me(cur_seat, "\n" + self._board_text(cur_seat, drew, drew is not None))
                self.io.update_state(
                    cur_seat,
                    self._state_dict(cur_seat, drawn=drew))
                # ★ 다른 사람 좌석들: 남의 차례를 기다리며 자기 패를 다시 본다.
                #   (네트워크 모드에서 '선택중'만 보이면 추리를 못 하므로,
                #    대기 화면에 자기 패 + 상대 현황 + 공개 목록을 함께 준다)
                for i in range(self.n):
                    if i == cur_seat:
                        continue
                    p = self.game.players[i]
                    if not p.is_human:
                        continue        # CPU 좌석은 화면이 필요 없다
                    # 사람 좌석: 생존자 대기 화면 / 탈락자 관전 화면 모두 동일 경로
                    self.io.wait(i, "\n" + self._board_text(
                        i, None, False, waiting_name=cur.name))
                    self.io.update_state(
                        i, self._state_dict(i, waiting_name=cur.name))
            else:
                head = (f"[{cur.name}의 턴] 라운드 {self.game.round_number} · "
                        f"덱 {len(self.game.table.deck)}장 · (카드 1장을 뽑아 배치함)")
                # CPU 차례: 사람 좌석에는 대기 화면(자기 패 + 상대 현황)을,
                # 나머지(CPU)에는 간단 안내를 보낸다.
                for i in range(self.n):
                    p = self.game.players[i]
                    if not p.is_human:
                        # CPU 좌석 — 탈락/생존 모두 간단 안내(관전 화면 불필요)
                        if not p.is_eliminated():
                            self.io.show_me(i, "\n" + head)
                        continue
                    # 사람 좌석: 생존자 대기 화면 / 탈락자 관전 화면 모두 동일 경로
                    self.io.wait(i, "\n" + self._board_text(
                        i, None, False, waiting_name=cur.name))
                    self.io.update_state(
                        i, self._state_dict(i, waiting_name=cur.name))
            # 공개 카드 알림은 '추측 결과 직후'에만 뿌린다.
            # (턴 화면의 대기 모드에 이미 [공개] 목록이 실려 있고,
            #  여기서 또 뿌리면 직전 결과의 [공개]와 붙어 2연속 중복이 된다.)

            # (5) 추측 반복
            keep = True
            while keep and len(alive()) > 1:
                cur_seat = self.game.turn_index
                cur_p = self.game.players[cur_seat]
                opps = [(i, p) for i, p in enumerate(self.game.players)
                        if i != cur_seat and not p.is_eliminated()]
                if not opps:
                    break

                if cur_p.is_human:
                    g = self._human_guess(cur_seat)
                    if g is None:
                        # ★ 입력 도중 연결이 끊겼으면 기권 처리
                        if not self.io.is_connected(cur_seat):
                            forfeit(cur_seat,
                                    f"⚠ {cur_p.name} 님의 연결이 끊겼습니다 "
                                    f"— 기권 처리합니다.")
                        break
                    tidx, pos, val = g
                    tgt = self.game.players[tidx]
                else:
                    cand = prob_ai.prob_guess_for(self.game, cur_seat, rng=self.rng)
                    if cand is None:
                        break
                    tidx, pos, val = cand
                    tgt = self.game.players[tidx]

                actual = tgt.card_at_pos(pos)
                hit = (actual is not None and actual.display() == val)
                prob_ai.broadcast_claim(self.game, cur_seat, val)
                guess_txt = f"(#{tidx+1} {tgt.name}의 패) 자리 {pos} = {val}"

                if hit:
                    rc = tgt.reveal_attacked(pos)
                    if rc is not None and rc not in self.game.table.public:
                        self.game.table.public.append(rc)
                    self._result_show(f"✔ 정답! {cur_p.name} 가 {guess_txt} 추측 → {val} 공개.")
                    self._show_public()
                    sweep()
                    self.guess_pause()      # 추리 결과 읽을 여유
                    if len(alive()) <= 1:
                        break
                    if cur_p.is_human:
                        ans = self._human_ask(cur_seat, "\n연속 지목? (Enter=계속 / q=그만) : ",
                                              mode="more_guess")
                        # ★ 응답 없이 끊겼으면 기권 처리
                        if not self.io.is_connected(cur_seat):
                            forfeit(cur_seat,
                                    f"⚠ {cur_p.name} 님의 연결이 끊겼습니다 "
                                    f"— 기권 처리합니다.")
                            keep = False
                        elif str(ans).strip().lower() in ("q", "quit", "그만", "종료"):
                            keep = False
                    else:
                        cont, _info = prob_ai.continue_decision(self.game, cur_seat, rng=self.rng)
                        if not cont:
                            keep = False
                else:
                    if not cur_p.is_human:
                        prob_ai.remember_failure(self.game, cur_seat, (tidx, pos, val))
                    if drew is not None and drew not in cur_p.revealed_cards:
                        cur_p.reveal(drew)
                        if drew not in self.game.table.public:
                            self.game.table.public.append(drew)
                        self._result_show(f"✘ 오답! {cur_p.name} 의 추측({guess_txt}) "
                                          f"— 벌칙: 방금 뽑은 {drew.display()} 카드 공개.")
                    else:
                        # ★ 덱이 소진됐을 때: '내 패 중 공개할 자리'를 직접 고른다.
                        #   (CPU 는 자동, 사람은 물어본다)
                        if cur_p.is_human:
                            hpos = self._ask_fail_reveal_pos(cur_seat)
                        else:
                            hpos = None
                        if hpos is not None:
                            pen = cur_p.own_cards[hpos - 1]
                            cur_p.reveal(pen)
                        else:
                            pen = cur_p.reveal_failed(None)
                        if pen is not None and pen not in self.game.table.public:
                            self.game.table.public.append(pen)
                        # ★ '자리 N' 대신 실제 값이 보이게 (어느 카드가 공개됐는지 바로 알 수 있게)
                        loc = f"자리 {hpos}({pen.display()})" if pen is not None else "-"
                        self._result_show(f"✘ 오답! {cur_p.name} 의 추측({guess_txt}) "
                                          f"— 벌칙 공개: {loc}")
                    self._show_public()
                    sweep()
                    self.guess_pause()      # 추리 결과 읽을 여유
                    keep = False
            # end 추측 루프

            if len(alive()) <= 1:
                break
            # ★ 턴이 끝나면 전원에게 STATE 를 발행한다.
            #   안 하면 '연속 지목? (계속/그만)' 같은 버튼이 내 화면에 남는다.
            #   (다음 사람 턴에는 내 좌석에 STATE 가 안 가므로 버튼이 안 사라졌다.)
            self.game.next_turn()
            nxt = self.game.current_player()
            self._push_state_all(waiting_name=nxt.name if nxt else None)
        # end 전체 루프

        # (6) 종료 정산
        surv = alive()
        final = dict(self.elim_rank)
        lines = ["", "=" * 52]
        if len(surv) == 1:
            final[surv[0]] = 1
            lines.append(f"🏆 1등 : {self.game.players[surv[0]].name}")
        else:
            lines.append("게임이 정상 종료되지 못함 (승자 없음).")
        lines.append("  최종 순위:")
        for i2, p in enumerate(self.game.players):
            r = final.get(i2)
            if r:
                lines.append(f"    {r}등  {p.name}")
        # ★ 우승자까지 elim_rank 에 반영하고 STATE 를 한 번 더 보낸다.
        #   (elim_rank 는 탈락자만 채우므로 1등이 빠져 있었다 → 웹 순위표가 불완전.)
        self.elim_rank = {k: v for k, v in final.items()}
        self._push_state_all()
        self.io.finish("\n".join(lines))

    def _human_guess(self, seat):
        """사람 좌석 입력 루프 (검증 실패 시 재질문).

        ★ 재질문 횟수 상한: 잘못된 입력이 계속 들어와도 게임이 멈추면 안 된다.
          10회 실패하면 이번 턴 추측을 포기(멈춤)하고 턴을 넘긴다.
          (사람 오타 방지용 — 3번까지는 실수할 수 있으니 10회. 정상 입력이면 1회에 통과.)
        """
        io = self.io
        for _ in range(10):
            raw = self._human_ask(seat, ">> 추측: [#] [자리] [값(3b/aw/Jb/Jw)]  q=멈춤 : ",
                                  mode="guess")
            r = self._parse_guess(seat, raw)
            if r is None:
                return None
            if isinstance(r, tuple) and r and r[0] == "ERR":
                io.show_me(seat, f"   [!] {r[1]}")
                continue
            return r
        io.show_me(seat, "   [!] 입력 실패가 계속되어 이번 턴은 넘어갑니다.")
        return None

    def _ask_fail_reveal_pos(self, seat):
        """(덱 소진 시 오답 벌칙) 내 패 중 '공개할 자리'를 골라 받는다.

        덱이 남아 있으면 '방금 뽑은 카드'가 자동 공개되지만,
        덱이 비면 내 패 중 하나가 공개돼야 하므로 **본인이 고른다**.

        Returns: 1부터의 자리번호 or None(미공개 패 없음 → reveal_failed 로 위임)
        """
        io = self.io
        p = self.game.players[seat]
        hidden = [i for i, c in enumerate(p.own_cards, 1)
                  if c not in p.revealed_cards]
        if not hidden:
            return None
        # 후보를 눈으로 확인하고 고르게 한다.
        parts = []
        for i, c in enumerate(p.own_cards, 1):
            mark = "*" if i in hidden else " "
            parts.append(f"{i}:{c.display()}{mark}")
        io.show_me(seat, "\n   <내 패> " + "  ".join(parts)
                   + "   (* = 아직 비공개)")
        io.show(("\n★ %s 님, 벌칙으로 공개할 카드를 고릅니다." % p.name))
        # ★ 버튼 라벨에 '자리 3 · 2b' 처럼 실제 값을 함께 보여준다.
        vals = [p.own_cards[i - 1].display() for i in hidden]
        data = {"hidden": hidden, "values": vals}
        for _ in range(10):
            s = self._human_ask(seat, f"\n   공개할 자리 {hidden} 중 1 : ",
                                mode="fail_reveal", data=data)
            if str(s).strip().isdigit() and int(s) in hidden:
                return int(s)
            io.show_me(seat, f"   [!] {hidden} 안에서 고르세요.")
        # 10회 실패 시 자동으로 첫 비공개 카드
        io.show_me(seat, f"   [!] 입력 실패 — {hidden[0]}번으로 공개합니다.")
        return hidden[0]


# =============================================================================
class SilentOutput(Output):
    """검증용: 출력 버리고 사람 자리도 자동응답."""

    def __init__(self, bot_guess_fn=None):
        self.log = []
        self.bot_guess_fn = bot_guess_fn

    def show(self, text):
        self.log.append(("SHOW", text))

    def show_me(self, seat, text):
        self.log.append((f"SHOWME#{seat}", text))

    def ask(self, seat, prompt, mode=None, data=None):
        self.log.append((f"ASK#{seat}", prompt))
        if "추측" in prompt:
            return "q"          # 기본: 멈춤
        if "검은 카드" in prompt:
            return "1"
        if "공개할 자리" in prompt:
            return "1"          # 자리 1 (없으면 재질문/자동선택으로 흘러감)
        return "0"

    def wait(self, seat, text):
        self.log.append((f"WAIT#{seat}", text))

    def finish(self, text):
        self.log.append(("END", text))
