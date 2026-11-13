const NATIVE_HOST = "com.gamer520.baidu";
const ALLOWED = /(^|\.)gamer520\.com$/i;
const ALLOWED_HOSTS = /(^|\.)gamers520\.com$/i;

function isSupportedUrl(url) {
  try {
    const u = new URL(url);
    return (
      (ALLOWED.test(u.hostname) || ALLOWED_HOSTS.test(u.hostname)) &&
      (u.protocol === "http:" || u.protocol === "https:")
    );
  } catch {
    return false;
  }
}

async function notify(title, message) {
  try {
    await chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title,
      message
    });
  } catch {
    // ignore
  }
}

function runViaNative(url) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendNativeMessage(NATIVE_HOST, { url }, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!response?.ok) {
          reject(new Error(response?.error || "本地主机返回失败"));
          return;
        }
        resolve(response);
      });
    } catch (err) {
      reject(err);
    }
  });
}

async function runViaProtocol(url) {
  // 协议兜底：前台打开，且长时间不关标签，避免「打开」确认框瞬间消失
  const protocolUrl = "gamer520dl:" + url;
  const temp = await chrome.tabs.create({ url: protocolUrl, active: true });
  await notify(
    "请点击「打开」",
    "浏览器会弹出确认框，请点「打开」。此标签会保留约 1 分钟。"
  );
  setTimeout(() => {
    chrome.tabs.remove(temp.id).catch(() => {});
  }, 60000);
  return { ok: true, via: "protocol" };
}

async function runForTab(tab) {
  const url = tab?.url || "";
  if (!url || /^(chrome|edge|about|devtools):/i.test(url)) {
    throw new Error("请先打开 gamer520 文章页再点图标");
  }
  if (!isSupportedUrl(url)) {
    throw new Error("当前不是 gamer520 页面");
  }

  try {
    await runViaNative(url);
    await notify("已启动下载脚本", "已通过本地通道唤起，无需点「打开」。");
    return { ok: true, via: "native" };
  } catch (nativeErr) {
    // Native Messaging 未安装时回退协议
    console.warn("native failed:", nativeErr);
    await runViaProtocol(url);
    return { ok: true, via: "protocol", nativeError: String(nativeErr?.message || nativeErr) };
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  try {
    await runForTab(tab);
  } catch (err) {
    await notify("无法启动", String(err?.message || err));
  }
});
