import keyboard
import pystray
from PIL import Image
import threading
import os
import sys
import time


def get_resource_path(relative_path):
    """ 获取资源绝对路径，适配 PyInstaller 打包后的路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def send_arrow(key):
    """ 发送方向键，并确保 Alt 被释放 """
    try:
        keyboard.release('alt')  # 🔥 关键：防止 Alt 卡住
        keyboard.press(key)
        keyboard.release(key)
    except:
        pass


def setup_keyboard():
    """ 注册快捷键 """
    keyboard.add_hotkey('alt+i', lambda: send_arrow('up'), suppress=True)
    keyboard.add_hotkey('alt+k', lambda: send_arrow('down'), suppress=True)
    keyboard.add_hotkey('alt+j', lambda: send_arrow('left'), suppress=True)
    keyboard.add_hotkey('alt+l', lambda: send_arrow('right'), suppress=True)

    # 保持线程存活（比 keyboard.wait 更稳定）
    while True:
        time.sleep(1)


def on_quit(icon, item):
    """ 退出程序 """
    icon.stop()
    os._exit(0)


def main():
    # 1. 启动键盘监听线程
    threading.Thread(target=setup_keyboard, daemon=True).start()

    # 2. 加载托盘图标
    icon_path = get_resource_path("icon.ico")
    try:
        icon_image = Image.open(icon_path)
    except Exception:
        # fallback 防止崩溃
        icon_image = Image.new('RGB', (64, 64), (255, 255, 255))

    # 3. 创建系统托盘
    menu = (pystray.MenuItem('退出脚本', on_quit),)
    icon = pystray.Icon("AltKeyRemap", icon_image, "改键工具 (Alt+IJKL)", menu)

    icon.run()


if __name__ == "__main__":
    main()