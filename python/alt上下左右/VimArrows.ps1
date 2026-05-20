$code = @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class VimParser {
    private const int WH_KEYBOARD_LL = 13;
    private const uint LLKHF_INJECTED = 0x10;

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

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);
    private static IntPtr _hookID = IntPtr.Zero;
    private static LowLevelKeyboardProc _proc = HookCallback;

    // 精确的状态追踪机制
    private static bool _physicalLAltDown = false;
    private static bool _virtualLAltReleased = false;

    // 记录各按键是否处于映射为方向键的状态
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
            // 偏移 8 字节读取 flags
            int flags = Marshal.ReadInt32(lParam, 8);
            
            // 核心修复：忽略由 keybd_event 注入的模拟按键，防止引发系统状态机混乱
            if ((flags & LLKHF_INJECTED) != 0) {
                return CallNextHookEx(_hookID, nCode, wParam, lParam);
            }

            bool isKeyDown = (wParam == (IntPtr)0x0100 || wParam == (IntPtr)0x0104);
            bool isKeyUp = (wParam == (IntPtr)0x0101 || wParam == (IntPtr)0x0105);

            // 监听真实的物理 左 Alt 键 (VK_LMENU = 0xA4)
            if (vkCode == 0xA4) {
                if (isKeyDown) {
                    _physicalLAltDown = true;
                } else if (isKeyUp) {
                    _physicalLAltDown = false;
                    _virtualLAltReleased = false; 
                }
            }

            // 处理 I (0x49), J (0x4A), K (0x4B), L (0x4C)
            if (vkCode == 0x49 || vkCode == 0x4A || vkCode == 0x4B || vkCode == 0x4C) {
                if (isKeyDown) {
                    if (_physicalLAltDown) {
                        if (!_virtualLAltReleased) {
                            // 防菜单焦点夺取的 Dummy 按键 (0xFC)
                            keybd_event(0xFC, 0, 0, 0); 
                            keybd_event(0xFC, 0, 2, 0); 
                            // 逻辑上释放左 Alt 键，防止变成 Alt+方向键
                            keybd_event(0xA4, 0, 2, 0); 
                            _virtualLAltReleased = true;
                        }

                        byte target = 0;
                        if (vkCode == 0x49) { target = 0x26; _iIsArrow = true; } // Up
                        if (vkCode == 0x4A) { target = 0x25; _jIsArrow = true; } // Left
                        if (vkCode == 0x4B) { target = 0x28; _kIsArrow = true; } // Down
                        if (vkCode == 0x4C) { target = 0x27; _lIsArrow = true; } // Right

                        keybd_event(target, 0, 0, 0);
                        return (IntPtr)1; // 拦截按键
                    }
                } 
                else if (isKeyUp) {
                    bool wasArrow = false;
                    byte target = 0;

                    if (vkCode == 0x49 && _iIsArrow) { target = 0x26; _iIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4A && _jIsArrow) { target = 0x25; _jIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4B && _kIsArrow) { target = 0x28; _kIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4C && _lIsArrow) { target = 0x27; _lIsArrow = false; wasArrow = true; }

                    if (wasArrow) {
                        // 释放对应的方向键
                        keybd_event(target, 0, 2, 0);

                        // 核心修复：仅当用户仍然按住物理左 Alt 且没有其他映射键未释放时，才逻辑上恢复 Alt
                        if (_physicalLAltDown && !_iIsArrow && !_jIsArrow && !_kIsArrow && !_lIsArrow) {
                            keybd_event(0xA4, 0, 0, 0);
                            _virtualLAltReleased = false;
                        }
                        return (IntPtr)1; // 拦截按键
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