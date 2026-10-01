# 다빈치 코드 — 프로그램 구조

이 문서는 **개발자/유지보수용** 설명입니다.
"이 파일이 무슨 일을 하는가"를 빠르게 파악하려고 쓴 문서예요.
게임 방법은 `README.md`, AI 원리는 `CPU_AI_설명.md`, 규칙 명세는 `design/game_spec.md` 를 보세요.

---

## 1. 전체 그림

이 프로그램은 **모델 / 중계 / 뷰** 를 분리한 구조입니다.
핵심 아이디어는 **"게임 상태(진실)는 서버 한 곳에만 있고, 나머지는 상태를 그려주는 껍데기"** 입니다.

```
                        ┌──────────────────────────┐
                        │   relay.py (게임 서버)    │
                        │   게임 상태 보유 = 진실   │
                        │   session.py 로 진행      │
                        └───────┬──────────┬───────┘
                                │          │
                 ┌──────────────┘          └──────────────┐
                 ▼                                        ▼
      ┌────────────────────┐                  ┌────────────────────┐
      │ web_server.py      │                  │ client.py          │
      │ (브라우저 ↔ relay) │                  │ (터미널 참가자)     │
      └─────────┬──────────┘                  └────────────────────┘
                │ HTTP 폴링 / POST
                ▼
      ┌────────────────────┐
      │ web/game.html      │
      │ (브라우저 화면)     │
      └────────────────────┘
```

**왜 이렇게 나눴나**: 게임 규칙은 한 번만 구현하고, 화면(터미널/웹/나중엔 다른 GUI)은
교체 가능하게 하기 위해서입니다. `session.py` 가 터미널과 웹 양쪽에서 재사용됩니다.

---

## 2. 계층별 파일

### 2-1. 순수 모델 — `DavinciCode.py` (574줄)

**게임 규칙 그 자체.** 화면/네트워크를 전혀 모릅니다. `time.sleep` 도 없습니다.

| 클래스 | 역할 |
|---|---|
| `Card` | 카드 한 장. `value`(0~11 또는 조커), `is_black`. `display()` 로 `3b`/`aw`/`Jw` 문자열 |
| `Table` | 덱·패산·공개 카드 관리. `deal()`, `draw()`, `cards_per_player()` |
| `Player` | 한 사람의 손패. `sort_hand()`(조커=벽), `reveal()`, `is_eliminated()`(공개집합 == 자기패 로 파생) |
| `RandomDecider` | 조커 배치를 무작위로 정하는 기본 결정자 |
| `Game` | 턴 순환·라운드·딜·판정. `next_turn()` 은 탈락자를 건너뜁니다 |

**결정자(Decider) 계층**: "조커를 어디에 둘까" 같은 선택을 위임합니다.
`HumanDecider`(사람 입력) / `RandomDecider`(무작위) / `prob_ai.StrategicDecider`(확률 전략).

> **주의**: 모델은 네트워크·화면 코드를 넣지 않습니다. AI의 "기억"도 모델이 아니라
> `game` 객체 속성(`_ai_prob_memory` 등)에 붙여, 모델을 오염시키지 않습니다.

---

### 2-2. 확률 추론 AI — `prob_ai.py` (1015줄)

CPU의 두뇌. **공개 정보만으로** 상대 카드의 확률을 계산합니다.

핵심 함수는 `position_spec_probabilities()` — 자리별 `(값, 색)` 확률을 냅니다.
중복조합 공식으로 "이 배치가 성립하는 경우의 수"를 세고 정규화해요.

자세한 원리는 `CPU_AI_설명.md` 참고. 파일 하단에 `_selftest()` 가 있어
`python prob_ai.py` 로 단독 회귀 점검을 할 수 있습니다.

---

### 2-3. 게임 진행 (터미널 비의존) — `session.py` (918줄)

**`run_game.py` 의 게임 루프를 "터미널에서 떼어낸" 버전.** 이게 구조의 심장입니다.

| 요소 | 역할 |
|---|---|
| `Output` (인터페이스) | `show` / `show_me` / `ask` / `wait` / `finish` / `is_connected` / `on_forfeit` |
| `Session` | 게임 루프 본체. `Session(io, 인원, names=, human_seats=, rng=)` |
| `_SeatDecider` | 사람 좌석의 결정을 `io.ask` 로 중계 |
| `SilentOutput` | 검증용 — 출력을 버리고 자동응답 |

**좌석(seat) 번호 = `players` 리스트 인덱스(0-based).** `human_seats` 에 없는 좌석은 CPU가 플레이합니다.
입력 검증·재질문은 **서버(session)** 가 담당하므로, 클라이언트는 규칙을 몰라도 됩니다.

`_state_dict()` 가 웹 GUI 용 **STATE JSON** 을 만듭니다. 이때 비밀 정보를
`open_`(= 내가 보거나 공개된 카드) 기준으로 가립니다.

