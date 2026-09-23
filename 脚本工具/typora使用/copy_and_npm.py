#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具：把本地 JS 文件复制到指定目录，并在该目录执行 npm 命令。

用法示例：
  1) 交互式（不传参数，运行后按提示输入）：
       python copy_and_npm.py

  2) 命令行指定目标路径：
       python copy_and_npm.py "C:\\path\\to\\target"

  3) 指定目标路径，且跳过 npm：
       python copy_and_npm.py "C:\\path\\to\\target" --skip-npm

  4) 自定义要执行的 npm 命令：
       python copy_and_npm.py "C:\\path\\to\\target" --npm "npm install" --npm "npm run build"
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# =============================================================================
# 【可修改区域 1】脚本所在目录
# =============================================================================
# __file__ 是当前 .py 文件的路径。用它算出脚本所在文件夹，
# 这样无论你从哪里运行本脚本，相对路径都能正确定位。
SCRIPT_DIR = Path(__file__).resolve().parent

# =============================================================================
# 【可修改区域 2】要复制的本地 JS 文件
# =============================================================================
# 默认：和本脚本同目录下的 script.js
# 你可以改成绝对路径，例如：
#   SOURCE_JS = Path(r"D:\my-projects\hello.js")
# 也可以改成同目录下的其它文件名，例如：
#   SOURCE_JS = SCRIPT_DIR / "my_plugin.js"
SOURCE_JS = SCRIPT_DIR / "script.js"

# =============================================================================
# 【可修改区域 3】复制到目标目录后的文件名
# =============================================================================
# 若保持与源文件同名，用 SOURCE_JS.name 即可。
# 若想改名，例如复制过去叫 index.js：
#   DEST_JS_NAME = "index.js"
DEST_JS_NAME = SOURCE_JS.name

# =============================================================================
# 【可修改区域 4】默认要执行的 npm 命令列表
# =============================================================================
# 每条是一个「完整命令字符串」，会在「目标路径」下执行。
# 常见改法：
#   - 只安装依赖：["npm install"]
#   - 安装后再构建：["npm install", "npm run build"]
#   - 用 pnpm / yarn：["pnpm install", "pnpm run build"]
#   - 不执行任何命令：写成 [] ，或运行时加 --skip-npm
DEFAULT_NPM_COMMANDS = [
    "npm install",
    # "npm run build",  # 需要构建时取消本行注释
]

# =============================================================================
# 【可修改区域 5】npm 超时时间（秒）
# =============================================================================
# 网络慢或依赖多时，可调大，例如 600（10 分钟）。
# 设为 None 表示不限制超时。
NPM_TIMEOUT_SECONDS = 300


def copy_js_to_target(source: Path, target_dir: Path, dest_name: str) -> Path:
    """
    将 source 复制到 target_dir / dest_name。

    参数:
        source:    本地源 JS 文件路径
        target_dir:目标目录（必须已存在，或本函数会自动创建）
        dest_name: 复制后的文件名

    返回:
        复制后的完整路径
    """
    if not source.is_file():
        # 源文件不存在时给出明确提示，方便你检查【可修改区域 2】
        raise FileNotFoundError(
            f"找不到要复制的 JS 文件：{source}\n"
            f"请把文件放好，或修改脚本顶部的 SOURCE_JS。"
        )

    # 目标目录不存在则创建（parents=True 会一并创建上级目录）
    # 若不希望自动创建，删掉下一行，改成：
    #   if not target_dir.is_dir(): raise NotADirectoryError(...)
    target_dir.mkdir(parents=True, exist_ok=True)

    dest = target_dir / dest_name
    # shutil.copy2 会尽量保留修改时间等元数据；若只要内容可用 shutil.copy
    shutil.copy2(source, dest)
    print(f"[OK] 已复制：{source}  ->  {dest}")
    return dest


