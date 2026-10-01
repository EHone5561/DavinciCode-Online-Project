# -*- coding: utf-8 -*-
"""다빈치 코드 exe 빌드 스크립트.

두 가지 빌드를 지원한다:

    python -E build_exe.py            ← 웹 버전 (기본) : 다빈치코드_웹.exe
    python -E build_exe.py web        ← 위와 같음
    python -E build_exe.py term       ← 터미널 버전      : 다빈치코드.exe

★ 웹 버전은 web/game.html 과 sfx/*.ogg 를 exe 안에 넣는다(--add-data).
  그래야 브라우저로 접속했을 때 화면과 소리가 나온다.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 공통
ICON = "DavinciCode.ico"

# 동적으로 import 되는 모듈들 — PyInstaller 가 못 찾을 수 있으므로 명시
HIDDEN_COMMON = [
    "relay", "client", "session", "protocol", "run_game",
    "DavinciCode", "prob_ai",
]
HIDDEN_WEB = HIDDEN_COMMON + ["web_server", "web_launcher"]


def _clean(workdir, spec):
    """이전 빌드 산출물 정리 (build/, spec).

    ⚠️ dist/ 안의 다른 exe 는 지우지 않는다.
    """
    if os.path.isdir(workdir):
        shutil.rmtree(workdir, ignore_errors=True)
    if os.path.isfile(spec):
        os.remove(spec)


def _run_pyinstaller(name, entry, hidden, add_data=None, workdir_name=None):
    """PyInstaller 를 실행하고 결과 exe 경로를 돌려준다 (실패 시 None)."""
    workdir = os.path.join(HERE, workdir_name or ("build_" + name))
    spec = os.path.join(HERE, f"{name}.spec")
    _clean(workdir, spec)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--name", name,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", workdir,
        "--specpath", HERE,
    ]
    for m in hidden:
        cmd += ["--hidden-import", m]
    for src, dst in (add_data or []):
        cmd += ["--add-data", f"{src}{os.pathsep}{dst}"]

    icon_path = os.path.join(HERE, ICON)
    if os.path.isfile(icon_path):
        cmd += ["--icon", icon_path]
        print(f"아이콘: {ICON}")
    else:
        print(f"[i] 아이콘 없음({ICON}) — 기본 아이콘으로 빌드")

    cmd.append(entry)

    # ★ 부모 환경에 PYTHONHOME 이 다른 버전으로 박혀 있으면
    #   PyInstaller 자식 프로세스가 엉뚱한 표준 라이브러리를 물고
    #   "SRE module mismatch" 로 죽는다.  3.14 실행파일 + 3.11 라이브러리 조합.
    #   → 자식에게는 PYTHONHOME/PYTHONPATH 를 넘기지 않는다.
    child_env = dict(os.environ)
    child_env.pop("PYTHONHOME", None)
    child_env.pop("PYTHONPATH", None)

    print("빌드 명령:")
    print("  " + " ".join(cmd))
    print("-" * 60)
    r = subprocess.run(cmd, env=child_env)
    if r.returncode != 0:
        print("[!] 빌드 실패")
        return None

    exe = os.path.join(HERE, "dist", f"{name}.exe")
    if os.path.isfile(exe):
        size = os.path.getsize(exe) / (1024 * 1024)
        print("-" * 60)
        print(f"[OK] 빌드 완료: {exe}  ({size:.1f} MB)")
        return exe
    print("[!] exe 파일을 찾을 수 없습니다.")
    return None


# ---------------------------------------------------------------- 웹 버전
def build_web():
    """웹(브라우저) 버전 — web/game.html 과 sfx/ 를 함께 묶는다."""
    print("=== 웹 버전 빌드 (다빈치코드_웹.exe) ===")
    add_data = [
        (os.path.join(HERE, "web", "game.html"), "web"),
        (os.path.join(HERE, "sfx"), "sfx"),
    ]
    # 자산이 실제로 있는지 확인 (없으면 exe 가 빈 화면이 된다)
    for src, _dst in add_data:
        if not os.path.exists(src):
            print(f"[!] 웹 자산 없음: {src}")
            return 1
    return 0 if _run_pyinstaller("다빈치코드_웹", "web_launcher.py",
                                 HIDDEN_WEB, add_data,
                                 workdir_name="build_web") else 1


# ---------------------------------------------------------------- 터미널 버전
def build_term():
    """터미널 버전 (이미 배포됨 — 재빌드용으로 남겨둔다)."""
    print("=== 터미널 버전 빌드 (다빈치코드.exe) ===")
    return 0 if _run_pyinstaller("다빈치코드", "launcher.py",
                                 HIDDEN_COMMON,
                                 workdir_name="build_term") else 1


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    os.chdir(HERE)
    what = (argv[0].lower() if argv else "web")
    if what in ("web", "w", "html"):
        return build_web()
    if what in ("term", "terminal", "t", "cli"):
        return build_term()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
