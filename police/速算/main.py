from __future__ import annotations

import random
import re
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Type

DEFAULT_ROUNDS = 10  # 默认每局题数（菜单输入「编号 题数」可覆盖）

# ---------------------------------------------------------------------------
# 每题限时（秒）—— 只改这里即可调整各模块节奏
# ---------------------------------------------------------------------------
TIME_三位数加减 = 20.0      # 三位数加减（和与差）
TIME_两位数乘一位数 = 8.0  # 两位数乘一位数
TIME_三位数乘一位数 = 22.0  # 三位数乘一位数
TIME_百化分速选 = 15.0      # 百化分速选（四选一）
TIME_截位直除 = 25.0        # 截位直除（四选一）
TIME_增长量百化分 = 25.0    # 增长量（百化分）
TIME_基期量 = 30.0          # 基期量（÷(1+r)）
TIME_分数比大小 = 20.0      # 分数比大小
TIME_间隔增长率 = 20.0      # 间隔增长率
TIME_邻近百化分 = 15.0      # 邻近百化分（四选一）
TIME_两位数乘两位数 = 40.0  # 两位数乘两位数
TIME_乘除一加r = 30.0       # ×(1+r) / ÷(1+r)
TIME_年均增长率 = 35.0      # 年均增长率（代入验算）
TIME_平方数速记 = 12.0      # 平方数速记（11~30）
TIME_凑整乘除 = 20.0        # 凑整乘除（×5/25/125）

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

        try:
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
        except KeyboardInterrupt:
            print("\n已中断。")
            if self.score.total:
                print(self.score.summary())
            return self.score

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


