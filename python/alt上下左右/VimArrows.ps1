$code = @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class VimParser {
    private const int WH_KEYBOARD_LL = 13;
    
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
    private static bool _logicalAltUp = false;

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
            bool isKeyDown = (wParam == (IntPtr)0x0100 || wParam == (IntPtr)0x0104);
            bool isKeyUp = (wParam == (IntPtr)0x0101 || wParam == (IntPtr)0x0105);

            if (vkCode == 0x49 || vkCode == 0x4B || vkCode == 0x4A || vkCode == 0x4C) {
                bool physicalAlt = (GetAsyncKeyState(0x12) & 0x8000) != 0;
                if (physicalAlt || _logicalAltUp) {
                    byte target = 0;
                    if (vkCode == 0x49) target = 0x26;
                    if (vkCode == 0x4B) target = 0x28;
                    if (vkCode == 0x4A) target = 0x25;
                    if (vkCode == 0x4C) target = 0x27;

                    if (isKeyDown) {
                        if (!_logicalAltUp) {
                            keybd_event(0xFC, 0, 0, 0); 
                            keybd_event(0xFC, 0, 2, 0); 
                            keybd_event(0x12, 0, 2, 0); 
                            _logicalAltUp = true;
                        }
                        keybd_event(target, 0, 0, 0);
                    } 
                    else if (isKeyUp) {
                        keybd_event(target, 0, 2, 0);
                        keybd_event(0x12, 0, 0, 0); 
                        keybd_event(0xFC, 0, 0, 0); 
                        keybd_event(0xFC, 0, 2, 0); 
                        _logicalAltUp = false;
                    }
                    return (IntPtr)1;
                }
            }
            if (vkCode == 0x12 && isKeyUp) {
                _logicalAltUp = false;
            }
        }
        return CallNextHookEx(_hookID, nCode, wParam, lParam);
    }
}
'@
Add-Type -TypeDefinition $code -ReferencedAssemblies "System.Windows.Forms"
[VimParser]::Start()