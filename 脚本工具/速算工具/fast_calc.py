#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
速算练习工具 —— 
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
    "digits_a": 2,              # 左操作数位数: 1~5
    "digits_b": 2,              # 右操作数位数: 1~5
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

def generate_problem(digits_a, digits_b, op):
    """
    生成一道速算题。左右操作数各自独立的位数范围。
    返回 (num1, num2, op_symbol, expected_answer)
    """
    lo_a = 10 ** (digits_a - 1) if digits_a > 1 else 1
    hi_a = (10 ** digits_a) - 1
    lo_b = 10 ** (digits_b - 1) if digits_b > 1 else 1
    hi_b = (10 ** digits_b) - 1

    def retry_if_equal(get_a, get_b, max_tries=8):
        """通用防重复：若 a==b 则重抽，最多 max_tries 次"""
        for _ in range(max_tries):
            a_val = get_a()
            b_val = get_b()
            if a_val != b_val:
                return a_val, b_val
        # 最终还是相同的话，把 b 微调一下
        a_val = get_a()
        b_val = get_b()
        if a_val == b_val:
            b_val = b_val + 1 if b_val < hi_b else b_val - 1
        return a_val, b_val

    if op == "+":
        a, b = retry_if_equal(
            lambda: random.randint(lo_a, hi_a),
            lambda: random.randint(lo_b, hi_b),
        )
        return a, b, OPS_SYMBOL[op], a + b

    elif op == "-":
        # 减法：保证 a > b，且差不小于阈值（避免太简单）
        min_diff = max(lo_a, lo_b) // 3
        for _ in range(10):
            a = random.randint(lo_a, hi_a)
            b = random.randint(lo_b, hi_b)
            if a > b and (a - b) >= min_diff:
                return a, b, OPS_SYMBOL[op], a - b
        # 兜底：先定 b，再从保证 a > b 的范围中抽 a
        b = random.randint(lo_b, hi_b)
        a_lo = max(lo_a, b + max(min_diff, 1))
        if a_lo > hi_a:
            # b 太大，换一个小一点的 b
            b = random.randint(lo_b, max(lo_b, hi_a - min_diff - 1)) if hi_a - min_diff - 1 >= lo_b else lo_b
            a_lo = max(lo_a, b + max(min_diff, 1))
        a = random.randint(a_lo, hi_a) if a_lo <= hi_a else hi_a
        if a <= b:
            a = b + max(min_diff, 1)
        return a, b, OPS_SYMBOL[op], a - b

    elif op == "×":
        # 乘法：各自独立范围（不再硬编码限死）
        a, b = retry_if_equal(
            lambda: random.randint(lo_a, hi_a),
            lambda: random.randint(lo_b, hi_b),
        )
        return a, b, OPS_SYMBOL[op], a * b

    elif op == "÷":
        # 除法：b 从右数范围取，商从左数范围约束；避免商=1
        for _ in range(30):
            b = random.randint(max(lo_b, 2), hi_b)  # 除数至少 2
            q_lo = max((lo_a + b - 1) // b, 2)      # ceil(lo_a/b)，商至少 2
            q_hi = hi_a // b
            if q_lo <= q_hi:
                quotient = random.randint(q_lo, q_hi)
                a = b * quotient
                if lo_a <= a <= hi_a:
                    return a, b, OPS_SYMBOL[op], quotient
        # 兜底：降低 b 的上限，保证能得到合法 a
        for b in range(min(hi_b, hi_a // 2), 1, -1):
            q_lo = max((lo_a + b - 1) // b, 2)
            q_hi = hi_a // b
            if q_lo <= q_hi:
                quotient = random.randint(q_lo, q_hi)
                a = b * quotient
                if lo_a <= a <= hi_a:
                    return a, b, OPS_SYMBOL[op], quotient
        # 最终兜底
        b = max(lo_b, 2)
        quotient = max((lo_a + b - 1) // b, 2)
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
        "digits_a": config.get("digits_a", config.get("digits", 2)),
        "digits_b": config.get("digits_b", config.get("digits", 2)),
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
        print("  ║  时间          位数      运算     题数  正确  正确率 ║")
        print("  ║" + "─" * 50 + "║")
        for r in reversed(history[-20:]):  # 最近20条
            ops_short = "".join(r.get("ops", ["?"])[:3])
            da = r.get("digits_a", r.get("digits", "?"))
            db = r.get("digits_b", r.get("digits", "?"))
            digits_str = f"{da}vs{db}"
            line = (
                f"  ║  {r['time']}  "
                f"{digits_str:<6}  "
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
        da = config.get("digits_a", config.get("digits", 2))
        db = config.get("digits_b", config.get("digits", 2))
        print(f"  ║  [1] 位数        →  {da} 位 vs {db} 位          ║")
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
            da, db = _choose_two_digits(config)
            config["digits_a"] = da
            config["digits_b"] = db
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


def _choose_two_digits(config):
    """分别选择左数和右数的位数，支持快捷预设"""
    da = config.get("digits_a", config.get("digits", 2))
    db = config.get("digits_b", config.get("digits", 2))

    print()
    print("  ┌" + "─" * 38 + "┐")
    print(f"  │  当前: 左数 {da} 位  vs  右数 {db} 位" + " " * (13 - len(str(da)) - len(str(db))) + "│")
    print("  ├" + "─" * 38 + "┤")
    print("  │  快捷预设:                              │")
    print("  │  1 — 相同位数 (与左数一致)              │")
    print("  │  2 — 2位 vs 1位  (如 23 + 8)           │")
    print("  │  3 — 3位 vs 2位  (如 345 + 67)         │")
    print("  │  4 — 4位 vs 2位  (如 5678 ÷ 23)        │")
    print("  │  5 — 自定义                             │")
    print("  └" + "─" * 38 + "┘")
    print()

    presets = {"1": (da, da), "2": (2, 1), "3": (3, 2), "4": (4, 2)}
    while True:
        print("  请选择 (1~5): ", end="", flush=True)
        ch = msvcrt.getch().decode("utf-8", errors="replace")
        print(ch)
        if ch in presets:
            return presets[ch]
        elif ch == "5":
            da = _input_int("  左数位数 (1~5): ", 1, 5, da)
            db = _input_int("  右数位数 (1~5): ", 1, 5, db)
            return da, db
        print("  无效选项，请重新选择")


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

    digits_a = config.get("digits_a", config.get("digits", 2))
    digits_b = config.get("digits_b", config.get("digits", 2))
    ops = config["operations"]
    count = config["problem_count"]
    time_per_q = config["time_per_question"]

    # 打印本轮设置
    ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in ops)
    print()
    print("  ╔" + "═" * 42 + "╗")
    print(f"  ║  位数: {digits_a}位 vs {digits_b}位  |  运算: {ops_display:<10s}║")
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
        num1, num2, op_sym, expected = generate_problem(digits_a, digits_b, op)

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

    # 向后兼容：旧配置中只有 "digits"，自动迁移
    if "digits" in config and "digits_a" not in config:
        config["digits_a"] = config["digits"]
        config["digits_b"] = config["digits"]
        del config["digits"]
        save_json(CONFIG_FILE, config)

    while True:
        clear_screen()
        set_console_title("速算练习工具")

        ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in config["operations"])
        da = config.get("digits_a", 2)
        db = config.get("digits_b", 2)

        print()
        print("  ╔" + "═" * 42 + "╗")
        print("  ║" + " " * 3 + "⚡ 速 算 练 习 工 具 —        用 ⚡" + " " * 3 + "║")
        print("  ╠" + "═" * 42 + "╣")
        print("  ║                                          ║")
        print(f"  ║   当前设置: {da}位vs{db}位 | {ops_display:<10s} | {config['problem_count']:2d}题/{config['time_per_question']}s   ║")
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
    print("  ║  · 入门: 2位vs1位加法, 20题, 限时30s         ║")
    print("  ║  · 进阶: 3位vs2位加减, 15题, 限时20s         ║")
    print("  ║  · 高手: 4位vs2位全混合, 10题, 限时15s       ║")
    print("  ║  · 资料分析: 3位vs1位除法, 15题, 限时20s     ║")
    print("  ║                                            ║")
    print("  ║  技巧提示:                                  ║")
    print("  ║  · 左右数可分别指定位数，模拟真实计算场景      ║")
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