---

### 2-4. 중계 서버 — `relay.py` (776줄)

**게임 상태를 혼자 보유하는 진실의 원천.**

```
       relay.py (게임 상태 보유)
          ↑      ↑      ↑
     client1  client2  client3   ← 각자 화면
```

| 클래스 | 역할 |
|---|---|
| `ClientConn` | 접속자 하나 (소켓 + 수신 스레드 + 큐) |
| `RelayOutput` | `Output` 구현체 — 소켓으로 화면/입력을 중계 |
| `RelayServer` | 좌석 관리·접속 대기·게임 실행. 이름 대기, 재시작 루프, 기권 판정 |

- 게임 진행은 **메인 스레드 하나**가 순차로, `read_reply()` 가 큐에서 답을 꺼낼 때까지 블록합니다.
- 실행: `python relay.py 3 --cpu 1 --port 8765`
- **`--cpu` 는 뒤쪽 좌석부터** 채웁니다 (`range(n-cpu, n)`).
- 게임 종료 후 `_restart_wait()` 로 '다시하기' 투표를 받고, 전원 동의 시 새 판을 시작합니다.

---

### 2-5. 프로토콜 계약서 — `protocol.py` (220줄)

**서버와 클라이언트가 주고받는 메시지 형식.** 한 줄 = 한 메시지, 개행은 이스케이프합니다.

| 방향 | 메시지 |
|---|---|
| 서버→클라 | `HELLO`(좌석 배정) / `SHOW`(공통) / `SHOWME`(개인 비밀) / `ASK`(입력 요청) / `WAIT`(대기) / `STATE`(GUI 상태 JSON) / `END` / `RESTARTED`(재시작 현황) |
| 클라→서버 | `REPLY` / `CHAT` / `PING`(생존 신호) / `RESTART`(다시하기 투표) / `BYE` |

`encode_ask()` / `decode_ask()` 는 ASK payload 를 JSON 으로 실어
`mode`(guess/black_count/joker_slot/…)와 `data`(버튼 UI 힌트)를 함께 보냅니다.
`decode_ask` 는 `{` 로 시작 안 하면 원문을 prompt 로 돌려주므로 **구형 터미널 클라이언트와 호환**됩니다.

---

### 2-6. 웹 브라우저 뷰 — `web_server.py` (472줄) + `web/game.html` (1111줄)

브라우저는 소켓을 못 다루니, **로컬 HTTP 서버**가 중간에서 relay 와 브라우저를 이어줍니다.

```
브라우저 ──HTTP──▶ web_server ──TCP──▶ relay
   ▲                   │
   └── /api/state 폴링 ─┘   (약 0.28초마다)
```

| 요소 | 역할 |
|---|---|
| `GameBridge` | relay 소켓 연결 + 수신 스레드 + PING 생존 신호 |
| `Handler` | HTTP 엔드포인트 |

| 엔드포인트 | 용도 |
|---|---|
| `GET /` | `game.html` 서빙 |
| `GET /api/state` | 게임 상태 JSON (폴링) |
| `POST /api/reply` | 게임 입력 (지목/버튼) |
| `POST /api/name` | 이름 전송 |
| `POST /api/chat` | 채팅 |
| `POST /api/restart` | 다시하기 투표 |

**`web/game.html`** 은 시안(`design/gui_mockup.html`)의 CSS 를 살린 단일 파일입니다.
STATE JSON 을 받아 DOM 을 그립니다. 게임 입력은 전부 버튼/클릭이고,
맨 아래 텍스트 입력창은 **채팅 전용**입니다.

---

### 2-7. 실행 진입점 (런처)

두 개의 exe 로 각각 빌드됩니다. **입력 헬퍼가 의도적으로 중복**돼 있으니
`_ask_int`/`_ask_text`/`_valid_host`/`_ask_host`/`_pause_before_exit` 수정 시 **양쪽 다** 고쳐야 합니다.

| 파일 | exe | 대상 |
|---|---|---|
| `launcher.py` (249줄) | `다빈치코드.exe` | 터미널 버전 (서버/참가/시연) |
| `web_launcher.py` (494줄) | `다빈치코드_웹.exe` | 웹 버전 (혼자/방만들기/참가) |

`web_launcher.py` 는 relay 를 **데몬 스레드**로 띄우고, 웹서버를 메인 스레드에서 돌립니다
(relay 는 블로킹이라 스레드가 필요). `[2] 방 만들기` 는 `--web-host 0.0.0.0` 로 바인딩해
다른 PC 접속을 허용하고, LAN IP 를 안내합니다.

`build_exe.py` (139줄) = PyInstaller 빌드 스크립트.
`python build_exe.py web` / `term` 으로 두 타깃을 빌드합니다.

---

### 2-8. 터미널 시연/참가

