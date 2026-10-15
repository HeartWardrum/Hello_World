# Win11 任务栏常驻序号

在任务栏应用图标左上角显示 1-9、0（第 10 个），方便用 Win+数字 快速切换窗口。

## 用法

1. 双击 `run.bat`（首次会自动安装依赖）

或手动：

```
pip install -r requirements.txt
python taskbar_numbers.py
```

2. 黑窗口里按 Enter 即可退出。

## 说明

- 仅支持 Windows（Win11 为主，Win10 也可能可用）
- 已处理高 DPI（如 125%/150% 缩放），坐标与任务栏对齐
- 数字叠在图标上，鼠标可穿透，不影响点击
- 大约每 0.7 秒刷新一次，图标增减会自动更新
- 最多显示 10 个：对应 Win+1 … Win+9、Win+0
