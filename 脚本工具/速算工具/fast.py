import os
import random
import sys
import time

# 尝试导入 msvcrt（Windows 适用），如果不在 Windows 则使用 select（Mac/Linux 适用）
try:
    import msvcrt
except ImportError:
    import select


def generate_question():
    """随机生成行测常见的速算题型"""
    quiz_type = random.choice(["资料分析-比重/增长率", "乘法速算", "除法截位", "加减法"])

    if quiz_type == "资料分析-比重/增长率":
        # 模拟资料分析中的基期、现期、比重计算
        a = random.randint(100, 999)
        b = random.randint(10, 99)
        question = f"【资料分析】 {a}占{b}% 的基期值是多少？ (保留整数)"
        answer = str(round(a / (b / 100)))

    elif quiz_type == "乘法速算":
        # 两位数乘法或十几乘十几
        a = random.randint(11, 89)
        b = random.randint(11, 19)
        question = f"【乘法速算】 {a} × {b} = ?"
        answer = str(a * b)

    elif quiz_type == "除法截位":
        # 模拟大数直除
        a = random.randint(1000, 9999)
        b = random.randint(12, 99)
        question = f"【除法截位】 {a} ÷ {b} = ? (取前两位有效数字，不四舍五入，直接截取)"
        # 提取前两位有效数字
        res = str(a // b)
        answer = res[:2]

    else:
        # 多个数连加减
        a = random.randint(100, 999)
        b = random.randint(100, 999)
        c = random.randint(100, 999)
        question = f"【加减混合】 {a} + {b} - {c} = ?"
        answer = str(a + b - c)

    return question, answer


def input_with_timeout(prompt, timeout=10):
    """带动态倒计时的输入函数"""
    sys.stdout.write(prompt + "\n")
    sys.stdout.flush()

    input_buf = ""
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        remaining = max(0, timeout - int(elapsed))

        # 动态刷新倒计时行
        # \r 让光标回到行首，\033[K 清除从光标到行尾的内容
        timer_str = f"⏳ 剩余时间: {remaining} 秒 | 你的答案: {input_buf}"
        sys.stdout.write("\r" + timer_str)
        sys.stdout.flush()

        if elapsed >= timeout:
            sys.stdout.write("\n\n⏰ 时间到！\n")
            return "TIMEOUT"

        # 检查是否有键盘输入
        if sys.platform == "win32":
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\r", b"\n"):  # 回车键
                    sys.stdout.write("\n")
                    return input_buf.strip()
                elif ch == b"\x08":  # 退格键
                    input_buf = input_buf[:-1]
                    # 清除当前行以便刷新
                    sys.stdout.write("\r" + " " * (len(timer_str) + 5))
                else:
                    try:
                        input_buf += ch.decode("utf-8")
                    except:
                        pass
        else:
            # Mac/Linux 环境
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if rlist:
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    return input_buf.strip()
                elif ch in ("\x7f", "\b"):  # 退格键
                    input_buf = input_buf[:-1]
                    sys.stdout.write("\r" + " " * (len(timer_str) + 5))
                else:
                    input_buf += ch

        time.sleep(0.05)  # 稍微降低CPU占用


def main():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 50)
    print("        🚀 行测速算终极训练营 🚀        ")
    print("   每题有 10 秒思考时间，输入答案后回车。")
    print("   按 Ctrl + C 可以退出程序。")
    print("=" * 50)
    input("\n准备好了吗？按【回车键】开始轰炸... ")

    score = 0
    total = 0

    try:
        while True:
            total += 1
            os.system("cls" if os.name == "nt" else "clear")
            print(f"--- 第 {total} 题 ---")

            question, correct_answer = generate_question()

            # 调用带倒计时的输入，设置10秒限制
            user_answer = input_with_timeout(
                f"\n👉 题目: {question}", timeout=10
            )

            if user_answer == "TIMEOUT":
                print(f"❌ 遗憾超时！正确答案是: 【 {correct_answer} 】")
            elif user_answer == correct_answer:
                print(f"✅ 🎯 太强了！答案正确！")
                score += 1
            else:
                print(
                    f"❌ 算错啦！你的答案: {user_answer if user_answer else '空'} | 正确答案: 【 {correct_answer} 】"
                )

            print(f"\n📊 当前胜率: {score}/{total} ({score/total:.1%})")
            input("\n按【回车键】进入下一题...")

    except KeyboardInterrupt:
        print(f"\n\n👋 训练结束！最终战绩: 总做题 {total-1} 道，答对 {score} 道。继续加油！")


if __name__ == "__main__":
    main()