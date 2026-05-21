$code = @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class VimParser {
    private const int WH_KEYBOARD_LL = 13;
    private const uint LLKHF_EXTENDED = 0x01;
    private const uint LLKHF_INJECTED = 0x10;

    private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    private const uint KEYEVENTF_KEYUP       = 0x0002;

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

    // 物理左 Alt 是否按下（纯状态追踪，不影响系统）
    private static bool _physicalLAltDown = false;

    // 是否已向系统发送过 dummy 键打断 Alt（即系统已不再持有 Alt 修饰）
    // true  = 系统侧 Alt 已被 dummy 断开，可以安全注入方向键
    // false = 系统侧 Alt 还活着，下次 IJKL 按下需要先发 dummy
    private static bool _altBroken = false;

    // 四个字母键当前是否以方向键身份按下
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
            int flags  = Marshal.ReadInt32(lParam, 8);

            // 过滤自身注入
            if ((flags & LLKHF_INJECTED) != 0)
                return CallNextHookEx(_hookID, nCode, wParam, lParam);

            bool isKeyDown = (wParam == (IntPtr)0x0100 || wParam == (IntPtr)0x0104);
            bool isKeyUp   = (wParam == (IntPtr)0x0101 || wParam == (IntPtr)0x0105);
            bool isLAlt    = (vkCode == 0xA4) || (vkCode == 0x12 && (flags & LLKHF_EXTENDED) == 0);

            // ── 处理物理左 Alt ──────────────────────────────────────────────
            if (isLAlt) {
                if (isKeyDown) {
                    _physicalLAltDown = true;
                    // 如果上一轮用过 IJKL（_altBroken=true），说明系统侧 Alt 已被断开。
                    // 这次 Alt↓ 如果放进系统，方向键注入时会变成 Alt+方向键。
                    // 所以直接吃掉，_physicalLAltDown 已更新，后续 IJKL 判断不受影响。
                    if (_altBroken)
                        return (IntPtr)1;
                }
                else if (isKeyUp) {
                    _physicalLAltDown = false;
                    if (_altBroken) {
                        // 所有方向键都已弹起，完全结束本轮，重置状态
                        if (!_iIsArrow && !_jIsArrow && !_kIsArrow && !_lIsArrow)
                            _altBroken = false;
                        // 吃掉 Alt↑，系统从未见过这个 Alt，不会有残留
                        return (IntPtr)1;
                    }
                }
            }

            // ── 处理 I / J / K / L ──────────────────────────────────────────
            bool isIJKL = (vkCode == 0x49 || vkCode == 0x4A || vkCode == 0x4B || vkCode == 0x4C);

            if (isIJKL) {
                if (isKeyDown && _physicalLAltDown) {
                    if (!_altBroken) {
                        // 首次触发：发 dummy 键打断系统侧的 Alt 修饰
                        keybd_event(0xFC, 0, 0, 0);
                        keybd_event(0xFC, 0, KEYEVENTF_KEYUP, 0);
                        // 再显式释放系统侧 Alt（dummy 键本身已经能打断菜单触发，
                        // 但为保险起见，把系统 Alt 状态也清干净）
                        keybd_event(0xA4, 0, KEYEVENTF_KEYUP, 0);
                        keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0);
                        _altBroken = true;
                    }

                    byte target = 0;
                    if (vkCode == 0x49) { target = 0x26; _iIsArrow = true; }  // I → Up
                    if (vkCode == 0x4A) { target = 0x25; _jIsArrow = true; }  // J → Left
                    if (vkCode == 0x4B) { target = 0x28; _kIsArrow = true; }  // K → Down
                    if (vkCode == 0x4C) { target = 0x27; _lIsArrow = true; }  // L → Right

                    // 此时系统侧无 Alt，注入的方向键是纯净的
                    keybd_event(target, 0, KEYEVENTF_EXTENDEDKEY, 0);
                    return (IntPtr)1;
                }
                else if (isKeyUp) {
                    bool wasArrow = false;
                    byte target   = 0;

                    if (vkCode == 0x49 && _iIsArrow) { target = 0x26; _iIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4A && _jIsArrow) { target = 0x25; _jIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4B && _kIsArrow) { target = 0x28; _kIsArrow = false; wasArrow = true; }
                    if (vkCode == 0x4C && _lIsArrow) { target = 0x27; _lIsArrow = false; wasArrow = true; }

                    if (wasArrow) {
                        keybd_event(target, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0);

                        // 所有方向键弹起且物理 Alt 也已释放 → 重置
                        if (!_iIsArrow && !_jIsArrow && !_kIsArrow && !_lIsArrow && !_physicalLAltDown)
                            _altBroken = false;

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
