"""中繼站回歸測試執行器 / Relay regression runner

啟動 relay（8770）＋ harness（帶 RELAY_URL，當作家裡的機器人）＋ 測試腳本，跑完全部收掉
Starts the relay (port 8770) + the harness (with RELAY_URL, playing the bot at home) + the test script, then stops everything

用法 / Usage: .venv\\Scripts\\python.exe tests\\run_relay.py
"""
import os, re, subprocess, sys, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEY = "t" * 40            # 測試用金鑰，不是真的 / throwaway test key, not a real one
SUITES = [                # (腳本, 參數, DASHBOARD_ACCESS) / (script, args, DASHBOARD_ACCESS)
    ("relay_test.py", [], "verify"),
    ("relay_verify.py", [], "verify"),
    ("relay_extra.py", ["voice"], "voice"),
]


def stop(p):
    """關掉子程序並等它結束 / Kill a child and wait for it."""
    if p.poll() is None:
        p.kill()
    p.wait()


def main():
    base = {**os.environ, "PYTHONIOENCODING": "utf-8", "RELAY_KEY": KEY}
    total_pass = total = 0
    failed = False
    for script, args, access in SUITES:
        renv = {**base, "RELAY_PORT": "8770", "RELAY_HOST": "127.0.0.1", "DASHBOARD_ACCESS": access}
        henv = {**base, "FAKE_SECS": "900", "N_WORKERS": "3", "DASHBOARD_ACCESS": access, "RELAY_URL": "ws://127.0.0.1:8770"}
        hlog = os.path.join(HERE, "harness.log")
        with open(os.path.join(HERE, "relay.log"), "w", encoding="utf-8") as rf, open(hlog, "w", encoding="utf-8") as hf:
            rp = subprocess.Popen([PY, "-X", "utf8", "-m", "musicbot.relay"], cwd=ROOT, env=renv,
                                  stdout=rf, stderr=subprocess.STDOUT, creationflags=NOWIN)
            time.sleep(1.5)
            hp = subprocess.Popen([PY, "-X", "utf8", os.path.join(HERE, "harness_hub.py")], cwd=ROOT, env=henv,
                                  stdout=hf, stderr=subprocess.STDOUT, creationflags=NOWIN)
            try:
                t0 = time.time()
                while time.time() - t0 < 40 and "READY" not in open(hlog, encoding="utf-8", errors="ignore").read():
                    time.sleep(0.5)
                time.sleep(2)
                tenv = {**base, "HARNESS": os.path.join(HERE, "harness_hub.py"), "DASHBOARD_ACCESS": access, "RELAY_URL": henv["RELAY_URL"]}
                r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, script), *args], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=tenv, cwd=ROOT, timeout=400)
            finally:
                stop(rp)
                stop(hp)
                # relay_extra 會自己另外啟動一個 harness，要一併關掉 / relay_extra starts one more harness on its own, stop it too
                try:
                    urllib.request.urlopen("http://127.0.0.1:8767/shutdown", timeout=2).read()
                except Exception:
                    pass
        out = r.stdout + r.stderr
        m = re.findall(r"(\d+)/(\d+) 通過", out)
        if m:
            total_pass += int(m[-1][0])
            total += int(m[-1][1])
        if not m or m[-1][0] != m[-1][1] or r.returncode != 0:
            failed = True
        print(f"== {script} ({access}): {m[-1][0] + '/' + m[-1][1] if m else '沒有總結 / no summary'}  exit={r.returncode}", flush=True)
        for line in out.splitlines():
            if line.startswith("FAIL"):
                print("   ", line[:220], flush=True)
        if not m:
            print(out[-900:], flush=True)
        time.sleep(1)
    print(f"\n全部 / total：{total_pass}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