def run_npm_commands(target_dir: Path, commands: list[str], timeout: int | None) -> None:
    """
    在 target_dir 目录下依次执行 commands。

    说明:
        - 使用 shell=True，这样可以直接写 "npm install" 这种字符串。
          在 Windows 上也能找到 npm.cmd。
        - 若某条命令失败（非 0 退出码），默认立即停止后续命令。
          若希望失败也继续，把 check=True 改成 check=False。
    """
    if not commands:
        print("[INFO] 没有需要执行的 npm 命令，跳过。")
        return

    if not target_dir.is_dir():
        raise NotADirectoryError(f"目标目录不存在，无法执行 npm：{target_dir}")

    for cmd in commands:
        print(f"[RUN] 在 {target_dir} 执行：{cmd}")
        try:
            # cwd=target_dir 表示「在指定路径下」执行
            completed = subprocess.run(
                cmd,
                cwd=str(target_dir),
                shell=True,
                check=True,          # 失败则抛出 CalledProcessError
                timeout=timeout,     # 超时则抛出 TimeoutExpired
                # 若想把输出写进日志文件，可加：
                # stdout=open("npm.log", "a", encoding="utf-8"),
                # stderr=subprocess.STDOUT,
            )
            print(f"[OK] 完成（退出码 {completed.returncode}）：{cmd}")
        except subprocess.TimeoutExpired:
            print(f"[ERROR] 命令超时（>{timeout}s）：{cmd}", file=sys.stderr)
            raise
        except subprocess.CalledProcessError as exc:
            print(
                f"[ERROR] 命令失败（退出码 {exc.returncode}）：{cmd}",
                file=sys.stderr,
            )
            raise


def parse_args() -> argparse.Namespace:
    """解析命令行参数。绝大多数默认值来自脚本顶部的【可修改区域】。"""
    parser = argparse.ArgumentParser(
        description="复制本地 JS 到指定目录，并在该目录执行 npm 命令。",
    )
    parser.add_argument(
        "target",
        nargs="?",                  # 可选：没传就后面交互输入
        default=None,
        help="目标目录路径（JS 复制到这里，npm 也在这里执行）",
    )
    parser.add_argument(
        "--source",
        default=str(SOURCE_JS),
        help=f"要复制的本地 JS 路径（默认：{SOURCE_JS}）",
    )
    parser.add_argument(
        "--dest-name",
        default=DEST_JS_NAME,
        help=f"复制到目标后的文件名（默认：{DEST_JS_NAME}）",
    )
    parser.add_argument(
        "--npm",
        action="append",
        dest="npm_commands",
        default=None,
        help='追加一条 npm 命令，可写多次。例如：--npm "npm install" --npm "npm run build"',
    )
    parser.add_argument(
        "--skip-npm",
        action="store_true",
        help="只复制 JS，不执行任何 npm 命令",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # ---------- 1. 确定目标路径 ----------
    if args.target:
        target_dir = Path(args.target).expanduser().resolve()
    else:
        # 没传参数时，交互式询问（适合双击 / 直接 python 运行）
        raw = input("请输入目标路径：").strip().strip('"').strip("'")
        if not raw:
            print("[ERROR] 目标路径不能为空。", file=sys.stderr)
            return 1
        target_dir = Path(raw).expanduser().resolve()

    source = Path(args.source).expanduser().resolve()
    dest_name = args.dest_name

    # ---------- 2. 复制 JS ----------
    try:
        copy_js_to_target(source, target_dir, dest_name)
    except (OSError, FileNotFoundError) as exc:
        print(f"[ERROR] 复制失败：{exc}", file=sys.stderr)
        return 1

    # ---------- 3. 执行 npm ----------
    if args.skip_npm:
        print("[INFO] 已指定 --skip-npm，跳过 npm。")
        return 0

    # 命令行 --npm 优先；否则用脚本顶部 DEFAULT_NPM_COMMANDS
    commands = args.npm_commands if args.npm_commands is not None else list(DEFAULT_NPM_COMMANDS)

    try:
        run_npm_commands(target_dir, commands, NPM_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[ERROR] npm 执行失败：{exc}", file=sys.stderr)
        return 1

    print("[DONE] 全部完成。")
    return 0


if __name__ == "__main__":
    # Windows 控制台中文乱码时，可取消下面两行注释：
    # sys.stdout.reconfigure(encoding="utf-8")
    # sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