| 파일 | 역할 |
|---|---|
| `run_game.py` (608줄) | **터미널 시연용** (사람이 직접 플레이). 사람이 보기 좋게 지연·안내가 들어있음 |
| `client.py` (193줄) | 터미널 참가자. 게임 규칙을 전혀 모르고 프롬프트만 출력 |

`run_game.py` 와 `session.py` 는 로직이 일부 중복돼 있습니다(시연용/네트워크용 분리).
**사람 면전 지연**은 `run_game.py`·relay 경로에만 있고, 디버깅용 사본에는 넣지 않는 게 관례입니다.

---

## 3. 데이터 흐름 (한 턴)

```
① relay: session.run() 이 턴 주인 결정
        ↓
② STATE JSON 생성 (_state_dict) — 비밀은 open_ 기준으로 가림
        ↓
③ RelayOutput 이 각 클라이언트에 SHOW / SHOWME / WAIT 전송
        ↓
④ web_server 가 relay 에서 받아 브라우저 스냅샷에 저장
        ↓
⑤ 브라우저가 /api/state 폴링 → DOM 렌더 (버튼 UI)
        ↓
⑥ 사용자가 카드 클릭 + 값 버튼 클릭 → POST /api/reply
        ↓
⑦ web_server → relay 로 REPLY
        ↓
⑧ session 이 판정 → 결과를 다시 ③번으로
```

---

## 4. 설계 규칙 (기여 시 지킬 것)

1. **모델 ↔ 뷰 분리** — `DavinciCode.py` 에 화면/네트워크 코드를 넣지 않습니다.
2. **게임 상태는 서버 한 곳** — 클라이언트는 진실을 보관하지 않습니다.
3. **비밀 정보는 `open_` 기준** — STATE 필드를 추가할 때마다 "이게 비밀인가?"를 확인합니다.
   (색은 공개, 값·조커 여부는 비밀)
4. **같은 판정은 헬퍼 하나로** — 생존/기권 판정을 두 곳에서 따로 구현하면 반드시 갈라집니다.
5. **입력은 메인 스레드, 출력은 락** — 소켓 수신 스레드에서 `input()` 을 부르면
   Windows 에서 빈 응답이 돌아옵니다.
6. **런처 중복은 의도적** — 두 exe 가 독립 배포 단위이므로 함부로 합치지 않습니다.
7. **`python -E` 로 실행** — 이 환경은 `PYTHONHOME` 간섭이 있어 `-E` 가 필요합니다.

---

## 5. 테스트 (`Test/` 폴더)

`Test/` 안에 검증 스크립트가 모여 있습니다.
⚠️ **경로가 루트 기준으로 작성돼 있어**, 폴더 안에서 그대로 돌리면 import 가 깨집니다.
필요할 때 **루트로 꺼내서** 실행하는 방식입니다.

```
cd C:\Suzuha\DavinciOnline
python -E Test\test_session.py       # 게임 진행 (CPU 완주)
python -E Test\test_relay.py         # 실제 소켓 릴레이
python -E Test\test_web.py           # 웹 브리지
python -E Test\test_restart_logic.py # 다시하기 좌석 규칙
node Test\test_webui.js              # game.html DOM 검증 (Python 아님)
```

`dev_no_sleep/` 은 **디버깅용 무지연 사본**(`DavinciCode.py` + `run_game.py`)입니다.
사람 면전 지연을 뺀 상태로 빠르게 완주시켜 검증할 때 씁니다.

---

## 6. 파일 요약표

| 파일 | 줄 수 | 한 줄 정의 |
|---|---|---|
| `DavinciCode.py` | 574 | 순수 게임 모델 (규칙) |
| `prob_ai.py` | 1015 | 확률 추론 CPU AI |
| `session.py` | 918 | 게임 진행 루프 (뷰 비의존) |
| `relay.py` | 776 | 중계 서버 (상태 보유) |
| `protocol.py` | 220 | 메시지 계약서 |
| `web_server.py` | 472 | 브라우저 ↔ relay HTTP 브리지 |
| `web/game.html` | 1111 | 브라우저 화면 (단일 파일) |
| `client.py` | 193 | 터미널 참가자 |
| `run_game.py` | 608 | 터미널 시연용 |
| `launcher.py` | 249 | 터미널 exe 진입점 |
| `web_launcher.py` | 494 | 웹 exe 진입점 |
| `build_exe.py` | 139 | PyInstaller 빌드 |
| `design/game_spec.md` | — | 규칙 명세 |
| `design/gui_mockup.html` | — | GUI 시안 (CSS 원본) |
| `README.md` | — | 사용자 안내서 |
| `CPU_AI_설명.md` | — | AI 원리 |
| `sfx/` | — | 효과음 5종 |
| `Test/` | — | 검증 스크립트 |
| `dist/` | — | 빌드된 exe 2종 |
