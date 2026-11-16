"""回歸測試執行器 / Regression runner

每個套件各自啟動一個乾淨的假環境（harness_hub.py：真的 Hub、Dashboard、PlayerBot，只有 Discord 語音層是假的），跑完就收掉
Every suite gets its own clean fake environment (harness_hub.py: the real Hub, Dashboard and PlayerBot, only the Discord voice layer is faked) and is stopped afterwards

用法 / Usage (從專案根目錄 / from the project root):
    .venv\\Scripts\\python.exe tests\\run_all.py            全部 / everything
    .venv\\Scripts\\python.exe tests\\run_all.py verify    只跑名稱含 verify 的 / only suites whose name contains "verify"

需要 / Needs: 網路（測試會解析一支 Bilibili 影片）、ffmpeg、已安裝的套件
              network access (tests resolve a Bilibili video), ffmpeg and the installed packages
"""
import os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # Windows 上不要彈出黑視窗 / no console window on Windows

# 要用 harness 的套件：(腳本, DASHBOARD_ACCESS 模式, 額外環境變數)
# Suites that run against the harness: (script, DASHBOARD_ACCESS mode, extra env)
SUITES = [
    ("hub_test.py", "voice", {}),
    ("open_test.py", "open", {"N_WORKERS": "2"}),
    ("loop_test.py", "open", {"N_WORKERS": "2", "FAKE_SECS": "7"}),
    ("seek_test.py", "open", {}),
    ("quality_test.py", "open", {}),
    ("verify_test.py", "verify", {}),
    ("health_test.py", "open", {}),
    ("avatar_test.py", "verify", {}),
]
# 自己就能跑的（不需要 harness）/ Self-contained (no harness needed)
STANDALONE = ["health_unit.py", "harden_test.py", "recover_unit.py", "source_unit.py", "launcher_unit.py"]


def stop(p):
    """關掉子程序並等它結束，避免下一個套件搶不到埠 / Kill a child and wait for it, so the next suite can reuse the ports."""
    if p.poll() is None:
        p.kill()
    p.wait()


def summary(out):
    """從輸出找出 "N/M 通過" / Find the "N/M 通過" summary line in the output."""
    m = re.findall(r"(\d+)/(\d+) 通過", out)
    return tuple(map(int, m[-1])) if m else None


def run_script(script, env):
    r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, script)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=ROOT, timeout=900)
    return r.returncode, r.stdout + r.stderr


def main(argv):
    pick = [a.lower() for a in argv]
    want = lambda name: not pick or any(k in name.lower() for k in pick)
    total_pass = total = 0
    failed = False

    def report(script, label, code, out):
        nonlocal total_pass, total, failed
        s = summary(out)
        if s:
            total_pass += s[0]
            total += s[1]
        if not s or s[0] != s[1] or code != 0:
            failed = True
        print(f"== {script} ({label}): {'%d/%d' % s if s else '沒有總結 / no summary'}  exit={code}", flush=True)
        for line in out.splitlines():
            if line.startswith("FAIL"):
                print("   ", line[:220], flush=True)
        if not s:
            print(out[-800:], flush=True)

    for script, access, extra in SUITES:
        if not want(script):
            continue
        log = os.path.join(HERE, "harness.log")
        env = {**os.environ, "FAKE_SECS": "900", "N_WORKERS": "3", "PYTHONIOENCODING": "utf-8", **extra, "DASHBOARD_ACCESS": access}
        with open(log, "w", encoding="utf-8") as fh:
            p = subprocess.Popen([PY, "-X", "utf8", os.path.join(HERE, "harness_hub.py")], cwd=ROOT, env=env,
                                 stdout=fh, stderr=subprocess.STDOUT, creationflags=NOWIN)
            try:
                t0 = time.time()
                while time.time() - t0 < 40 and "READY" not in open(log, encoding="utf-8", errors="ignore").read():
                    time.sleep(0.5)
                code, out = run_script(script, {**os.environ, "PYTHONIOENCODING": "utf-8", **extra})
            finally:
                stop(p)
        report(script, access, code, out)
    for script in STANDALONE:
        if want(script):
            code, out = run_script(script, {**os.environ, "PYTHONIOENCODING": "utf-8"})
            report(script, "standalone", code, out)
    print(f"\n全部 / total：{total_pass}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
