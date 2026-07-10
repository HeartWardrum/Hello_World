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
ERROR_FILE = os.path.join(BASE_DIR, "calc_errors.json")

# ── 默认配置 ───────────────────────────────────────────
DEFAULT_CONFIG = {
    "digits_a": 2,              # 左操作数位数: 1~5 或 [min,max]
    "digits_b": 2,              # 右操作数位数: 1~5 或 [min,max]
    "operations": ["+", "-", "×", "÷"],  # 启用的运算符
    "problem_count": 10,        # 每轮题数: 5~50
    "time_per_question": 30,    # 每题限时(秒): 5~120
    "decimal_places": 0,        # 小数位数: 0(整数) | 1 | 2
}

OPS_SYMBOL = {"+": "+", "-": "-", "×": "×", "÷": "÷", "%": "%"}  # 显示用

class QuitToMenu(Exception):
    """在练习中按 ESC 抛此异常，回到主菜单"""
    pass

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

def resolve_digits(spec):
    """解析位数配置：int 为固定，list [min,max] 为随机范围"""
    if isinstance(spec, list) and len(spec) == 2:
        return random.randint(spec[0], spec[1])
    return spec

def digits_display(spec):
    """位数配置的可读字符串"""
    if isinstance(spec, list) and len(spec) == 2:
        return f"{spec[0]}~{spec[1]}位"
    return f"{spec}位"

def int_range(digits, scale):
    """返回缩放后的整数范围 [lo, hi]"""
    lo = (10 ** (digits - 1) if digits > 1 else 2) * scale  # 1位数不用1
    hi = ((10 ** digits) - 1) * scale + (scale - 1)
    return lo, hi

def fmt_dec(val_int, d):
    """将内部缩放整数格式化为小数字符串"""
    if d == 0:
        return str(val_int)
    neg = val_int < 0
    s = str(abs(val_int))
    s = s.zfill(d + 1)
    int_part = s[:-d] or "0"
    dec_part = s[-d:]
    sign = "-" if neg else ""
    return f"{sign}{int_part}.{dec_part}"

def parse_decimal_input(answer_str, d):
    """解析用户输入：支持 '12.34', '.5', '12', '-3.14' 等，返回缩放整数或 None"""
    s = answer_str.strip()
    if not s:
        return None
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if "." in s:
        parts = s.split(".")
        if len(parts) != 2:
            return None
        int_s, dec_s = parts
        dec_s = (dec_s + "0" * d)[:d]  # 补零或截断
    else:
        int_s, dec_s = s, "0" * d
    # 去掉前导零（但保留至少一位数字）
    int_s = int_s.lstrip("0") or "0"
    try:
        val = int(int_s + dec_s)
        return -val if neg else val
    except ValueError:
        return None

# ── 题目生成 ───────────────────────────────────────────

