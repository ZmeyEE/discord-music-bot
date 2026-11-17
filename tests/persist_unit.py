"""存檔與裝置登錄的單元測試：壞檔備份、原子寫入、同一個人的裝置數量上限
Unit tests of persistence and the device registry: broken-file backup, atomic write, the per-person device cap

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import glob
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from musicbot import jsonfile, params
from musicbot.library import Library
from musicbot.members import Registry
from musicbot.spotify import Accounts

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.json")
    check("J1 沒有檔案 = 空的，不建檔", jsonfile.read_dict(p) == {} and not os.path.exists(p))
    jsonfile.write_text(p, '{"a": 1}')
    check("J2 寫了再讀一樣，沒有留下暫存檔", jsonfile.read_dict(p) == {"a": 1} and not os.path.exists(p + ".tmp"))
    with open(p, "w", encoding="utf-8") as f: f.write("{壞掉")
    check("J3 壞檔：回傳空的，原檔被改名備份（不會被下次存檔蓋掉）", jsonfile.read_dict(p) == {} and not os.path.exists(p) and len(glob.glob(p + ".bad-*")) == 1)
    with open(p, "w", encoding="utf-8") as f: f.write("[1, 2]")
    check("J4 最外層不是字典（例如 list）也當壞檔，不會讓啟動崩潰", jsonfile.read_dict(p) == {} and len(glob.glob(p + ".bad-*")) == 2)
    with open(p, "w", encoding="utf-8") as f: f.write("")
    check("J5 0 位元組檔（斷電常見的樣子）也備份後當空的", jsonfile.read_dict(p) == {} and len(glob.glob(p + ".bad-*")) == 3)

    # 各個存檔都吃得下壞檔 / every store survives a broken file
    for name, make in (("library.json", Library), ("tokens.json", Accounts), ("members.json", Registry)):
        q = os.path.join(d, name)
        with open(q, "w", encoding="utf-8") as f: f.write("[]")
        obj = make(q)
        check(f"J6 {name} 最外層是 list：啟動不崩潰，當作空的並留下備份", len(glob.glob(q + ".bad-*")) == 1 and not (getattr(obj, "users", None) or getattr(obj, "devices", None)))

    # 裝置登錄：同一個人同一個伺服器的上限 / the device cap
    reg = Registry(os.path.join(d, "dev.json"))
    toks = [reg.add_device(1, "小明", 10) for _ in range(params.DEVICE_MAX_PER_USER + 4)]
    mine = [r for r in reg.devices.values() if r["uid"] == "1" and r["gid"] == "10"]
    check("M1 同一個人同一個伺服器最多留 DEVICE_MAX_PER_USER 個（連結重新整理不會無限增加）", len(mine) == params.DEVICE_MAX_PER_USER, len(mine))
    check("M2 最新的那個還在、最舊的被丟掉", reg.lookup(toks[-1]) is not None and reg.lookup(toks[0]) is None)
    reg.add_device(2, "小華", 10); reg.add_device(1, "小明", 11)
    check("M3 別人、別的伺服器不受影響", len([r for r in reg.devices.values() if r["uid"] == "2"]) == 1 and len([r for r in reg.devices.values() if r["gid"] == "11"]) == 1)
    first = next(iter(reg.devices)); reg.devices[first]["seen"] = 0
    reg.add_device(3, "阿傑", 10)
    check("M4 登記時順便清掉過期的裝置", first not in reg.devices)
    check("M5 重開後讀回來一樣", len(Registry(os.path.join(d, "dev.json")).devices) == len(reg.devices))

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
