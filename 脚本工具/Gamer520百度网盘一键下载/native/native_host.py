#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chrome/Edge Native Messaging host: run Gamer520-BaiduDownload.ps1"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "Gamer520-BaiduDownload.ps1"


def read_message() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    (length,) = struct.unpack("<I", raw_len)
    data = sys.stdin.buffer.read(length)
    if not data:
        return None
    return json.loads(data.decode("utf-8"))


def send_message(msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def run_download(url: str) -> dict:
    if not PS1.is_file():
        return {"ok": False, "error": f"找不到脚本: {PS1}"}
    # 新控制台窗口跑下载，避免卡住 native messaging 管道
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PS1),
                "-Url",
                url,
            ],
            cwd=str(ROOT),
            creationflags=creationflags,
        )
        return {"ok": True, "url": url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> int:
    msg = read_message()
    if not msg:
        send_message({"ok": False, "error": "空消息"})
        return 1
    url = (msg.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        send_message({"ok": False, "error": f"无效 URL: {url}"})
        return 1
    send_message(run_download(url))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        try:
            send_message({"ok": False, "error": str(exc)})
        except Exception:
            pass
        raise SystemExit(1)
