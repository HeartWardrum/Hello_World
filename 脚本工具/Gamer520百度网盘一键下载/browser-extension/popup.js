const urlEl = document.getElementById("url");
const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");

function setStatus(text, ok) {
  statusEl.hidden = !text;
  statusEl.textContent = text || "";
  statusEl.className = "status " + (ok ? "ok" : "err");
}

function isSupported(url) {
  return (
    !!url &&
    /^https?:/i.test(url) &&
    /(gamer520\.com|gamers520\.com)/i.test(url)
  );
}

async function loadCurrentUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab?.url || "";
  urlEl.textContent = url || "(无)";
  const ok = isSupported(url);
  runBtn.disabled = !ok;
  if (!ok) setStatus("请先打开 gamer520 文章页", false);
  else setStatus("", true);
  return { tab, url, ok };
}

runBtn.addEventListener("click", async () => {
  runBtn.disabled = true;
  setStatus("正在唤起本机脚本…", true);
  try {
    const { url, ok } = await loadCurrentUrl();
    if (!ok) throw new Error("当前不是 gamer520 页面");

    // 用户手势下直接触发自定义协议
    const protocolUrl = "gamer520dl:" + url;
    const iframe = document.createElement("iframe");
    iframe.style.display = "none";
    iframe.src = protocolUrl;
    document.body.appendChild(iframe);
    setTimeout(() => iframe.remove(), 2500);

    setStatus("已唤起。若浏览器询问「打开外部应用」，请点允许。", true);
    setTimeout(() => window.close(), 1100);
  } catch (err) {
    setStatus(String(err?.message || err), false);
    runBtn.disabled = false;
  }
});

loadCurrentUrl().catch((err) => {
  urlEl.textContent = "(读取失败)";
  setStatus(String(err?.message || err), false);
  runBtn.disabled = true;
});
