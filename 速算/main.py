from __future__ import annotations

import random
import re
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Type

DEFAULT_ROUNDS = 10

# ---------------------------------------------------------------------------
# Exercise API
# ---------------------------------------------------------------------------


@dataclass
class Question:
    display: str
    answer_hint: str
    expected: Any
    reveal: str


class Exercise(ABC):
    name: str = "未命名题型"
    time_limit: float = 30.0
    answer_prompt: str = "答案> "

    @abstractmethod
    def generate(self) -> Question:
        ...

    @abstractmethod
    def check(self, raw: str, question: Question) -> bool:
        ...


_REGISTRY: list[Type[Exercise]] = []


def register(cls: Type[Exercise]) -> Type[Exercise]:
    if not issubclass(cls, Exercise):
        raise TypeError(f"{cls!r} must subclass Exercise")
    _REGISTRY.append(cls)
    return cls


def all_exercises() -> list[Type[Exercise]]:
    return list(_REGISTRY)


def get_exercise(index: int) -> Exercise:
    if index < 1 or index > len(_REGISTRY):
        raise IndexError(f"题型编号无效: {index}")
    return _REGISTRY[index - 1]()


# ---------------------------------------------------------------------------
# Timed input (Windows-friendly)
# ---------------------------------------------------------------------------


def _ask_windows(prompt: str, timeout: float) -> Optional[str]:
    """Poll keys with msvcrt so timeout leaves no zombie stdin reader."""
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: list[str] = []
    deadline = time.perf_counter() + timeout

    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None

        if not msvcrt.kbhit():
            time.sleep(min(0.05, remaining))
            continue

        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)
        if ch in ("\x08", "\x7f"):
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        if ch == "\x03":
            raise KeyboardInterrupt

        buf.append(ch)
        sys.stdout.write(ch)
        sys.stdout.flush()


def _ask_threaded(prompt: str, timeout: float) -> Optional[str]:
    """Fallback for non-Windows: thread + readline (may leave a reader on timeout)."""
    result: list[Optional[str]] = [None]
    done = threading.Event()

    def _reader() -> None:
        try:
            line = sys.stdin.readline()
            if line == "":
                result[0] = None
            else:
                result[0] = line.rstrip("\r\n")
        except Exception:
            result[0] = None
        finally:
            done.set()

    thread = threading.Thread(target=_reader, daemon=True)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    thread.start()

    if done.wait(timeout):
        return result[0]

    sys.stdout.write("\n")
    sys.stdout.flush()
    return None


def ask(prompt: str, timeout: float) -> Optional[str]:
    """Read a line with timeout; return None on timeout / EOF."""
    if sys.platform == "win32":
        return _ask_windows(prompt, timeout)
    return _ask_threaded(prompt, timeout)


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------


@dataclass
class ScoreBoard:
    total: int = 0
    correct: int = 0
    times: list[float] = field(default_factory=list)

    def record(self, ok: bool, elapsed: float | None = None) -> None:
        self.total += 1
        if ok:
            self.correct += 1
            if elapsed is not None:
                self.times.append(elapsed)

    def summary(self) -> str:
        line = f"本局结束：正确 {self.correct}/{self.total}"
        if self.times:
            avg = sum(self.times) / len(self.times)
            line += f"，平均用时 {avg:.1f}s"
        return line


class GameRunner:
    def __init__(self, exercise: Exercise, rounds: int = 10) -> None:
        self.exercise = exercise
        self.rounds = rounds
        self.score = ScoreBoard()

    def run(self) -> ScoreBoard:
        limit = self.exercise.time_limit
        print(f"本局：{self.rounds} 题，每题 {limit:g} 秒\n")

        for i in range(1, self.rounds + 1):
            question = self.exercise.generate()
            print(f"第 {i}/{self.rounds} 题")
            print(f"  {question.display}")

            started = time.perf_counter()
            raw = ask(self.exercise.answer_prompt, timeout=limit)
            elapsed = time.perf_counter() - started

            if raw is None:
                print(f"❌ 超时！正确答案：{question.reveal}\n")
                self.score.record(False)
                continue

            ok = self.exercise.check(raw, question)
            if ok:
                print(f"✅ 正确！用时 {elapsed:.1f}s\n")
                self.score.record(True, elapsed)
            else:
                print(f"❌ 错误！正确答案：{question.reveal}\n")
                self.score.record(False)

        print(self.score.summary())
        return self.score


# ---------------------------------------------------------------------------
# Exercises — add new @register classes below to extend
# ---------------------------------------------------------------------------


def _parse_pair(raw: str) -> tuple[int, int] | None:
    parts = re.split(r"[\s,，]+", raw.strip())
    parts = [p for p in parts if p]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


