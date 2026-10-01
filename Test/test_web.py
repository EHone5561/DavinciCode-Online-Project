# -*- coding: utf-8 -*-
"""web_server.py 검증 — relay + web_server 를 띄우고 HTTP API 확인.

브라우저 없이 curl 로:
  1) /            → HTML 이 오는지
  2) /api/state   → STATE(JSON) 가 오는지
  3) /api/reply   → 입력이 relay 로 전달되는지 (게임이 진행되는지)
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
GAME_PORT = 8893
WEB_PORT = 8894
ENV = dict(os.environ, RESULT_DELAY="0", GUESS_DELAY="0")
for k in ("PYTHONHOME", "PYTHONPATH", "AUTOHUMAN"):
    ENV.pop(k, None)


def http_get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}{path}", timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def http_post(path, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{WEB_PORT}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    import testutil
    testutil.free_port(GAME_PORT)
    testutil.free_port(WEB_PORT)

    # relay 서버: 2인 (사람 1 + CPU 1)
    srv = subprocess.Popen(
        [PY, "-E", "-u", "relay.py", "2", "--cpu", "1", "--port", str(GAME_PORT)],
        cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    time.sleep(2.0)

    # web_server (--name 없이: 이름도 브라우저(=여기서) 입력)
    web = subprocess.Popen(
        [PY, "-E", "-u", "web_server.py", "--host", "127.0.0.1",
         "--port", str(GAME_PORT), "--web-port", str(WEB_PORT),
         "--no-browser"],
        cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    time.sleep(2.0)

    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + name)
        ok = ok and cond

    try:
        # 1) HTML
        st, body = http_get("/")
        chk("GET / → HTML 응답", st == 200 and "<html" in body.lower())
        chk("HTML 에 시안 CSS 포함", "radial-gradient" in body and "패 산" in body)

        # 1.5) 이름 질문에 응답 (이름은 브라우저에서 입력하는 구조)
        st, body = http_get("/api/state")
        dn = json.loads(body)
        if dn.get("ask_prompt"):
            print(f"   (이름 질문 응답: 웹테스터) ask_prompt={dn['ask_prompt']!r}")
            http_post("/api/reply", {"text": "웹테스터"})
            time.sleep(0.8)

        # 2) 검은 카드 수 질문이 오면 응답 (게임 시작 단계)
        st, body = http_get("/api/state")
        d0 = json.loads(body)
        ask0 = d0.get("ask") or {}
        if ask0.get("mode") == "black_count":
            print(f"   (검은 카드 수 질문에 응답: 0) max={ask0.get('data', {}).get('max')}")
            http_post("/api/reply", {"text": "0"})
            time.sleep(1.2)
        elif d0.get("ask_prompt"):
            print("   (프롬프트 응답: 0)")
            http_post("/api/reply", {"text": "0"})
            time.sleep(1.2)

        # 3) state
        time.sleep(0.8)
        st, body = http_get("/api/state")
        d = json.loads(body)
        chk("GET /api/state → 200", st == 200)
        chk("STATE 수신됨(게임 진행)", d.get("state") is not None)
        chk("접속 인식(HELLO)", d.get("connected") is True)
        if d.get("state"):
            s = d["state"]
            chk("STATE 에 players/round/deck 존재",
                "players" in s and "round" in s and "deck" in s)
            chk("내 좌석(is_me) 1명", sum(1 for p in s["players"] if p.get("is_me")) == 1)
            chk("상대 '미공개' 카드 값은 가려짐(비밀)",
                all(c.get("value") is None
                    for p in s["players"] if not p["is_me"]
                    for c in p["cards"] if not c.get("revealed")))

        # 3) reply (입력 전달 → 게임 진행)
        st, r = http_post("/api/reply", {"text": "q"})
        chk("POST /api/reply → ok", st == 200 and r.get("ok") is True)

        # 게임이 조금 진행됐는지 로그 확인
        time.sleep(2.0)
        st, body = http_get("/api/state")
        d2 = json.loads(body)
        has_log = any("다빈치" in m or "정답" in m or "오답" in m or "턴" in m
                      for m in d2.get("messages", []))
        chk("게임 로그(SHOW) 수신", has_log or d2.get("msg_total", 0) > 0)

        # 4) ★ ask 모드(data) 가 STATE 에 실려 오는지 — 클릭 UI 의 전제
        #    내 턴이 될 때까지 잠깐 기다리며 guess 모드를 찾는다.
        found_guess = None
        my_seat = None
        for _ in range(40):
            st, body = http_get("/api/state")
            dd = json.loads(body)
            my_seat = dd.get("seat")
            a = dd.get("ask") or {}
            if a.get("mode") == "guess":
                found_guess = a
                break
            if a.get("mode") == "more_guess":
                http_post("/api/reply", {"text": "q"})
            elif a.get("mode") in ("black_count",):
                http_post("/api/reply", {"text": "0"})
            elif a.get("mode") == "fail_reveal":
                http_post("/api/reply", {"text": str((a.get("data") or {}).get("hidden", [1])[0])})
            elif a.get("mode") or dd.get("ask_prompt") is not None:
                http_post("/api/reply", {"text": "q"})
            elif dd.get("ended"):
                break
            time.sleep(0.4)
        if found_guess is not None:
            chk("ask.mode='guess' + targets + values 수신",
                isinstance(found_guess.get("targets"), list)
                and isinstance(found_guess.get("values"), list)
                and len(found_guess["values"]) > 0)
            # 지목 대상은 내 패가 아닌 상대 자리만
            chk("지목 대상에 내 좌석 미포함",
                all(t.get("seat") != my_seat
                    for t in found_guess.get("targets", [])))
            print(f"   (guess ask: targets={len(found_guess.get('targets', []))}개, "
                  f"values={len(found_guess.get('values', []))}개, 내좌석={my_seat})")
        else:
            print("  SKIP guess ask 미포착(턴 타이밍) — 모드 배선은 relay 테스트로 확인")

    finally:
        for p in (web, srv):
            if p.poll() is None:
                p.kill()
        testutil.free_port(GAME_PORT)
        testutil.free_port(WEB_PORT)

    print("RESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
