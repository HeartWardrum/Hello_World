import keyboard
import pystray
from PIL import Image
import threading
import os
import sys


def get_resource_path(relative_path):
    """ 获取资源绝对路径，适配 PyInstaller 打包后的路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def setup_keyboard():
    keyboard.add_hotkey('alt+i', lambda: keyboard.send('up'), suppress=True)
    keyboard.add_hotkey('alt+k', lambda: keyboard.send('down'), suppress=True)
    keyboard.add_hotkey('alt+j', lambda: keyboard.send('left'), suppress=True)
    keyboard.add_hotkey('alt+l', lambda: keyboard.send('right'), suppress=True)
    keyboard.wait()


def on_quit(icon, item):
    icon.stop()
    os._exit(0)


def main():
    # 1. 启动键盘监听
    threading.Thread(target=setup_keyboard, daemon=True).start()

    # 2. 加载你的 icon.ico
    icon_path = get_resource_path("icon.ico")
    try:
        icon_image = Image.open(icon_path)
    except Exception as e:
        # 如果找不到图标，备选方案是创建一个纯色块，防止程序崩溃
        icon_image = Image.new('RGB', (64, 64), (255, 255, 255))

    # 3. 创建托盘
    menu = (pystray.MenuItem('退出脚本', on_quit),)
    icon = pystray.Icon("AltKeyRemap", icon_image, "改键工具 (Alt+IJKL)", menu)

    icon.run()


if __name__ == "__main__":
    main()