@register
class ThreeDigitAddSub(Exercise):
    name = "三位数加减（和与差）"
    time_limit = 30.0
    answer_prompt = "和 差> "

    def generate(self) -> Question:
        a = random.randint(100, 999)
        b = random.randint(100, 999)
        total = a + b
        diff = a - b
        return Question(
            display=f"{a}  {b}",
            answer_hint="和 差",
            expected=(total, diff),
            reveal=f"{total} {diff}",
        )

    def check(self, raw: str, question: Question) -> bool:
        parsed = _parse_pair(raw)
        if parsed is None:
            return False
        return parsed == question.expected


@register
class TwoDigitTimesOne(Exercise):
    name = "两位数乘一位数"
    time_limit = 30.0
    answer_prompt = "积> "

    def generate(self) -> Question:
        a = random.randint(1, 9) * 10 + random.randint(1, 9)  # 11–99，个位非 0
        b = random.randint(2, 9)
        product = a * b
        return Question(
            display=f"{a} × {b}",
            answer_hint="积",
            expected=product,
            reveal=str(product),
        )

    def check(self, raw: str, question: Question) -> bool:
        try:
            return int(raw.strip()) == question.expected
        except ValueError:
            return False


# 与资料分析特殊分数表一致：1/n ≈ 百分数
_BAIHUAFEN: list[tuple[int, str]] = [
    (2, "50%"),
    (3, "33.3%"),
    (4, "25%"),
    (5, "20%"),
    (6, "16.7%"),
    (7, "14.3%"),
    (8, "12.5%"),
    (9, "11.1%"),
    (10, "10%"),
    (11, "9.1%"),
    (12, "8.3%"),
    (13, "7.7%"),
    (14, "7.1%"),
    (15, "6.7%"),
    (16, "6.25%"),
    (17, "5.9%"),
    (18, "5.6%"),
    (19, "5.3%"),
    (20, "5%"),
]

_CHOICE_LETTERS = ("A", "B", "C", "D")


def _normalize_choice(raw: str) -> str | None:
    s = raw.strip().upper()
    if s in _CHOICE_LETTERS:
        return s
    if s in ("1", "2", "3", "4"):
        return _CHOICE_LETTERS[int(s) - 1]
    return None


@register
class BaiHuaFenChoice(Exercise):
    name = "百化分速选（四选一）"
    time_limit = 15.0
    answer_prompt = "选项> "

    def generate(self) -> Question:
        correct_n, correct_pct = random.choice(_BAIHUAFEN)
        distractors = random.sample(
            [pair for pair in _BAIHUAFEN if pair[0] != correct_n],
            k=3,
        )
        options = [(correct_n, correct_pct), *distractors]
        random.shuffle(options)

        percent_to_frac = random.choice((True, False))
        if percent_to_frac:
            stem = f"约 {correct_pct} 最接近下列哪个分数？"
            labels = [f"1/{n}" for n, _ in options]
        else:
            stem = f"1/{correct_n} 约等于百分之几？"
            labels = [pct for _, pct in options]

        lines = [stem]
        answer_letter = "A"
        for letter, label, (n, pct) in zip(_CHOICE_LETTERS, labels, options):
            lines.append(f"  {letter}. {label}")
            if n == correct_n:
                answer_letter = letter

        correct_label = next(
            label
            for letter, label in zip(_CHOICE_LETTERS, labels)
            if letter == answer_letter
        )
        return Question(
            display="\n".join(lines),
            answer_hint="A/B/C/D",
            expected=answer_letter,
            reveal=f"{answer_letter}. {correct_label}",
        )

    def check(self, raw: str, question: Question) -> bool:
        choice = _normalize_choice(raw)
        if choice is None:
            return False
        return choice == question.expected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def print_menu() -> None:
    print("=== 速算 ===")
    for i, cls in enumerate(all_exercises(), start=1):
        print(f"{i}. {cls.name}")
    print("0. 退出")


def parse_choice(line: str) -> tuple[int, int] | None:
    """Parse 'N' or 'N rounds'. Returns (exercise_index, rounds) or None to quit."""
    parts = line.strip().split()
    if not parts:
        return None
    try:
        index = int(parts[0])
    except ValueError:
        return None
    if index == 0:
        return None
    rounds = DEFAULT_ROUNDS
    if len(parts) >= 2:
        try:
            rounds = int(parts[1])
        except ValueError:
            return None
        if rounds < 1:
            return None
    return index, rounds


def main() -> None:
    while True:
        print_menu()
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        parsed = parse_choice(line)
        if parsed is None:
            if line.strip() in ("", "0"):
                break
            print("无效输入，请输入题型编号，或「编号 题数」。\n")
            continue

        index, rounds = parsed
        try:
            exercise = get_exercise(index)
        except IndexError:
            print("题型编号无效。\n")
            continue

        print()
        GameRunner(exercise, rounds=rounds).run()
        print()


if __name__ == "__main__":
    main()
