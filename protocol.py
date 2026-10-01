# -*- coding: utf-8 -*-
"""다빈치 코드 멀티플레이 — 통신 프로토콜 정의.

서버(relay.py)와 클라이언트(client.py)가 공유하는 '계약서'.
메시지는 전부 **한 줄 = 한 메시지** 로 주고받는다(줄바꿈이 구분자).

전송 형식
---------
  <TYPE> <payload>\\n

  TYPE 은 4~6글자 대문자 토큰, payload 는 나머지 한 줄 전체.
  payload 안의 줄바꿈은 인코딩해서 없앤다(_escape 참고).

메시지 종류 (서버 → 클라이언트)
-------------------------------
  HELLO <좌석번호> <이름>     접속 직후, "너는 N번 좌석이다"
  SHOW  <텍스트>              **모두에게** 보이는 공통 출력
  SHOWME <텍스트>             **너에게만** 보이는 비밀 출력 (네 패 = 실제 값)
  ASK   <프롬프트>            **너에게만** 오는 입력 요청 → REPLY 로 답한다
  WAIT  <텍스트>              남이 선택 중. 이 클라이언트는 대기 화면
  STATE <JSON>                구조화된 게임 상태 (GUI 클라이언트용)
  END   <텍스트>              게임 종료. 출력 후 연결 닫힘

메시지 종류 (클라이언트 → 서버)
-------------------------------
  REPLY <한 줄 입력>          ASK 에 대한 응답
  BYE                          자발적 퇴장

설계 원칙
---------
  1) 서버가 진실의 원천 — 게임 상태는 서버만 보유. 클라이언트는 멍청한 터미널.
  2) 입력 검증은 서버 — 클라이언트는 문자열을 그대로 올려보내기만 한다.
     (재질문도 서버가 ASK 를 다시 보내는 방식으로 처리)
  3) 비밀은 SHOWME/ASK 로만 — SHOW 는 모든 좌석이 동일하게 본다.
"""

import socket

# ---------------- 메시지 타입 ----------------
# 서버 → 클라이언트
HELLO = "HELLO"     # 접속 승인, 좌석 배정
SHOW = "SHOW"       # 모두 공통 출력
SHOWME = "SHOWME"   # 개인 전용 출력 (비밀)
ASK = "ASK"         # 개인 전용 입력 요청
WAIT = "WAIT"       # 대기 안내
STATE = "STATE"     # 구조화된 게임 상태 (JSON, GUI 전용)
END = "END"         # 종료
RESTARTED = "RESTARTED"  # ★ 게임 종료 후 '다시하기' — 전원 동의 현황 브로드캐스트

# 클라이언트 → 서버
REPLY = "REPLY"     # ASK 응답
CHAT = "CHAT"       # 자유 채팅 (게임 입력과 무관 — 모든 사람에게 브로드캐스트)
PING = "PING"       # ★ 생존 신호 (web_server → relay). 브라우저가 폴링을 멈추면
                    #   web_server 가 PING 을 보내지 않아 relay 가 '끊김'으로 판단한다.
RESTART = "RESTART"  # ★ '다시하기' 투표 (게임이 끝난 뒤에만 유효).
                     #   전원이 누르면 같은 구성원으로 새 게임을 시작한다.
                     #   큐를 거치지 않고 릴레이가 직접 집계한다 (PING 과 같은 취급).
BYE = "BYE"         # 퇴장

ALL_TYPES = {HELLO, SHOW, SHOWME, ASK, WAIT, STATE, END, RESTARTED,
             REPLY, CHAT, PING, RESTART, BYE}

# 줄바꿈/제어문자 이스케이프 (한 줄 = 한 메시지 규칙 유지용)
_ESC = {"\\": "\\\\", "\n": "\\n", "\r": "\\r"}
_UNESC = {"\\\\": "\\", "\\n": "\n", "\\r": "\r"}


