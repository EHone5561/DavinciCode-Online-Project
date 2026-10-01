# -*- coding: utf-8 -*-
"""테스트 공용 유틸.

★ 이전 실행에서 남은 좀비 서버 프로세스/포트를 정리한다.
  (테스트를 반복/연속 실행하면 이전 서버가 포트를 점유한 채 남아,
   다음 테스트의 클라이언트 접속이 실패하는 일이 있었다 —
   실측: test_relay 4인 케이스가 '좌석=None 응답=0' 으로 FAIL.)

윈도우에서 실행: bash(git-bash/MSYS) 환경이므로 taskkill 은 //F //PID 로.
"""

import os
import subprocess
import sys


def free_port(port, verbose=True):
    """지정 포트를 LISTEN 중인 프로세스를 찾아 종료한다.

    Returns: 종료시킨 PID 목록 (없으면 빈 리스트).
    """
    if not sys.platform.startswith("win"):
        # POSIX: lsof 로 찾아 kill
        killed = []
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True, timeout=5).stdout
            for pid in out.split():
                subprocess.run(["kill", "-9", pid], timeout=5)
                killed.append(pid)
        except (OSError, subprocess.SubprocessError):
            pass
        if killed and verbose:
            print(f"[testutil] 포트 {port} 정리: {killed}")
        return killed

    killed = []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return killed

    pids = set()
    for line in out.splitlines():
        parts = line.split()
        # 예: TCP  0.0.0.0:8802  0.0.0.0:0  LISTENING  9208
        if len(parts) >= 5 and parts[3] == "LISTENING":
            local = parts[1]
            if local.endswith(f":{port}"):
                pids.add(parts[4])
    for pid in pids:
        if pid == "0":
            continue
        try:
            # ⚠️ Python subprocess 는 bash 의 '//' → '/' 변환을 거치지 않는다.
            #    ('//F' 로 넘기면 taskkill 이 'Invalid argument/option' 으로 실패)
            r = subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                killed.append(pid)
        except (OSError, subprocess.SubprocessError):
            pass
    if killed and verbose:
        print(f"[testutil] 포트 {port} 좀비 정리: PID {killed}")
    return killed


def free_ports(ports, verbose=True):
    """여러 포트를 한 번에 정리."""
    killed = []
    for p in ports:
        killed += free_port(p, verbose=verbose)
    return killed


if __name__ == "__main__":
    # 직접 실행: python -E testutil.py 8801 8802 8803
    args = sys.argv[1:]
    ports = [int(a) for a in args] if args else [8801, 8802, 8803]
    n = free_ports(ports)
    print(f"[testutil] 정리한 PID: {n or '(없음)'}")
