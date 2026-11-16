"""打包控制面板成 exe：檔名帶版本（MusicBotLauncher-1.1.0.exe），並把版本寫進 Windows 的檔案版本資訊

用法：
  pip install pyinstaller
  python launcher/build.py                 -> 輸出到專案的 dist/
  python launcher/build.py --out 某個資料夾

版本號來自 launcher/botpanel/__init__.py 的 __version__，圖示是 launcher/MusicBotLauncher.ico

Build the control panel into an exe: the file name carries the version (MusicBotLauncher-1.1.0.exe) and the version is
written into the Windows file version info (right click -> Properties -> Details).

Usage:
  pip install pyinstaller
  python launcher/build.py                 -> writes into the project's dist/
  python launcher/build.py --out SOME_DIR

The version comes from __version__ in launcher/botpanel/__init__.py, the icon is launcher/MusicBotLauncher.ico.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from botpanel import __version__   # noqa: E402  (要先把 launcher/ 放進路徑 / launcher/ must be on the path first)

NAME = "MusicBotLauncher"
TITLE = "Discord 音樂機器人控制面板"


def numbers(version: str) -> tuple[int, int, int, int]:
    """"1.1.0" -> (1, 1, 0, 0)：Windows 的版本是四個數字 / Windows versions are four numbers."""
    nums = [int(x) for x in re.findall(r"\d+", version)][:4]
    return tuple(nums + [0] * (4 - len(nums)))  # type: ignore[return-value]


def version_info(version: str) -> str:
    """PyInstaller 的版本資訊檔內容 / The content of PyInstaller's version-info file."""
    v = numbers(version)
    dotted = ".".join(map(str, v))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040404B0', [
      StringStruct('FileDescription', '{TITLE}'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('OriginalFilename', '{NAME}-{version}.exe'),
      StringStruct('ProductName', '{TITLE}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0404, 1200])])
  ])
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="輸出資料夾，預設是專案的 dist/ / output folder, default is the project's dist/")
    out = Path(ap.parse_args().out or HERE.parent / "dist").resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        vfile = Path(tmp) / "version_info.txt"
        vfile.write_text(version_info(__version__), encoding="utf-8")
        cmd = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
            "--icon", str(HERE / "MusicBotLauncher.ico"), "--version-file", str(vfile),
            "--name", f"{NAME}-{__version__}", "--distpath", str(out), "--workpath", str(Path(tmp) / "work"),
            "--specpath", tmp, str(HERE / "launcher.py"),
        ]
        code = subprocess.run(cmd).returncode
    if code == 0:
        print(f"\n完成 / done: {out / f'{NAME}-{__version__}.exe'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
