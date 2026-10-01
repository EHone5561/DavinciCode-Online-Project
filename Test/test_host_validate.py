# -*- coding: utf-8 -*-
"""launcher 의 IP/호스트 검증(_valid_host) 단위 검증."""

import launcher as L


CASES = [
    # (입력, 기대)
    ("127.0.0.1", True),
    ("192.168.0.49", True),
    ("0.0.0.0", True),
    ("255.255.255.255", True),
    ("0.tcp.ngrok.io", True),
    ("localhost", False),          # 점 없음 → 거부 (IP 아님)
    ("my.server.com", True),
    ("ads", False),                # ★ EHone 이 지적한 케이스
    ("192.168.0", False),          # 옥텟 3개
    ("192.168.0.256", False),      # 범위 초과
    ("192.168.0.-1", False),
    ("1.2.3.4.5", False),
    ("", False),
    ("  ", False),
    ("192.168.0.1 2", False),      # 내부 공백
    ("192.168.0.1;rm", False),     # 특수문자
    ("a..b", False),               # 빈 라벨 → 거부
    ("-abc.com", False),           # 하이픈 시작
    ("abc.com-", False),
    (".", False),
    ("...", False),
    ("1.2.3.a", True),             # 문자 포함 → 호스트명으로 허용
]


def main():
    ok = True
    for s, exp in CASES:
        got = L._valid_host(s)
        mark = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"  {mark}  {s!r:24} → {got}  (기대 {exp})")
    print("RESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