def generate_problem(digits_a, digits_b, op, decimal_places=0):
    """
    生成一道速算题。内部全部使用缩放整数（×10^d）。
    统一返回 5 元组:
      (num1_int, num2_int, op_symbol, answer_int, answer_decimal_places)
    其中 answer_decimal_places 用于格式化答案和解析用户输入。
    """
    da = resolve_digits(digits_a)
    db = resolve_digits(digits_b)
    scale = 10 ** decimal_places
    ans_d = decimal_places  # 默认答案小数位

    lo_a, hi_a = int_range(da, scale)
    lo_b, hi_b = int_range(db, scale)

    def retry_if_equal(get_a, get_b, hi_b_val, max_tries=8):
        for _ in range(max_tries):
            av = get_a()
            bv = get_b()
            if av != bv:
                return av, bv
        av = get_a()
        bv = get_b()
        if av == bv:
            bv = bv + 1 if bv < hi_b_val else bv - 1
        return av, bv

    if op == "+":
        a, b = retry_if_equal(
            lambda: random.randint(lo_a, hi_a),
            lambda: random.randint(lo_b, hi_b), hi_b,
        )
        return a, b, OPS_SYMBOL[op], a + b, ans_d

    elif op == "-":
        min_diff = max(lo_a, lo_b) // 3
        for _ in range(10):
            a = random.randint(lo_a, hi_a)
            b = random.randint(lo_b, hi_b)
            if a > b and (a - b) >= min_diff:
                return a, b, OPS_SYMBOL[op], a - b, ans_d
        b = random.randint(lo_b, hi_b)
        a_lo = max(lo_a, b + max(min_diff, 1))
        if a_lo > hi_a:
            b = random.randint(lo_b, max(lo_b, hi_a - min_diff - 1)) if hi_a - min_diff - 1 >= lo_b else lo_b
            a_lo = max(lo_a, b + max(min_diff, 1))
        a = random.randint(a_lo, hi_a) if a_lo <= hi_a else hi_a
        if a <= b:
            a = b + max(min_diff, 1)
        return a, b, OPS_SYMBOL[op], a - b, ans_d

    elif op == "×":
        if decimal_places > 0 and random.random() < 0.5:
            # 右数为整数（无缩放）
            lo_b_int, hi_b_int = int_range(db, 1)
            b = random.randint(lo_b_int, hi_b_int)
            a = random.randint(lo_a, hi_a)
            if a == b:
                b = b + 1 if b < hi_b_int else b - 1
            return a, b, OPS_SYMBOL[op], a * b, ans_d
        else:
            # 右数同为 d 位小数 → 答案 2d 位小数
            a, b = retry_if_equal(
                lambda: random.randint(lo_a, hi_a),
                lambda: random.randint(lo_b, hi_b), hi_b,
            )
            return a, b, OPS_SYMBOL[op], a * b, ans_d * 2

    elif op == "÷":
        # 除法不强制整除，答案四舍五入到 N 位小数（N >= 2）
        ans_d = max(decimal_places, 2)
        scale_div = 10 ** ans_d
        lo_b_int, hi_b_int = int_range(db, 1)
        for _ in range(30):
            b = random.randint(max(lo_b_int, 2), hi_b_int)
            a = random.randint(lo_a, hi_a)
            # 四舍五入：round(a/b * scale_div) = (a*scale_div + b//2) // b
            expected = (a * scale_div + b // 2) // b
            if expected > 0 and a != b:
                return a, b, OPS_SYMBOL[op], expected, ans_d
        # 兜底
        b = max(lo_b_int, 2)
        a = random.randint(lo_a, hi_a)
        expected = (a * scale_div + b // 2) // b
        return a, b, OPS_SYMBOL[op], max(expected, 1), ans_d

    elif op == "%":
        # A × B% = ?  答案 = A × B / 100，四舍五入
        ans_d = max(decimal_places, 2)
        scale_pct = 10 ** ans_d
        b = random.randint(2, 99)  # 百分数 2~99，避免 1 和 100
        a = random.randint(lo_a, hi_a)
        if a == b:
            b = b + 1 if b < 99 else b - 1
        # round(a * b / 100 * scale_pct) = (a*b*scale_pct + 50) // 100
        expected = (a * b * scale_pct + 50) // 100
        return a, b, OPS_SYMBOL[op], expected, ans_d

    return 0, 0, "?", 0, 0


def format_problem(num1, num2, op_sym, dec_places=0, right_dec_places=None):
    """
    格式化题目显示。
    dec_places: 左操作数小数位数
    right_dec_places: 右操作数小数位数（None=与左相同; 0=整数）
    """
    d = dec_places
    if op_sym == "%":
        # 百分数：A × B% = ?
        return f"{fmt_dec(num1, d)} × {num2}% = ?"
    rd = d if right_dec_places is None else right_dec_places
    if d == 0 and rd == 0:
        return f"{num1} {op_sym} {num2} = ?"
    return f"{fmt_dec(num1, d)} {op_sym} {fmt_dec(num2, rd)} = ?"


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

            # ESC → 退出到主菜单
            elif ch == b"\x1b":
                sys.stdout.write("\n\n  已退出当前练习\n")
                sys.stdout.flush()
                time.sleep(0.4)
                raise QuitToMenu()

            # 负号 / 小数点 / 数字
            elif ch == b"-" or ch == b"+" or ch == b"." or (b"0" <= ch <= b"9"):
                # 只允许一个小数点
                if ch == b"." and b"." in answer_chars:
                    continue
                answer_chars.append(ch.decode("utf-8", errors="replace"))
                sys.stdout.write(ch.decode("utf-8", errors="replace"))
                sys.stdout.flush()

        # 防止 CPU 空转
        time.sleep(0.015)


# ── 单题练习 ───────────────────────────────────────────

def play_one_problem(num1, num2, op_sym, expected, timeout_sec, idx, total,
                     dec_places=0, ans_dec_places=0, right_dec_places=None,
                     is_error_retry=False):
    """
    练习一道题。返回结果字典。
    dec_places: 左操作数小数位数
    ans_dec_places: 答案小数位数
    right_dec_places: 右操作数小数位数（None=同左, 0=整数）
    is_error_retry: 是否为错题重练模式
    """
    label = "错题重练" if is_error_retry else "速算练习"
    set_console_title(f"{label} - 第 {idx}/{total} 题")

    # 打印题目区
    problem_text = format_problem(num1, num2, op_sym, dec_places, right_dec_places)
    print()
    print("  ┌" + "─" * 42 + "┐")
    tag = "  错题重练" if is_error_retry else "  速算练习"
    print(f"  │{tag} 第 {idx}/{total} 题" + " " * (27 - len(tag) + 4) + "│")
    print("  ├" + "─" * 42 + "┤")
    print(f"  │" + " " * 42 + "│")
    padding = (38 - len(problem_text)) // 2
    print(f"  │  " + " " * padding + problem_text + " " * (38 - padding - len(problem_text)) + "│")
    print(f"  │" + " " * 42 + "│")
    print("  └" + "─" * 42 + "┘")

    # 读取答案（带倒计时）
    answer_str, is_timeout, elapsed = input_with_timer(timeout_sec)

    # 判定结果（使用小数解析）
    if is_timeout:
        correct = False
        user_answer_int = None
    else:
        user_answer_int = parse_decimal_input(answer_str, ans_dec_places)
        correct = (user_answer_int is not None and user_answer_int == expected)

    result = {
        "num1": num1,
        "num2": num2,
        "op": op_sym,
        "expected": expected,
        "user_answer": user_answer_int,
        "answer_str": answer_str,
        "correct": correct,
        "timeout": is_timeout,
        "elapsed_sec": round(elapsed, 2),
        "dec_places": dec_places,
        "ans_dec_places": ans_dec_places,
        "right_dec_places": right_dec_places,
    }
    return result


# ── 反馈显示 ───────────────────────────────────────────

def show_feedback(result):
    """显示单题反馈"""
    ans_d = result.get("ans_dec_places", 0)
    exp_disp = fmt_dec(result["expected"], ans_d)
    if result["timeout"]:
        print(f"  ❌ 超时未答！")
        print(f"  正确答案: {exp_disp}")
    elif result["correct"]:
        elapsed = result["elapsed_sec"]
        print(f"  ✅ 正确！ ({elapsed:.1f}s)")
    else:
        user_disp = fmt_dec(result["user_answer"], ans_d) if result["user_answer"] is not None else result["answer_str"]
        print(f"  ❌ 错误！")
        print(f"  你的答案: {user_disp}")
        print(f"  正确答案: {exp_disp}")

    print()
    print("  按任意键继续 (ESC 退出)...")

    # 等待按键
    while msvcrt.kbhit():
        msvcrt.getch()
    ch = msvcrt.getch()
    if ch == b"\x1b":
        raise QuitToMenu()


# ── 错题本 ─────────────────────────────────────────────

def add_to_error_book(result, config):
    """将答错/超时的题目加入错题本，自动查重"""
    errors = load_json(ERROR_FILE, [])
    # 查重：相同 (num1, num2, op, decimal_places) 视为同一题
    key = (result["num1"], result["num2"], result["op"],
           result.get("dec_places", 0))
    for e in errors:
        ek = (e["num1"], e["num2"], e["op"], e.get("decimal_places", 0))
        if ek == key and not e.get("solved", False):
            e["retry_count"] = e.get("retry_count", 0) + 1
            e["last_retry"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(ERROR_FILE, errors)
            return
    # 新错题
    errors.append({
        "num1": result["num1"],
        "num2": result["num2"],
        "op": result["op"],
        "expected": result["expected"],
        "user_answer": result.get("answer_str", ""),
        "timeout": result["timeout"],
        "time_limit": config["time_per_question"],
        "digits_a": config.get("digits_a", 2),
        "digits_b": config.get("digits_b", 2),
        "decimal_places": result.get("dec_places", 0),
        "ans_dec_places": result.get("ans_dec_places", 0),
        "right_dec_places": result.get("right_dec_places"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "retry_count": 0,
        "solved": False,
    })
    save_json(ERROR_FILE, errors)


def mark_error_solved(error_entry):
    """标记错题已解决"""
    errors = load_json(ERROR_FILE, [])
    key = (error_entry["num1"], error_entry["num2"], error_entry["op"],
           error_entry.get("decimal_places", 0))
    for e in errors:
        ek = (e["num1"], e["num2"], e["op"], e.get("decimal_places", 0))
        if ek == key:
            e["solved"] = True
            save_json(ERROR_FILE, errors)
            return


def increment_error_retry(error_entry):
    """增加错题重试次数"""
    errors = load_json(ERROR_FILE, [])
    key = (error_entry["num1"], error_entry["num2"], error_entry["op"],
           error_entry.get("decimal_places", 0))
    for e in errors:
        ek = (e["num1"], e["num2"], e["op"], e.get("decimal_places", 0))
        if ek == key:
            e["retry_count"] = e.get("retry_count", 0) + 1
            e["last_retry"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(ERROR_FILE, errors)
            return


def get_unsolved_error_count():
    """获取未解决的错题数"""
    errors = load_json(ERROR_FILE, [])
    return sum(1 for e in errors if not e.get("solved", False))


def clear_solved_errors():
    """清除已解决的错题"""
    errors = load_json(ERROR_FILE, [])
    errors = [e for e in errors if not e.get("solved", False)]
    save_json(ERROR_FILE, errors)


def show_error_summary(results, total_time):
    """错题重练总结"""
    clear_screen()
    total = len(results)
    correct_count = sum(1 for r in results if r["correct"])
    solved = correct_count
    remaining = total - solved
    accuracy = correct_count / total * 100 if total > 0 else 0

    print()
    print("  ╔" + "═" * 42 + "╗")
    print("  ║" + " " * 12 + "错题重练 结 束" + " " * 17 + "║")
    print("  ╠" + "═" * 42 + "╣")
    print(f"  ║  总题数: {total:<4}                         ║")
    print(f"  ║  已解决: {solved:<4}  ✅                    ║")
    print(f"  ║  未解决: {remaining:<4}  ❌                    ║")
    print(f"  ║  正确率: {accuracy:.1f}%                       ║")
    print(f"  ║  总用时: {total_time:.0f}s                      ║")
    print("  ╚" + "═" * 42 + "╝")
    print()

    unsolved = get_unsolved_error_count()
    if unsolved > 0:
        print(f"  还有 {unsolved} 道错题待练习。")
    else:
        print(f"  全部错题已解决！🎉")
    print()

    print("  按任意键返回菜单...")
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
        dp = config.get("decimal_places", 0)
        dec_label = ["纯整数", "1 位小数", "2 位小数"][dp] if dp <= 2 else f"{dp}位小数"
        print(f"  ║  [1] 位数        →  {digits_display(da)} vs {digits_display(db):<8s}     ║")
        print(f"  ║  [2] 运算符      →  {ops_display:<20s}   ║")
        print(f"  ║  [3] 题目数量    →  {config['problem_count']:2d} 题              ║")
        print(f"  ║  [4] 每题限时    →  {config['time_per_question']:3d} 秒            ║")
        print(f"  ║  [5] 小数位数    →  {dec_label:<20s}   ║")
        print("  ║                                          ║")
        print("  ║  [0] 返回主菜单                           ║")
        print("  ╚" + "═" * 42 + "╝")
        print()
        print("  请选择 [0-5]: ", end="", flush=True)

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
        elif ch == "5":
            config["decimal_places"] = _choose_decimal_places()

    save_json(CONFIG_FILE, config)


def _choose_two_digits(config):
    """分别选择左数和右数的位数，支持固定/随机/自定义"""
    da = config.get("digits_a", config.get("digits", 2))
    db = config.get("digits_b", config.get("digits", 2))

    print()
    print("  ┌" + "─" * 40 + "┐")
    print(f"  │  当前: 左数 {digits_display(da):<8s}  右数 {digits_display(db):<8s} │")
    print("  ├" + "─" * 40 + "┤")
    print("  │  快捷预设:                              │")
    print("  │  1 — 相同位数                            │")
    print("  │  2 — 2位  vs 1位  (如 23 + 8)           │")
    print("  │  3 — 3位  vs 2位  (如 345 + 67)         │")
    print("  │  4 — 4位  vs 2位  (如 5678 / 23)        │")
    print("  │  5 — 随机 1~3 位（相同）                 │")
    print("  │  6 — 随机 2~4 位（相同）                 │")
    print("  │  7 — 自定义                              │")
    print("  └" + "─" * 40 + "┘")
    print()

    presets = {
        "1": (da if isinstance(da, int) else da[0], da if isinstance(da, int) else da[0]),
        "2": (2, 1),
        "3": (3, 2),
        "4": (4, 2),
        "5": ([1, 3], [1, 3]),
        "6": ([2, 4], [2, 4]),
    }
    while True:
        print("  请选择 (1~7): ", end="", flush=True)
        ch = msvcrt.getch().decode("utf-8", errors="replace")
        print(ch)
        if ch in presets:
            return presets[ch]
        elif ch == "7":
            print("\n  左数设置:")
            da = _choose_one_digit_spec(da)
            print("  右数设置:")
            db = _choose_one_digit_spec(db)
            return da, db
        print("  无效选项，请重新选择")


def _choose_one_digit_spec(current):
    """选择单个操作数的位数规格：固定值或随机范围"""
    cur_str = digits_display(current)
    print(f"  当前: {cur_str}")
    print("  1 — 固定位数")
    print("  2 — 随机范围 (如 1~3)")
    print("  请选择: ", end="", flush=True)
    ch = msvcrt.getch().decode("utf-8", errors="replace")
    print(ch)
    if ch == "2":
        lo = _input_int("  最小位数 (1~5): ", 1, 5, 1)
        hi = _input_int("  最大位数 (1~5): ", lo, 5, 3)
        return [lo, hi]
    else:
        if isinstance(current, list):
            current = current[0]
        return _input_int("  位数 (1~5): ", 1, 5, current if isinstance(current, int) else 2)


def _choose_decimal_places():
    """选择小数位数"""
    print("\n  小数位数设置:")
    print("  0 — 纯整数（无小数）")
    print("  1 — 1 位小数（如 12.3）")
    print("  2 — 2 位小数（如 12.34）")
    print()
    return _input_int("  请选择 (0~2): ", 0, 2, 0)


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
    print("  8 — 百分数 % (A × B%)")
    print()

    mapping = {
        "1": ["+"],
        "2": ["-"],
        "3": ["×"],
        "4": ["÷"],
        "5": ["+", "-"],
        "6": ["×", "÷"],
        "7": ["+", "-", "×", "÷"],
        "8": ["%"],
    }

    while True:
        print("  请选择 (1~8): ", end="", flush=True)
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

def run_practice(config, error_problems=None):
    """执行一轮练习。error_problems 不为 None 时进入错题重练模式。"""
    clear_screen()

    is_error_mode = error_problems is not None
    if is_error_mode:
        problems = error_problems
        count = len(problems)
        digits_a = config.get("digits_a", 2)
        digits_b = config.get("digits_b", 2)
        time_per_q = config["time_per_question"]
    else:
        digits_a = config.get("digits_a", config.get("digits", 2))
        digits_b = config.get("digits_b", config.get("digits", 2))
        ops = config["operations"]
        count = config["problem_count"]
        time_per_q = config["time_per_question"]

    dec_places = config.get("decimal_places", 0)
    ops_display = " ".join(OPS_SYMBOL.get(o, o) for o in config["operations"])
    digits_a_disp = digits_display(digits_a)
    digits_b_disp = digits_display(digits_b)
    dec_info = f" 小数{dec_places}位" if dec_places > 0 else ""

    # 打印本轮设置
    print()
    print("  ╔" + "═" * 42 + "╗")
    if is_error_mode:
        print(f"  ║  📝 错题重练 共 {count} 题                      ║")
    else:
        print(f"  ║  位数: {digits_a_disp} vs {digits_b_disp}  |  运算: {ops_display:<10s}║")
        print(f"  ║  题数: {count:2d}    |  每题限时: {time_per_q}s{dec_info:<8s}║")
    print("  ╚" + "═" * 42 + "╝")
    print()
    print("  按任意键开始 (ESC 返回)...")
    while msvcrt.kbhit():
        msvcrt.getch()
    if msvcrt.getch() == b"\x1b":
        return

    results = []
    round_start = time.time()

    try:
        for i in range(count):
            clear_screen()

            if is_error_mode:
                prob = problems[i]
                num1 = prob["num1"]
                num2 = prob["num2"]
                op_sym = OPS_SYMBOL.get(prob["op"], prob["op"])
                expected = prob["expected"]
                time_per_q = prob.get("time_limit", time_per_q)
                d = prob.get("decimal_places", 0)
                ad = prob.get("ans_dec_places", d)
                rd = prob.get("right_dec_places")
            else:
                op = random.choice(ops)
                num1, num2, op_sym, expected, ad = generate_problem(
                    digits_a, digits_b, op, dec_places)
                d = dec_places
                # 确定右操作数小数位数
                if op in ("+", "-"):
                    rd = d
                elif op in ("÷", "%"):
                    rd = 0
                elif op == "×":
                    rd = d
                    if d > 0:
                        db_val = resolve_digits(digits_b)
                        lo_nat = 10 ** (db_val - 1) if db_val > 1 else 1
                        hi_nat = (10 ** db_val) - 1
                        if lo_nat <= num2 <= hi_nat:
                            rd = 0

            # 练习
            result = play_one_problem(
                num1, num2, op_sym, expected, time_per_q,
                idx=i + 1, total=count,
                dec_places=d, ans_dec_places=ad, right_dec_places=rd,
                is_error_retry=is_error_mode,
            )
            results.append(result)

            # 反馈
            show_feedback(result)

            # 错题本收集 / 重练标记
            if is_error_mode:
                if result["correct"]:
                    mark_error_solved(problems[i])
                else:
                    increment_error_retry(problems[i])
            else:
                if not result["correct"]:
                    add_to_error_book(result, config)

        round_end = time.time()
        total_time = round_end - round_start

        if is_error_mode:
            show_error_summary(results, total_time)
        else:
            show_summary(results, total_time, config)

    except QuitToMenu:
        # 中途按 ESC 退出，已答题目照常统计
        if results:
            round_end = time.time()
            total_time = round_end - round_start
            if is_error_mode:
                show_error_summary(results, total_time)
            else:
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
        dp = config.get("decimal_places", 0)
        da_disp = digits_display(da)
        db_disp = digits_display(db)
        dec_info = f" 小数{dp}位" if dp > 0 else ""

        err_count = get_unsolved_error_count()
        err_line = f"\n  ║   [5] 错题重练 ({err_count}题待练)                    ║" if err_count > 0 else ""

        print()
        print("  ╔" + "═" * 42 + "╗")
        print("  ║" + " " * 3 + "⚡ 速 算 练 习 工 具 — 行 测 专 用 ⚡" + " " * 3 + "║")
        print("  ╠" + "═" * 42 + "╣")
        print("  ║                                          ║")
        print(f"  ║   {da_disp} vs {db_disp}{dec_info}  |  {ops_display:<10s}  |  {config['problem_count']:2d}题/{config['time_per_question']}s  ║")
        print("  ║                                          ║")
        print("  ║   [1] 开始练习                            ║")
        print("  ║   [2] 修改设置                            ║")
        print("  ║   [3] 历史成绩                            ║")
        print("  ║   [4] 使用说明                            ║")
        if err_line:
            print(err_line)
        print("  ║   [0] 退出                                ║")
        print("  ║                                          ║")
        print("  ╚" + "═" * 42 + "╝")
        print()
        opts = "[0-4]"
        if err_count > 0:
            opts = "[0-5]"
        print(f"  请选择 {opts}: ", end="", flush=True)

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
        elif ch == "5" and err_count > 0:
            errors = [e for e in load_json(ERROR_FILE, []) if not e.get("solved", False)]
            if errors:
                run_practice(config, error_problems=errors)
            else:
                print("  暂无待练错题！")
                time.sleep(1)


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
