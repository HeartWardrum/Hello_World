#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学速算测试系统 —— 模拟考场
------------------------------------------------
功能1：两位数 × 一位数，共 40 题，限时 90 秒
功能2：两位数加减法，共 20 组，限时 120 秒
      每组给出两个两位数（大小顺序不固定），你需要同时算出
      它们的和与差（差可能为负数）

特点：
  - 倒计时在答题的同一行实时跳动（每秒刷新，不是等你答完题才更新）
  - 时间到不会强制交卷，会提示"超时"，并允许你把剩下的题目做完
  - 交卷后显示得分、总用时、以及错题（你的答案 / 正确答案）
  - 两位数不出现以 0 / 1 结尾的数字，一位数不出现 1
"""

import random
import time
import sys
import os

IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    import msvcrt
else:
    import termios
    import tty
    import select


# ---------- 终端颜色 ----------
class C:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def enable_ansi_on_windows():
    if IS_WINDOWS:
        os.system('')  # 让 Windows 10+ cmd 支持 ANSI 转义序列


def clear_screen():
    os.system('cls' if IS_WINDOWS else 'clear')


def beep():
    sys.stdout.write('\a')
    sys.stdout.flush()


# ---------- 出题函数（两位数不以 0/1 结尾，一位数不为 1） ----------
def random_two_digit():
    tens = random.randint(1, 9)
    units = random.randint(2, 9)  # 不出现 0、1 结尾
    return tens * 10 + units


def random_one_digit():
    return random.randint(2, 9)  # 不出现 1


def gen_mul_item():
    """乘法：每题只有 1 个小问"""
    a = random_two_digit()
    b = random_one_digit()
    return [(f"{a} × {b}", a * b)]


def gen_add_sub_item():
    """加减法：每组两个数，顺序不固定，同时考加法和减法（差可能为负数）"""
    a = random_two_digit()
    b = random_two_digit()
    if random.random() < 0.5:
        a, b = b, a
    return [
        (f"{a} + {b}", a + b),
        (f"{a} - {b}", a - b),
    ]


# ---------- 跨平台单字符非阻塞读取 ----------
class KeyReader:
    """在 Unix 下用 termios+select 实现 cbreak 非阻塞读取；Windows 用 msvcrt。"""

    def __enter__(self):
        self.tty_ok = sys.stdin.isatty()
        if self.tty_ok and not IS_WINDOWS:
            self.fd = sys.stdin.fileno()
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        if self.tty_ok and not IS_WINDOWS:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)

    def get_char(self, timeout=0.08):
        """有键按下则返回该字符，否则返回 None（最多等待 timeout 秒）。"""
        if not self.tty_ok:
            return None
        if IS_WINDOWS:
            start = time.time()
            while time.time() - start < timeout:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.01)
            return None
        else:
            dr, _, _ = select.select([sys.stdin], [], [], timeout)
            if dr:
                return sys.stdin.read(1)
            return None


# ---------- 考试核心逻辑 ----------
class Exam:
    def __init__(self, name, duration, generator, item_total, unit_label="题"):
        """
        generator: 调用一次返回一个 item 的小问列表 [(题目文本, 正确答案), ...]
        item_total: item 的数量（例如 40 道乘法题，或 20 组加减法）
        unit_label: item 的单位，"题" 或 "组"
        """
        self.name = name
        self.duration = duration
        self.generator = generator
        self.item_total = item_total
        self.unit_label = unit_label
        self.start_time = None
        self.results = []  # {question, correct, user_answer, is_correct}
        self.warned_10s = False
        self.warned_overtime = False

    def elapsed(self):
        return time.time() - self.start_time if self.start_time else 0.0

    def remaining(self):
        """考试限时倒计时，可以为负数（代表已超时多久）"""
        return self.duration - self.elapsed()

    def format_timer(self):
        remaining = self.remaining()
        if remaining >= 0:
            mins, secs = divmod(int(remaining), 60)
            if remaining <= 10:
                color = C.RED + C.BOLD
                icon = "🔥"
            elif remaining <= 30:
                color = C.YELLOW + C.BOLD
                icon = "⚠"
            else:
                color = C.GREEN
                icon = "⏱"
            text = f"{icon} 剩余 {mins:02d}:{secs:02d}"
        else:
            overtime = int(-remaining)
            mins, secs = divmod(overtime, 60)
            color = C.RED + C.BOLD
            text = f"⏰ 已超时 {mins:02d}:{secs:02d}"
        return f"{color}{text}{C.RESET}"

    def countdown_intro(self):
        clear_screen()
        print(C.BOLD + C.CYAN + "=" * 60)
        print(f"{self.name}  ——  正式开始".center(60))
        print("=" * 60 + C.RESET)
        print(f"{C.YELLOW}总{self.unit_label}数: {self.item_total}    时限: "
              f"{self.duration // 60} 分 {self.duration % 60} 秒{C.RESET}")
        if self.unit_label == "组":
            print(f"{C.MAGENTA}每组给出两个数（顺序不固定），需依次算出它们的"
                  f"和与差，差可能为负数！{C.RESET}")
        print(f"{C.MAGENTA}倒计时会在答题行实时跳动；时间到不会强制交卷，"
              f"但请尽量在限时内完成！{C.RESET}")
        print("-" * 60)
        for i in range(3, 0, -1):
            print(f"{C.RED}{C.BOLD}>>> 考试即将开始 ... {i} <<<{C.RESET}")
            beep()
            time.sleep(1)
        clear_screen()
        print(C.BOLD + C.GREEN + f"开始答题！{self.name}" + C.RESET)
        print("=" * 60)

    def get_answer_live(self, reader, header):
        """在同一行实时刷新倒计时 + 已输入内容，回车提交。支持负号。"""
        buffer = ""
        overtime_banner_shown = False
        while True:
            remaining = self.remaining()

            if 0 <= remaining <= 10 and not self.warned_10s:
                self.warned_10s = True
                beep()

            if remaining < 0 and not overtime_banner_shown:
                overtime_banner_shown = True
                if not self.warned_overtime:
                    self.warned_overtime = True
                    sys.stdout.write('\n')
                    sys.stdout.write(
                        f"{C.RED}{C.BOLD}⏰⏰⏰ 时间到！可以继续把剩下的题目做完 ⏰⏰⏰{C.RESET}\n"
                    )
                    beep()

            line = f"{self.format_timer()}  {header}{buffer}"
            sys.stdout.write('\r' + '\033[K' + line)
            sys.stdout.flush()

            if not reader.tty_ok:
                sys.stdout.write('\n')
                try:
                    return input().strip()
                except EOFError:
                    return ""

            ch = reader.get_char(timeout=0.08)
            if ch is None:
                continue
            if ch in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                return buffer.strip()
            elif ch in ('\x08', '\x7f'):  # 退格
                buffer = buffer[:-1]
            elif ch == '\x03':  # Ctrl+C
                raise KeyboardInterrupt
            elif ch == '-' or ch.isdigit():
                buffer += ch
            # 其余字符忽略

    def run(self):
        self.countdown_intro()
        self.start_time = time.time()

        with KeyReader() as reader:
            for idx in range(1, self.item_total + 1):
                subqs = self.generator()
                multi = len(subqs) > 1
                for si, (q_text, correct_answer) in enumerate(subqs, 1):
                    if multi:
                        tag = f"第 {idx:>2}/{self.item_total} {self.unit_label} [{si}/{len(subqs)}]"
                    else:
                        tag = f"第 {idx:>2}/{self.item_total} {self.unit_label}"
                    header = f"{tag}：  {q_text} = "
                    user_input = self.get_answer_live(reader, header)

                    try:
                        user_answer = int(user_input) if user_input not in ("", "-") else None
                    except ValueError:
                        user_answer = None

                    is_correct = (user_answer == correct_answer)
                    submit_elapsed = self.elapsed()
                    self.results.append({
                        'question': q_text,
                        'correct': correct_answer,
                        'user_answer': user_answer,
                        'is_correct': is_correct,
                        'within_time': submit_elapsed <= self.duration,
                        'submit_elapsed': submit_elapsed,
                    })

        total_time_used = self.elapsed()
        self.show_report(total_time_used)

    @staticmethod
    def _rate(correct, total):
        return round(correct / total * 100, 1) if total else 0.0

    def show_report(self, total_time_used):
        clear_screen()
        expected_answers = len(self.results)  # 已作答的小问总数（固定，因为不再中途中断）
        correct_count = sum(1 for r in self.results if r['is_correct'])
        overall_rate = self._rate(correct_count, expected_answers)

        within = [r for r in self.results if r['within_time']]
        overtime_part = [r for r in self.results if not r['within_time']]
        within_correct = sum(1 for r in within if r['is_correct'])
        overtime_correct = sum(1 for r in overtime_part if r['is_correct'])

        print(C.BOLD + C.CYAN + "=" * 60)
        print(f"{self.name}  ——  成绩报告".center(60))
        print("=" * 60 + C.RESET)

        # ---- 总体成绩 ----
        print(f"{C.BOLD}【总体成绩】{C.RESET}")
        print(f"  总小题数: {expected_answers}    "
              f"正确: {C.GREEN}{correct_count}{C.RESET}    "
              f"错误: {C.RED}{expected_answers - correct_count}{C.RESET}")
        rate_color = C.GREEN if overall_rate >= 80 else (C.YELLOW if overall_rate >= 60 else C.RED)
        print(f"  正确率: {rate_color}{overall_rate}%{C.RESET}    "
              f"{C.BOLD}最终得分: {rate_color}{overall_rate} 分{C.RESET}")

        # ---- 用时情况 ----
        mins, secs = divmod(int(total_time_used), 60)
        avg_sec = total_time_used / expected_answers if expected_answers else 0.0
        print(f"\n{C.BOLD}【用时情况】{C.RESET}")
        if total_time_used > self.duration:
            over_mins, over_secs = divmod(int(total_time_used - self.duration), 60)
            print(f"  总用时: {mins:02d}:{secs:02d}  "
                  f"{C.RED}(超出限时 {over_mins:02d}:{over_secs:02d}){C.RESET}")
        else:
            print(f"  总用时: {C.GREEN}{mins:02d}:{secs:02d} (未超时){C.RESET}")
        print(f"  平均每题用时: {avg_sec:.1f} 秒    限时: "
              f"{self.duration // 60} 分 {self.duration % 60} 秒")

        # ---- 规定时间内 vs 超时后 ----
        print(f"\n{C.BOLD}【规定时间内 vs 超时后】{C.RESET}")
        within_rate = self._rate(within_correct, len(within))
        wcolor = C.GREEN if within_rate >= 80 else (C.YELLOW if within_rate >= 60 else C.RED)
        print(f"  规定时间内作答: {len(within)} 题    正确: {C.GREEN}{within_correct}{C.RESET}"
              f"    正确率: {wcolor}{within_rate}%{C.RESET}")
        if overtime_part:
            over_rate = self._rate(overtime_correct, len(overtime_part))
            ocolor = C.GREEN if over_rate >= 80 else (C.YELLOW if over_rate >= 60 else C.RED)
            print(f"  {C.RED}超时后作答: {len(overtime_part)} 题    正确: "
                  f"{overtime_correct}    正确率: {ocolor}{over_rate}%{C.RESET}")
        else:
            print(f"  {C.GREEN}没有超时，全部题目都在规定时间内完成！{C.RESET}")
        print("-" * 60)

        wrongs = [r for r in self.results if not r['is_correct']]
        if wrongs:
            print(f"{C.YELLOW}{C.BOLD}错题回顾：{C.RESET}")
            for i, r in enumerate(wrongs, 1):
                ua = r['user_answer'] if r['user_answer'] is not None else "未作答"
                mark = "" if r['within_time'] else f"  {C.RED}[超时后作答]{C.RESET}"
                print(f"  {i:>2}. {r['question']} = "
                      f"{C.RED}{ua}{C.RESET}   "
                      f"(正确答案: {C.GREEN}{r['correct']}{C.RESET}){mark}")
        else:
            print(f"{C.GREEN}{C.BOLD}太棒了，全部正确！{C.RESET}")
        print("=" * 60)


# ---------- 主菜单 ----------
def main():
    enable_ansi_on_windows()
    while True:
        clear_screen()
        print(C.BOLD + C.CYAN + "=" * 60)
        print("数学速算测试系统 —— 模拟考场".center(60))
        print("=" * 60 + C.RESET)
        print(f"{C.YELLOW}1. 两位数 × 一位数   （40 题 / 90 秒）{C.RESET}")
        print(f"{C.YELLOW}2. 两位数加减法      （20 组 / 120 秒，"
              f"每组算和与差）{C.RESET}")
        print(f"{C.YELLOW}0. 退出{C.RESET}")
        print("-" * 60)
        try:
            choice = input("请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if choice == '1':
            Exam("两位数乘一位数测试", 90, gen_mul_item, 40, unit_label="题").run()
            input("\n按回车键返回主菜单...")
        elif choice == '2':
            Exam("两位数加减法测试", 120, gen_add_sub_item, 20, unit_label="组").run()
            input("\n按回车键返回主菜单...")
        elif choice == '0':
            print("再见！")
            break
        else:
            print(f"{C.RED}无效选择，请重新输入{C.RESET}")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n已退出考试系统。")