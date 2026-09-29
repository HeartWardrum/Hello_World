import tkinter as tk
from tkinter import messagebox
import subprocess
import os
import datetime

# ========== 配置区 ==========
REPO_PATH = rf"D:\文档\github\Hello_World"   # 你的仓库路径
FILE_NAME = rf"脚本工具\传送工具\msg.txt"                        # 用来存放消息的文件名
# ============================

def send():
    content = text_box.get("1.0", tk.END).strip()
    if not content:
        messagebox.showwarning("提示", "内容为空，没有可传送的内容。")
        return

    file_path = os.path.join(REPO_PATH, FILE_NAME)

    try:
        # 1. 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 2. 执行 git 命令
        os.chdir(REPO_PATH)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        subprocess.run(["git", "add", FILE_NAME], check=True)
        subprocess.run(["git", "commit", "-m", f"auto send {now}"], check=True)
        subprocess.run(["git", "push"], check=True)

        status_label.config(text=f"✅ 已传送 {now}", fg="green")

    except subprocess.CalledProcessError as e:
        status_label.config(text="❌ git 命令执行失败", fg="red")
        messagebox.showerror("Git 错误", f"执行 git 时出错：\n{e}\n\n请确认命令行里能直接 git push 成功。")
    except Exception as e:
        status_label.config(text="❌ 出错", fg="red")
        messagebox.showerror("错误", str(e))


# ========== 界面 ==========
root = tk.Tk()
root.title("传送工具")
root.geometry("520x360")

tk.Label(root, text="输入要传送的内容：", anchor="w").pack(fill="x", padx=10, pady=(10, 0))

text_box = tk.Text(root, height=12, wrap="word")
text_box.pack(fill="both", expand=True, padx=10, pady=5)

btn = tk.Button(root, text="🚀 传送", command=send, height=2, bg="#4CAF50", fg="white",
                font=("微软雅黑", 11, "bold"))
btn.pack(fill="x", padx=10, pady=5)

status_label = tk.Label(root, text="等待传送…", fg="gray")
status_label.pack(pady=(0, 10))

root.mainloop()