def _parse_number(raw: str) -> float | None:
    """Parse int/float; strip optional trailing % and commas."""
    s = raw.strip().replace(",", "").replace("，", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _approx_equal(got: float, expected: float, *, rel: float = 0.02, abs_tol: float = 1.0) -> bool:
    return abs(got - expected) <= max(abs_tol, abs(expected) * rel)


_CHOICE_LETTERS = ("A", "B", "C", "D")


def _normalize_choice(raw: str) -> str | None:
    s = raw.strip().upper()
    if s in _CHOICE_LETTERS:
        return s
    if s in ("1", "2", "3", "4"):
        return _CHOICE_LETTERS[int(s) - 1]
    return None


def _mc_question(
    stem: str,
    labels: list[str],
    correct_index: int,
) -> Question:
    lines = [stem]
    for letter, label in zip(_CHOICE_LETTERS, labels):
        lines.append(f"  {letter}. {label}")
    answer_letter = _CHOICE_LETTERS[correct_index]
    return Question(
        display="\n".join(lines),
        answer_hint="A/B/C/D",
        expected=answer_letter,
        reveal=f"{answer_letter}. {labels[correct_index]}",
    )


def _check_choice(raw: str, question: Question) -> bool:
    choice = _normalize_choice(raw)
    return choice is not None and choice == question.expected


def _format_quot(q: float) -> str:
    """Format quotient for display / options (2–3 significant feel)."""
    if q >= 100:
        return str(round(q))
    if q >= 10:
        return f"{q:.1f}"
    return f"{q:.2f}"


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

# 邻近百化分：常见非整表增速 → 最接近的 1/n
_NEAR_BAIHUAFEN: list[tuple[str, int]] = [
    ("15%", 7),  # ≈1/6.7
    ("12%", 8),  # ≈1/8.3
    ("18%", 6),  # ≈1/5.6
    ("9%", 11),
    ("8%", 12),
    ("6%", 17),
    ("7%", 14),
    ("13%", 8),  # ≈1/7.7 → 常取 8 附近；更准 1/7.7 用 8 估增长量
    ("22%", 5),  # ≈1/4.5
    ("4%", 25),
]


@register
class ThreeDigitAddSub(Exercise):
    name = "三位数加减（和与差）"
    time_limit = TIME_三位数加减
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
    time_limit = TIME_两位数乘一位数
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


@register
class ThreeDigitTimesOne(Exercise):
    name = "三位数乘一位数"
    time_limit = TIME_三位数乘一位数
    answer_prompt = "积> "

    def generate(self) -> Question:
        # 101–999，个位非 0，避免乘整十过于简单
        a = (
            random.randint(1, 9) * 100
            + random.randint(0, 9) * 10
            + random.randint(1, 9)
        )
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


@register
class BaiHuaFenChoice(Exercise):
    name = "百化分速选（四选一）"
    time_limit = TIME_百化分速选
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

        correct_index = next(i for i, (n, _) in enumerate(options) if n == correct_n)
        return _mc_question(stem, labels, correct_index)

    def check(self, raw: str, question: Question) -> bool:
        return _check_choice(raw, question)


@register
class JieWeiZhiChu(Exercise):
    name = "截位直除（四选一）"
    time_limit = TIME_截位直除
    answer_prompt = "选项> "

    def generate(self) -> Question:
        # 分子 3～4 位，分母 2～3 位，保证商在可辨区间
        for _ in range(40):
            a = random.randint(100, 9999)
            b = random.randint(11, 999)
            if a <= b:
                continue
            q = a / b
            if q < 1.05 or q > 900:
                continue
            correct = _format_quot(q)
            # 干扰项：错截位 / 放缩偏差
            distractors: set[str] = set()
            factors = [0.85, 0.9, 0.95, 1.05, 1.1, 1.15, 1.2]
            random.shuffle(factors)
            for f in factors:
                label = _format_quot(q * f)
                if label != correct:
                    distractors.add(label)
                if len(distractors) >= 3:
                    break
            # 首位错截
            rough = _format_quot((a // 100 or a // 10) / max(b // 100, b // 10, 1))
            if rough != correct:
                distractors.add(rough)
            if len(distractors) < 3:
                continue
            labels = [correct, *list(distractors)[:3]]
            random.shuffle(labels)
            stem = f"{a} ÷ {b} ≈ ？"
            return _mc_question(stem, labels, labels.index(correct))
        # fallback
        return _mc_question("4800 ÷ 750 ≈ ？", ["6.4", "5.8", "7.2", "6.0"], 0)

    def check(self, raw: str, question: Question) -> bool:
        return _check_choice(raw, question)


@register
class ZengZhangLiangBaiHuaFen(Exercise):
    name = "增长量（百化分）"
    time_limit = TIME_增长量百化分
    answer_prompt = "增长量> "

    def generate(self) -> Question:
        # 优先用表内精确 1/n；偶尔用邻近增速
        if random.random() < 0.7:
            n, pct = random.choice([(n, p) for n, p in _BAIHUAFEN if 5 <= n <= 20])
            r_label = pct
            divisor = n + 1
        else:
            r_label, n = random.choice(_NEAR_BAIHUAFEN)
            divisor = n + 1

        # 现期做成容易心算的数
        xianqi = random.choice([1200, 1500, 1800, 2100, 2400, 2700, 3000, 3600, 4200, 4800, 5400, 6000, 7200, 8400, 9600])
        xianqi = int(xianqi * random.choice([1, 10, 100]))
        zeng = round(xianqi / divisor)
        return Question(
            display=f"现期 {xianqi}，增长率约 {r_label}，增长量 ≈ ？\n  （百化分：增长量 ≈ 现期 ÷ (n+1)）",
            answer_hint="整数",
            expected=float(zeng),
            reveal=f"{zeng}（现期÷{divisor}）",
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        if got is None:
            return False
        return _approx_equal(got, question.expected, rel=0.03, abs_tol=max(2.0, question.expected * 0.02))


@register
class JiQiLiang(Exercise):
    name = "基期量（÷(1+r)）"
    time_limit = TIME_基期量
    answer_prompt = "基期> "

    def generate(self) -> Question:
        # 常用增速，含少量负增长
        r_pct = random.choice(
            [5, 8, 10, 12, 15, 20, 25, -5, -8, -10, -12]
        )
        r = r_pct / 100.0
        xianqi = random.randint(200, 980) * random.choice([1, 10, 100])
        jiqi = xianqi / (1 + r)
        expected = round(jiqi)
        sign = f"{r_pct}%" if r_pct >= 0 else f"{r_pct}%"
        return Question(
            display=f"现期 {xianqi}，增长率 {sign}，基期 ≈ ？\n  （基期 = 现期 ÷ (1+r)，可截位）",
            answer_hint="整数（约）",
            expected=float(expected),
            reveal=f"{expected}（精确 {jiqi:.2f}）",
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        if got is None:
            return False
        return _approx_equal(got, question.expected, rel=0.03, abs_tol=max(3.0, question.expected * 0.025))


@register
class FenShuBiJiao(Exercise):
    name = "分数比大小"
    time_limit = TIME_分数比大小
    answer_prompt = "选项> "

    def generate(self) -> Question:
        # 构造两个分数，避免恰好相等
        for _ in range(30):
            a = random.randint(11, 99)
            b = random.randint(11, 99)
            c = random.randint(11, 99)
            d = random.randint(11, 99)
            if a * d == b * c:
                continue
            left_bigger = a * d > b * c
            stem = f"比较：{a}/{b}  与  {c}/{d}  谁更大？"
            labels = [f"{a}/{b}", f"{c}/{d}", "一样大", "无法判断"]
            correct = 0 if left_bigger else 1
            return _mc_question(stem, labels, correct)
        return _mc_question("比较：3/4 与 5/7 谁更大？", ["3/4", "5/7", "一样大", "无法判断"], 0)

    def check(self, raw: str, question: Question) -> bool:
        return _check_choice(raw, question)


@register
class JianGeZengZhangLv(Exercise):
    name = "间隔增长率"
    time_limit = TIME_间隔增长率
    answer_prompt = "间隔增速%> "

    def generate(self) -> Question:
        r1 = random.randint(5, 30)
        r2 = random.randint(5, 30)
        # 间隔增长率(%) = r1 + r2 + r1*r2/100
        result = r1 + r2 + r1 * r2 / 100.0
        # 题目多数考到整数或一位小数
        if abs(result - round(result)) < 1e-9:
            reveal = str(int(round(result)))
            expected = float(int(round(result)))
        else:
            reveal = f"{result:.1f}".rstrip("0").rstrip(".")
            expected = round(result, 1)
        return Question(
            display=f"两年增速分别为 {r1}%、{r2}%，间隔增长率 = ？%\n  （r1+r2+r1×r2）",
            answer_hint="百分数数值，如 32 或 32.5",
            expected=expected,
            reveal=f"{reveal}%",
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        if got is None:
            return False
        return _approx_equal(got, question.expected, rel=0.0, abs_tol=0.15)


@register
class LinJinBaiHuaFen(Exercise):
    name = "邻近百化分（四选一）"
    time_limit = TIME_邻近百化分
    answer_prompt = "选项> "

    def generate(self) -> Question:
        pct, n = random.choice(_NEAR_BAIHUAFEN)
        # 干扰：邻近 n
        pool = list({n - 2, n - 1, n + 1, n + 2, n + 3, max(2, n - 3)})
        pool = [x for x in pool if x >= 2 and x != n]
        distractors = random.sample(pool, k=min(3, len(pool)))
        while len(distractors) < 3:
            x = random.randint(4, 25)
            if x != n and x not in distractors:
                distractors.append(x)
        ns = [n, *distractors[:3]]
        random.shuffle(ns)
        stem = f"增长率约 {pct}，最接近 1/n 的 n 是？\n  （增长量 ≈ 现期÷(n+1)）"
        labels = [str(x) for x in ns]
        return _mc_question(stem, labels, ns.index(n))

    def check(self, raw: str, question: Question) -> bool:
        return _check_choice(raw, question)


@register
class TwoDigitTimesTwo(Exercise):
    name = "两位数乘两位数"
    time_limit = TIME_两位数乘两位数
    answer_prompt = "积> "

    def generate(self) -> Question:
        a = random.randint(11, 99)
        b = random.randint(11, 99)
        product = a * b
        return Question(
            display=f"{a} × {b}",
            answer_hint="积",
            expected=product,
            reveal=str(product),
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        return got is not None and int(got) == question.expected


@register
class ChengChuYiJiaR(Exercise):
    name = "×(1+r) / ÷(1+r)"
    time_limit = TIME_乘除一加r
    answer_prompt = "结果> "

    def generate(self) -> Question:
        base = random.randint(80, 999) * random.choice([1, 10])
        r_pct = random.choice([2, 5, 8, 10, 12, 15, 20, 25, -5, -8, -10])
        r = r_pct / 100.0
        multiply = random.choice((True, False))
        if multiply:
            exact = base * (1 + r)
            op = f"{base} × (1{r_pct:+d}%)"
        else:
            exact = base / (1 + r)
            op = f"{base} ÷ (1{r_pct:+d}%)"
        expected = round(exact)
        return Question(
            display=f"{op} ≈ ？",
            answer_hint="整数（约）",
            expected=float(expected),
            reveal=f"{expected}（精确 {exact:.2f}）",
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        if got is None:
            return False
        return _approx_equal(got, question.expected, rel=0.025, abs_tol=max(2.0, question.expected * 0.02))


@register
class NianJunZengZhangLv(Exercise):
    name = "年均增长率（代入验算）"
    time_limit = TIME_年均增长率
    answer_prompt = "选项> "

    def generate(self) -> Question:
        # 构造：基期 × (1+r)^n = 现期，r 取整齐百分数
        n = random.choice([2, 3, 4, 5])
        r_pct = random.choice([5, 8, 10, 12, 15, 20])
        r = r_pct / 100.0
        jiqi = random.choice([100, 200, 250, 400, 500, 800, 1000])
        xianqi = round(jiqi * (1 + r) ** n)
        # 干扰增速
        distractors = []
        for delta in (-5, -3, -2, 2, 3, 5, 8):
            cand = r_pct + delta
            if cand > 0 and cand != r_pct and cand not in distractors:
                distractors.append(cand)
            if len(distractors) >= 3:
                break
        opts = [r_pct, *distractors[:3]]
        random.shuffle(opts)
        labels = [f"{x}%" for x in opts]
        stem = (
            f"基期 {jiqi}，{n} 年后现期 {xianqi}，年均增长率约为？\n"
            f"  （代入：基期×(1+r)^{n} ≈ 现期）"
        )
        return _mc_question(stem, labels, opts.index(r_pct))

    def check(self, raw: str, question: Question) -> bool:
        return _check_choice(raw, question)


@register
class PingFangSuJi(Exercise):
    name = "平方数速记（11~30）"
    time_limit = TIME_平方数速记
    answer_prompt = "结果> "

    def generate(self) -> Question:
        n = random.randint(11, 30)
        if random.random() < 0.5:
            return Question(
                display=f"{n}^2 = ？",
                answer_hint="平方",
                expected=n * n,
                reveal=str(n * n),
            )
        sq = n * n
        return Question(
            display=f"{sq} 开平方 = ？",
            answer_hint="正整数",
            expected=n,
            reveal=str(n),
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        return got is not None and int(got) == question.expected


@register
class CouZhengChengChu(Exercise):
    name = "凑整乘除（×5/25/125）"
    time_limit = TIME_凑整乘除
    answer_prompt = "结果> "

    def generate(self) -> Question:
        kind = random.choice(["*5", "/5", "*25", "/25", "*125", "/125"])
        if kind == "*5":
            a = random.randint(12, 99) * 2  # 偶数更好心算
            expected = a * 5
            display = f"{a} × 5"
        elif kind == "/5":
            expected = random.randint(20, 200)
            a = expected * 5
            display = f"{a} ÷ 5"
        elif kind == "*25":
            a = random.randint(8, 80) * 4
            expected = a * 25
            display = f"{a} × 25  （可看作 ÷4 再 ×100）"
        elif kind == "/25":
            expected = random.randint(4, 80)
            a = expected * 25
            display = f"{a} ÷ 25"
        elif kind == "*125":
            a = random.randint(4, 40) * 8
            expected = a * 125
            display = f"{a} × 125  （可看作 ÷8 再 ×1000）"
        else:
            expected = random.randint(2, 40)
            a = expected * 125
            display = f"{a} ÷ 125"
        return Question(
            display=display,
            answer_hint="整数",
            expected=expected,
            reveal=str(expected),
        )

    def check(self, raw: str, question: Question) -> bool:
        got = _parse_number(raw)
        return got is not None and int(got) == question.expected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------



def print_menu() -> None:
    print("=== 速算 ===")
    for i, cls in enumerate(all_exercises(), start=1):
        print(f"{i}. {cls.name}  每题 {cls.time_limit:g}s")
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

        parts = line.strip().split()
        # 选 0（或空回车）直接退出，不二次确认
        if not parts or parts[0] == "0":
            break

        parsed = parse_choice(line)
        if parsed is None:
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