def _escape(text):
    """payload 안의 줄바꿈을 이스케이프해 '한 줄'로 만든다."""
    out = []
    for ch in text:
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _unescape(text):
    """_escape 의 역변환."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            pair = text[i:i + 2]
            if pair in _UNESC:
                out.append(_UNESC[pair])
                i += 2
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def encode(mtype, payload=""):
    """(타입, 텍스트) → 전송용 한 줄(bytes).

    payload 가 여러 줄이어도 안전하게 이스케이프된다.
    """
    if mtype not in ALL_TYPES:
        raise ValueError(f"알 수 없는 메시지 타입: {mtype}")
    if not payload:
        return (mtype + "\n").encode("utf-8")
    return (mtype + " " + _escape(payload) + "\n").encode("utf-8")


def decode(raw_line):
    """전송용 한 줄(bytes/str) → (타입, 텍스트).

    알 수 없는 타입이면 (None, 원문) 을 돌려준다 (무시용).
    """
    if isinstance(raw_line, bytes):
        try:
            raw_line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            raw_line = raw_line.decode("utf-8", "replace")
    line = raw_line.rstrip("\r\n")
    if not line:
        return None, ""
    if " " in line:
        head, rest = line.split(" ", 1)
    else:
        head, rest = line, ""
    if head not in ALL_TYPES:
        return None, line
    return head, _unescape(rest)


def recv_message(sock_file):
    """파일객체(sock.makefile('rb')) 에서 메시지 한 개 읽기.

    ★ 빈 줄(\n 만 있는 줄)은 건너뛰고 다음 메시지를 읽는다.
      — 빈 줄을 '연결 종료'로 오판하면 게임 중 연결이 끊긴 것처럼 보인다.
    ★ 소켓 타임아웃(socket.timeout)은 EOF 가 아니다 — 계속 읽는다.
      — 소켓에 timeout 이 남아 있으면 정상 대기 중에도 예외가 나는데,
        그걸 EOF 로 처리하면 주기적으로 '연결 끊김'이 된다.
    Returns: (타입, 텍스트) or (None, None)  ← 연결 종료(EOF)
    """
    while True:
        try:
            raw = sock_file.readline()
        except socket.timeout:
            continue            # 타임아웃 — 연결은 살아있다
        except (OSError, ValueError):
            return None, None   # 소켓 파손/종료
        if not raw:
            return None, None   # 진짜 EOF
        mtype, payload = decode(raw)
        if mtype is None and not payload:
            continue        # 빈 줄 — 무시하고 다음 메시지
        return mtype, payload


def send_message(sock, mtype, payload=""):
    """소켓에 메시지 한 개 전송. 실패하면 False."""
    try:
        sock.sendall(encode(mtype, payload))
        return True
    except OSError:
        return False


# ---------------- STATE (JSON) 헬퍼 ----------------
def encode_state(state_dict):
    """상태 dict → STATE 메시지용 payload(한 줄 JSON).

    ensure_ascii=False 로 두어 한글 이름이 그대로 실린다.
    (그래도 _escape 가 줄바꿈을 처리하므로 한 줄 규칙은 유지된다.)
    """
    import json
    return json.dumps(state_dict, ensure_ascii=False, separators=(",", ":"))


def decode_state(payload):
    """STATE payload(JSON 한 줄) → 상태 dict. 실패하면 None."""
    import json
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


# ---------------- ASK (JSON) 헬퍼 ----------------
# ★ GUI(웹) 클라이언트는 '지금 무엇을 입력하는 중인가'를 알아야
#   클릭 UI(패 클릭 / 화살표 / 값 버튼)를 띄울 수 있다.
#   → ASK payload 를 JSON 으로 보내 prompt 와 함께 mode/data 를 싣는다.
#   터미널 클라이언트(client.py)는 이 payload 를 그대로 프롬프트로 쓴다
#   (decode_ask 가 실패하면 원문을 prompt 로 돌려주므로 하위호환).
def encode_ask(prompt, mode=None, data=None):
    """입력 요청 → ASK payload(한 줄 JSON).

    mode : 'guess' | 'black_count' | 'joker_slot' | 'joker_side'
           | 'more_guess' | 'fail_reveal' | 'name' | None(일반 텍스트 입력)
    data : 모드별 부가 정보 dict (예: 조커 슬롯 개수, 후보 자리 목록)
    """
    import json
    obj = {"prompt": prompt}
    if mode:
        obj["mode"] = mode
    if data:
        obj["data"] = data
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def decode_ask(payload):
    """ASK payload → (prompt, mode, data).

    JSON 이 아니면(구형/평문) (payload, None, None) 으로 돌려준다.
    """
    import json
    if not payload:
        return "", None, None
    s = payload.lstrip()
    if not s.startswith("{"):
        return payload, None, None
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return payload, None, None
    if not isinstance(obj, dict):
        return payload, None, None
    return (obj.get("prompt", ""), obj.get("mode"), obj.get("data"))
