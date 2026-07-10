#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
速算练习工具 —— 公务员行测专用
================================
运行环境: Windows 11 CMD (需 Python 3.7+)
功能:
  - 可指定位数 (1~5)
  - 加减乘除 + 混合随机
  - 每题实时倒计时，到点响铃
  - 逐字输入，回车判定
  - 统计正确率 / 平均用时 / 超时数
  - 自动保存配置与成绩历史
"""

import os
import sys
import time
import random
import json
import msvcrt
from datetime import datetime

# ── 文件路径 ───────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "calc_config.json")
HISTORY_FILE = os.path.join(BASE_DIR, "calc_history.json")

# ── 默认配置 ───────────────────────────────────────────
DEFAULT_CONFIG = {
    "digits": 2,                # 位数: 1 | 2 | 3 | 4 | 5
    "operations": ["+", "-", "×", "÷"],  # 启用的运算符
    "problem_count": 10,        # 每轮题数: 5~50
    "time_per_question": 30,    # 每题限时(秒): 5~120
}

OPS_SYMBOL = {"+": "+", "-": "-", "×": "×", "÷": "÷"}  # 显示用

# ── 工具函数 ───────────────────────────────────────────

def clear_screen():
    """清屏"""
    os.system("cls")

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def beep():
    """系统蜂鸣（倒计时到点时响）"""
    try:
        import winsound
        winsound.Beep(800, 200)
    except Exception:
        sys.stdout.write("\a")
        sys.stdout.flush()

def set_console_title(text):
    """设置 CMD 窗口标题"""
    sys.stdout.write(f"\033]0;{text}\007")
    sys.stdout.flush()

# ── 题目生成 ───────────────────────────────────────────

def generate_problem(digits, op):
    """
    生成一道速算题。
    返回 (num1, num2, op_symbol, expected_answer)
    """
    lo = 10 ** (digits - 1) if digits > 1 else 1
    hi = (10 ** digits) - 1

    if op == "+":
        a = random.randint(lo, hi)
        b = random.randint(lo, hi)
        return a, b, OPS_SYMBOL[op], a + b

    elif op == "-":
        a = random.randint(lo, hi)
        b = random.randint(lo, hi)
        if a < b:
            a, b = b, a
        return a, b, OPS_SYMBOL[op], a - b

    elif op == "×":
        # 控制乘积范围，避免过于庞大的数
        if digits <= 2:
            a = random.randint(lo, hi)
            b = random.randint(lo, hi)
        elif digits == 3:
            a = random.randint(lo, min(hi, 500))
            b = random.randint(lo, min(hi, 200))
        else:
            a = random.randint(lo, min(hi, 2000))
            b = random.randint(2, min(hi, 50))
        return a, b, OPS_SYMBOL[op], a * b

    elif op == "÷":
        # 保证整除
        if digits == 1:
            b = random.randint(1, 9)
            quotient = random.randint(1, 9)
        else:
            b = random.randint(2, min(hi, 99))
            quotient = random.randint(lo // b if lo // b > 0 else 1, hi // b)
        a = b * quotient
        return a, b, OPS_SYMBOL[op], quotient

    return 0, 0, "?", 0


def format_problem(num1, num2, op_sym):
    """格式化题目显示"""
    return f"{num1} {op_sym} {num2} = ?"


# ── 带倒计时的输入 ─────────────────────────────────────

def input_with_timer(timeout_sec):
    """
    读取用户一行输入，同时显示实时倒计时。
    返回 (answer_str, is_timeout, elapsed_sec)

    使用 msvcrt 逐字符读取 + ANSI 转义序列原地更新计时器。
    """
    # 先打印计时器行 + 输入提示行
    sys.stdout.write("  ⏱ 剩余 {:2d} 秒\n".format(timeout_sec))
    sys.stdout.write("  你的答案: ")
    sys.stdout.flush()

    answer_chars = []
    start_time = time.time()
    last_display = timeout_sec

    while True:
        elapsed = time.time() - start_time
        remaining = max(0, timeout_sec - elapsed)
        remaining_disp = int(remaining)

        # ── 每秒更新一次计时器显示 ──
        if remaining_disp != last_display:
            last_display = remaining_disp
            # 保存光标 → 上移 1 行 → 清行 → 写新计时器 → 恢复光标
            sys.stdout.write(
                f"\033[s"                              # 保存光标位置
                f"\033[1A"                             # 上移 1 行
                f"\033[K"                              # 清行
                f"  ⏱ 剩余 {remaining_disp:2d} 秒"    # 新内容
                f"\033[u"                              # 恢复光标
            )
            sys.stdout.flush()

        # ── 超时判断 ──
        if remaining <= 0:
            sys.stdout.write("\n\n  ⏰ 时间到！\n")
            sys.stdout.flush()
            beep()
            time.sleep(0.5)
            return "".join(answer_chars), True, elapsed

        # ── 键盘输入 ──
        if msvcrt.kbhit():
            ch = msvcrt.getch()

            # 回车
            if ch == b"\r":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(answer_chars), False, elapsed

            # 退格
            elif ch == b"\x08":
                if answer_chars:
                    answer_chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            # 方向键等功能键（双字节前缀 0xE0）
            elif ch == b"\xe0":
                msvcrt.getch()   # 吃掉第二个字节
                continue

            # Ctrl+C
            elif ch == b"\x03":
                raise KeyboardInterrupt

            # 负号 / 数字
            elif ch == b"-" or ch == b"+" or (b"0" <= ch <= b"9"):
                answer_chars.append(ch.decode("utf-8", errors="replace"))
                sys.stdout.write(ch.decode("utf-8", errors="replace"))
                sys.stdout.flush()

        # 防止 CPU 空转
        time.sleep(0.015)


# ── 单题练习 ───────────────────────────────────────────

def play_one_problem(num1, num2, op_sym, expected, timeout_sec, idx, total):
    """
    练习一道题。返回结果字典。
    """
    # 设置窗口标题
    set_console_title(f"速算练习 - 第 {idx}/{total} 题")

    # 打印题目区
    print()
    print("  ┌" + "─" * 42 + "┐")
    print(f"  │  第 {idx}/{total} 题" + " " * 27 + "│")
    print("  ├" + "─" * 42 + "┤")
    print(f"  │" + " " * 42 + "│")
    problem_text = format_problem(num1, num2, op_sym)
    padding = (38 - len(problem_text)) // 2
    print(f"  │  " + " " * padding + problem_text + " " * (38 - padding - len(problem_text)) + "│")
    print(f"  │" + " " * 42 + "│")
    print("  └" + "─" * 42 + "┘")

    # 读取答案（带倒计时）
    answer_str, is_timeout, elapsed = input_with_timer(timeout_sec)

    # 判定结果
    if is_timeout:
        correct = False
        user_answer = None
    else:
        try:
            user_answer = int(answer_str.strip())
            correct = (user_answer == expected)
        except ValueError:
            user_answer = None
            correct = False

    return {
        "num1": num1,
        "num2": num2,
        "op": op_sym,
        "expected": expected,
        "user_answer": user_answer,
        "answer_str": answer_str,
        "correct": correct,
        "timeout": is_timeout,
        "elapsed_sec": round(elapsed, 2),
    }


# ── 反馈显示 ───────────────────────────────────────────

def show_feedback(result):
    """显示单题反馈"""
    if result["timeout"]:
        print("  ❌ 超时未答！")
        print(f"  正确答案: {result['expected']}")
    elif result["correct"]:
        elapsed = result["elapsed_sec"]
        print(f"  ✅ 正确！ ({elapsed:.1f}s)")
    else:
        print(f"  ❌ 错误！")
        print(f"  你的答案: {result['user_answer']}")
        print(f"  正确答案: {result['expected']}")

    print()
    print("  按任意键继续...")

    # 等待按键
    while msvcrt.kbhit():
        msvcrt.getch()
    msvcrt.getch()


# ── 成绩统计 ───────────────────────────────────────────

def show_summary(results, total_time, config):
    """显示本轮练习总结"""
    clear_screen()
    total = len(results)
    correct_count = sum(1 for r in results if r["correct"])
    timeout_count = sum(1 for r in results if r["timeout"])
    wrong_count = total - correct_count - timeout_count

    answered = [r for r in results if not r["timeout"]]
    avg_time = (
        sum(r["elapsed_sec"] for r in answered) / len(answered)
        if answered
        else config["time_per_question"]
    )

    accuracy = correct_count / total * 100 if total > 0 else 0

    print()
    print("  ╔" + "═" * 42 + "╗")
    print("  ║" + " " * 14 + "练 习 结 束" + " " * 17 + "║")
    print("  ╠" + "═" * 42 + "╣")
    print(f"  ║  总题数: {total:<4}                         ║")
    print(f"  ║  正确:   {correct_count:<4}  ✅                    ║")
    print(f"  ║  错误:   {wrong_count:<4}  ❌                    ║")
    print(f"  ║  超时:   {timeout_count:<4}  ⏰                    ║")
    print(f"  ║  正确率: {accuracy:.1f}%                       ║")
    print(f"  ║  平均用时: {avg_time:.1f}s                      ║")
    print(f"  ║  总用时:   {total_time:.0f}s                      ║")
    print("  ╚" + "═" * 42 + "╝")
    print()

    # 星级评价
    stars = ""
    if accuracy >= 95:
        stars = "⭐⭐⭐⭐⭐ 神算子！"
    elif accuracy >= 85:
        stars = "⭐⭐⭐⭐ 非常优秀"
    elif accuracy >= 70:
        stars = "⭐⭐⭐ 继续加油"
    elif accuracy >= 50:
        stars = "⭐⭐ 还需努力"
    else:
        stars = "⭐ 多多练习"

    print(f"  {stars}")
    print()

    # 保存历史
    save_history(results, total_time, config, accuracy)

    print("  按任意键返回菜单...")
    while msvcrt.kbhit():
        msvcrt.getch()
    msvcrt.getch()


def save_history(results, total_time, config, accuracy):
    """追加成绩到历史文件"""
    history = load_json(HISTORY_FILE, [])
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "digits": config["digits"],
        "ops": config["operations"],
        "total": len(results),
        "correct": sum(1 for r in results if r["correct"]),
        "accuracy": round(accuracy, 1),
        "total_sec": round(total_time, 0),
    }
    history.append(record)
    # 只保留最近 50 条
    if len(history) > 50:
        history = history[-50:]
    save_json(HISTORY_FILE, history)


# ── 成绩历史查看 ───────────────────────────────────────

def show_history():
    """显示历史成绩"""
    clear_screen()
    history = load_json(HISTORY_FILE, [])

    print()
    print("  ╔" + "═" * 52 + "╗")
    print("  ║" + " " * 18 + "历 史 成 绩" + " " * 18 + "║")
    print("  ╠" + "═" * 52 + "╣")

    if not history:
        print("  ║" + " " * 17 + "暂无记录" + " " * 19 + "║")
    else:
        print("  ║  时间          位数  运算     题数  正确  正确率 ║")
        print("  ║" + "─" * 50 + "║")
        for r in reversed(history[-20:]):  # 最近20条
            ops_short = "".join(r.get("ops", ["?"])[:3])
            line = (
                f"  ║  {r['time']}  "
                f"{r['digits']}位  "
                f"{ops_short:<6}  "
                f"{r['total']:2d}题  "
                f"{r['correct']:2d}✓  "
                f"{r['accuracy']:5.1f}% ║"
            )
            print(line)

    print("  ╚" + "═" * 52 + "╝")
    print()
    print("  按任意键返回菜单...")
    while msvcrt.kbhit():
        msvcrt.getch()
    msvcrt.getch()


# ── 设置菜单 ───────────────────────────────────────────

def settings_menu(config):
    """修改设置的子菜单"""
    while True:
        clear_screen()
        ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in config["operations"])

        print()
        print("  ╔" + "═" * 42 + "╗")
        print("  ║" + " " * 16 + "设   置" + " " * 17 + "║")
        print("  ╠" + "═" * 42 + "╣")
        print(f"  ║  [1] 位数        →  {config['digits']} 位整数        ║")
        print(f"  ║  [2] 运算符      →  {ops_display:<20s}   ║")
        print(f"  ║  [3] 题目数量    →  {config['problem_count']:2d} 题              ║")
        print(f"  ║  [4] 每题限时    →  {config['time_per_question']:3d} 秒            ║")
        print("  ║                                          ║")
        print("  ║  [0] 返回主菜单                           ║")
        print("  ╚" + "═" * 42 + "╝")
        print()
        print("  请选择 [0-4]: ", end="", flush=True)

        ch = msvcrt.getch().decode("utf-8", errors="replace")
        print(ch)

        if ch == "0":
            break
        elif ch == "1":
            config["digits"] = _choose_digits()
        elif ch == "2":
            config["operations"] = _choose_operations()
        elif ch == "3":
            config["problem_count"] = _input_int(
                "题目数量 (5~50): ", 5, 50, config["problem_count"]
            )
        elif ch == "4":
            config["time_per_question"] = _input_int(
                "每题限时 / 秒 (5~120): ", 5, 120, config["time_per_question"]
            )

    save_json(CONFIG_FILE, config)


def _choose_digits():
    """选位数"""
    print("\n  可选的位数:")
    print("  1 — 1 位 (1~9)")
    print("  2 — 2 位 (10~99)")
    print("  3 — 3 位 (100~999)")
    print("  4 — 4 位 (1000~9999)")
    print("  5 — 5 位 (10000~99999)")
    print()
    return _input_int("  请选择位数 (1~5): ", 1, 5, 2)


def _choose_operations():
    """选运算符"""
    print("\n  可选的运算符:")
    print("  1 — 仅加法  +")
    print("  2 — 仅减法  -")
    print("  3 — 仅乘法  ×")
    print("  4 — 仅除法  ÷")
    print("  5 — 加减混合")
    print("  6 — 乘除混合")
    print("  7 — 全部混合 (推荐)")
    print()

    mapping = {
        "1": ["+"],
        "2": ["-"],
        "3": ["×"],
        "4": ["÷"],
        "5": ["+", "-"],
        "6": ["×", "÷"],
        "7": ["+", "-", "×", "÷"],
    }

    while True:
        print("  请选择 (1~7): ", end="", flush=True)
        ch = msvcrt.getch().decode("utf-8", errors="replace")
        print(ch)
        if ch in mapping:
            return mapping[ch]
        print("  无效选项，请重新选择")


def _input_int(prompt, lo, hi, default):
    """读取一个范围内的整数"""
    while True:
        print(f"  {prompt}", end="", flush=True)
        try:
            val = input().strip()
            if val == "":
                return default
            val = int(val)
            if lo <= val <= hi:
                return val
            print(f"  请输入 {lo}~{hi} 之间的整数")
        except ValueError:
            print(f"  请输入一个整数")


# ── 主练习流程 ─────────────────────────────────────────

def run_practice(config):
    """执行一轮练习"""
    clear_screen()

    digits = config["digits"]
    ops = config["operations"]
    count = config["problem_count"]
    time_per_q = config["time_per_question"]

    # 打印本轮设置
    ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in ops)
    print()
    print("  ╔" + "═" * 42 + "╗")
    print(f"  ║  位数: {digits} 位  |  运算: {ops_display:<18s}║")
    print(f"  ║  题数: {count:2d}    |  每题限时: {time_per_q} 秒          ║")
    print("  ╚" + "═" * 42 + "╝")
    print()
    print("  按任意键开始...")
    while msvcrt.kbhit():
        msvcrt.getch()
    msvcrt.getch()

    results = []
    round_start = time.time()

    for i in range(count):
        clear_screen()

        # 随机选择运算符
        op = random.choice(ops)
        # 生成题目
        num1, num2, op_sym, expected = generate_problem(digits, op)

        # 练习
        result = play_one_problem(num1, num2, op_sym, expected, time_per_q,
                                  idx=i + 1, total=count)
        results.append(result)

        # 反馈
        show_feedback(result)

    round_end = time.time()
    total_time = round_end - round_start

    # 显示总结
    show_summary(results, total_time, config)


# ── 主菜单 ─────────────────────────────────────────────

def main_menu():
    """主菜单循环"""
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)

    while True:
        clear_screen()
        set_console_title("速算练习工具 - 行测专用")

        ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in config["operations"])

        print()
        print("  ╔" + "═" * 42 + "╗")
        print("  ║" + " " * 3 + "⚡ 速 算 练 习 工 具 — 行 测 专 用 ⚡" + " " * 3 + "║")
        print("  ╠" + "═" * 42 + "╣")
        print("  ║                                          ║")
        print(f"  ║   当前设置: {config['digits']}位 | {ops_display:<12s} | {config['problem_count']:2d}题/{config['time_per_question']}s   ║")
        print("  ║                                          ║")
        print("  ║   [1] 开始练习                            ║")
        print("  ║   [2] 修改设置                            ║")
        print("  ║   [3] 历史成绩                            ║")
        print("  ║   [4] 使用说明                            ║")
        print("  ║   [0] 退出                                ║")
        print("  ║                                          ║")
        print("  ╚" + "═" * 42 + "╝")
        print()
        print("  请选择 [0-4]: ", end="", flush=True)

        ch = msvcrt.getch().decode("utf-8", errors="replace")
        print(ch)

        if ch == "0":
            print()
            print("  再见！祝你上岸 🎉")
            print()
            time.sleep(1)
            break
        elif ch == "1":
            run_practice(config)
        elif ch == "2":
            settings_menu(config)
        elif ch == "3":
            show_history()
        elif ch == "4":
            show_help()


def show_help():
    """使用说明"""
    clear_screen()
    print()
    print("  ╔" + "═" * 52 + "╗")
    print("  ║" + " " * 19 + "使 用 说 明" + " " * 18 + "║")
    print("  ╠" + "═" * 52 + "╣")
    print("  ║                                            ║")
    print("  ║  行测资料分析 / 数量关系中，速算是基本功。     ║")
    print("  ║  本工具模拟考场紧迫感，训练快速心算能力。       ║")
    print("  ║                                            ║")
    print("  ║  建议设置:                                  ║")
    print("  ║  · 入门: 2位加法, 20题, 限时30s              ║")
    print("  ║  · 进阶: 3位加减混合, 15题, 限时20s          ║")
    print("  ║  · 高手: 4位全混合, 10题, 限时15s            ║")
    print("  ║                                            ║")
    print("  ║  技巧提示:                                  ║")
    print("  ║  · 除法保证整除，答案一定是整数               ║")
    print("  ║  · 可输入负号 - 表示负数答案                  ║")
    print("  ║  · 退格键可修改输入                          ║")
    print("  ║  · 时间是压力也是动力，稳定心态最重要          ║")
    print("  ║                                            ║")
    print("  ╚" + "═" * 52 + "╝")
    print()
    print("  按任意键返回菜单...")
    while msvcrt.kbhit():
        msvcrt.getch()
    msvcrt.getch()


# ── 入口 ───────────────────────────────────────────────

if __name__ == "__main__":
    # 启用 Windows CMD 的 ANSI/VT100 支持
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass  # 忽略，老 win10 也可能自动支持

    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n  已退出。加油备考！\n")
    except Exception as e:
        print(f"\n  出错了: {e}\n")
        print("  按任意键退出...")
        msvcrt.getch()
