/* Coastworks embed: iframe isolation, strict postMessage target, no HTML injection. */
(() => {
  const script = document.currentScript;
  if (!(script instanceof HTMLScriptElement) || !script.dataset.bot) return;
  const bot = script.dataset.bot;
  if (!/^[0-9a-f-]{36}$/.test(bot) || document.getElementById(`cw-${bot}`))
    return;
  const base = new URL(script.src).origin;
  const host = document.createElement("div");
  host.id = `cw-${bot}`;
  const root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent =
    ":host{all:initial}button{position:fixed;right:24px;bottom:24px;z-index:2147483000;border:0;border-radius:28px;background:#163b30;color:white;padding:17px 22px;font:600 15px Arial;cursor:pointer;box-shadow:0 4px 20px #0002}button:focus-visible{outline:3px solid #72a87f;outline-offset:4px}iframe{position:fixed;right:24px;bottom:90px;width:min(390px,calc(100vw - 32px));height:min(550px,calc(100dvh - 120px));z-index:2147483000;border:1px solid #cad6cd;border-radius:18px;box-shadow:0 12px 60px #0002;background:white}@media(max-width:480px){iframe{right:16px}button{right:16px;bottom:18px}}";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Prata med oss";
  button.setAttribute("aria-expanded", "false");
  const frame = document.createElement("iframe");
  frame.title = "Företagets AI-assistent";
  frame.hidden = true;
  frame.referrerPolicy = "no-referrer";
  frame.setAttribute(
    "sandbox",
    "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox",
  );
  let token = "",
    expires = 0,
    loaded = false;
  async function session() {
    if (Date.now() < expires) return;
    const response = await fetch(`${base}/api/widget/${bot}/session`, {
      method: "POST",
      credentials: "omit",
    });
    if (!response.ok) throw new Error("unavailable");
    const data = await response.json();
    token = data.token;
    expires = Date.now() + 12 * 60 * 1000;
  }
  function send() {
    frame.contentWindow?.postMessage({ type: "cw:session", bot, token }, base);
  }
  frame.addEventListener("load", () => {
    loaded = true;
    send();
  });
  window.addEventListener("message", (event) => {
    if (
      event.source === frame.contentWindow &&
      event.origin === base &&
      event.data?.type === "cw:ready" &&
      event.data.bot === bot
    )
      send();
  });
  button.addEventListener("click", async () => {
    if (!frame.hidden) {
      frame.hidden = true;
      button.textContent = "Prata med oss";
      button.setAttribute("aria-expanded", "false");
      return;
    }
    button.disabled = true;
    try {
      await session();
      if (!frame.src) frame.src = `${base}/embed/${bot}`;
      frame.hidden = false;
      button.textContent = "Stäng chatten";
      button.setAttribute("aria-expanded", "true");
      if (loaded) send();
      frame.focus();
    } catch {
      button.textContent = "Chatten är inte tillgänglig";
    } finally {
      button.disabled = false;
    }
  });
  root.append(style, frame, button);
  // Only show the launcher after server-side installation verification.
  session()
    .then(() => document.body.append(host))
    .catch(() => {});
})();
