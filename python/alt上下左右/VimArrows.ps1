$code = @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class VimParser {
    private const int WH_KEYBOARD_LL = 13;
    private const uint LLKHF_EXTENDED = 0x01;
    private const uint LLKHF_INJECTED = 0x10;
    
    private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    private const uint KEYEVENTF_KEYUP = 0x0002;

    [DllImport("user32.dll")]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, IntPtr hMod, uint dwThreadId);
    [DllImport("user32.dll")]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);
    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetModuleHandle(string lpModuleName);
    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);
    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);
    private static IntPtr _hookID = IntPtr.Zero;
    private static LowLevelKeyboardProc _proc = HookCallback;

    private static bool _logicalAltReleased = false;

    // 精确追踪每个按键是否处于被映射的状态
    private static bool _iIsArrow = false;
    private static bool _jIsArrow = false;
    private static bool _kIsArrow = false;
    private static bool _lIsArrow = false;

    public static void Start() {
        _hookID = SetHook(_proc);
        Application.Run();
    }
    
    public static void Stop() {
        UnhookWindowsHookEx(_hookID);
    }
    
    private static IntPtr SetHook(LowLevelKeyboardProc proc) {
        using (var cp = System.Diagnostics.Process.GetCurrentProcess())
        using (var cm = cp.MainModule) {
            return SetWindowsHookEx(WH_KEYBOARD_LL, proc, GetModuleHandle(cm.ModuleName), 0);
        }
    }
    
    private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam) {
        if (nCode >= 0) {
            int vkCode = Marshal.ReadInt32(lParam);
            int flags = Marshal.ReadInt32(lParam, 8);
            
            // 忽略我们自己注入的按键，防止无限死循环
            if ((flags & LLKHF_INJECTED) != 0) {
                return CallNextHookEx(_hookID, nCode, wParam, lParam);
            }

            bool isKeyDown = (wParam == (IntPtr)0x0100 || wParam == (IntPtr)0x0104);
            bool isKeyUp = (wParam == (IntPtr)0x0101 || wParam == (IntPtr)0x0105);

            // 识别左侧 Alt (包含 0xA4 和可能被系统转换的 0x12)
            bool isLAlt = (vkCode == 0xA4) || (vkCode == 0x12 && (flags & LLKHF_EXTENDED) == 0);

            // 终极防卡死保险：只要系统收到物理左 Alt 的松开事件，强制清空所有 Alt 状态
            if (isLAlt && isKeyUp) {
                _logicalAltReleased = false;
                keybd_event(0xA4, 0x38, KEYEVENTF_KEYUP, 0); // 左 Alt 释放
                keybd_event(0x12, 0x38, KEYEVENTF_KEYUP, 0); // 宽泛 Alt 释放
            }

            bool isI = (vkCode == 0x49);
            bool isJ = (vkCode == 0x4A);
            bool isK = (vkCode == 0x4B);
            bool isL = (vkCode == 0x4C);

            if (isI || isJ || isK || isL) {
                if (isKeyDown) {
                    // 穿透系统消息队列，直接探测硬件层面你手指是否贴在左 Alt 上
                    bool physicalAltDown = (GetAsyncKeyState(0xA4) & 0x8000) != 0;
                    
                    // 判断当前按键是否需要被当作方向键
                    bool treatAsArrow = false;
                    if (isI && (physicalAltDown || _iIsArrow)) { treatAsArrow = true; _iIsArrow = true; }
                    if (isJ && (physicalAltDown || _jIsArrow)) { treatAsArrow = true; _jIsArrow = true; }
                    if (isK && (physicalAltDown || _kIsArrow)) { treatAsArrow = true; _kIsArrow = true; }
                    if (isL && (physicalAltDown || _lIsArrow)) { treatAsArrow = true; _lIsArrow = true; }

                    if (treatAsArrow) {
                        if (physicalAltDown && !_logicalAltReleased) {
                            keybd_event(0xFC, 0, 0, 0); // 防系统菜单拦截 Dummy Down
                            keybd_event(0xFC, 0, KEYEVENTF_KEYUP, 0); // Dummy Up
                            keybd_event(0xA4, 0x38, KEYEVENTF_KEYUP, 0); // 逻辑上释放左 Alt
                            keybd_event(0x12, 0x38, KEYEVENTF_KEYUP, 0); 
                            _logicalAltReleased = true;
                        }

                        byte target = 0;
                        if (isI) target = 0x26;
                        if (isJ) target = 0x25;
                        if (isK) target = 0x28;
                        if (isL) target = 0x27;

                        keybd_event(target, 0, KEYEVENTF_EXTENDEDKEY, 0);
                        return (IntPtr)1; // 吞掉原始的 IKJL
                    }
                } 
                else if (isKeyUp) {
                    bool wasArrow = false;
                    byte target = 0;

                    if (isI && _iIsArrow) { target = 0x26; _iIsArrow = false; wasArrow = true; }
                    if (isJ && _jIsArrow) { target = 0x25; _jIsArrow = false; wasArrow = true; }
                    if (isK && _kIsArrow) { target = 0x28; _kIsArrow = false; wasArrow = true; }
                    if (isL && _lIsArrow) { target = 0x27; _lIsArrow = false; wasArrow = true; }

                    if (wasArrow) {
                        keybd_event(target, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0);

                        // 只有在没有任何方向键残留时，才去判断是否恢复 Alt
                        if (!_iIsArrow && !_jIsArrow && !_kIsArrow && !_lIsArrow) {
                            // 再次直接读取硬件探测
                            bool physicalAltDown = (GetAsyncKeyState(0xA4) & 0x8000) != 0;
                            if (physicalAltDown) {
                                // 硬件证明你手指还在 Alt 上，恢复逻辑按下状态
                                keybd_event(0xA4, 0x38, 0, 0);
                                keybd_event(0x12, 0x38, 0, 0);
                                _logicalAltReleased = false;
                            } else {
                                // 硬件证明你手指已经松开了，下达死命令彻底清理 Alt 状态
                                keybd_event(0xA4, 0x38, KEYEVENTF_KEYUP, 0);
                                keybd_event(0x12, 0x38, KEYEVENTF_KEYUP, 0);
                                _logicalAltReleased = false;
                            }
                        }
                        return (IntPtr)1;
                    }
                }
            }
        }
        return CallNextHookEx(_hookID, nCode, wParam, lParam);
    }
}
'@
Add-Type -TypeDefinition $code -ReferencedAssemblies "System.Windows.Forms"
[VimParser]::Start()