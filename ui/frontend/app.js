const root = document.querySelector("#app");

function renderBootError(error) {
  if (!root) return;
  const message = error?.message || String(error || "Erro desconhecido");
  const stack = error?.stack || "";
  root.innerHTML = `
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px;">
      <div style="max-width:960px;width:100%;background:rgba(255,255,255,0.86);backdrop-filter:blur(22px);border:1px solid rgba(120,140,180,0.18);border-radius:28px;padding:28px 32px;box-shadow:0 30px 60px rgba(57,85,144,0.12);font-family:Arial,sans-serif;color:#1e2b45;">
        <h1 style="margin:0 0 12px;font-size:28px;">Falha ao iniciar o frontend</h1>
        <p style="margin:0 0 18px;line-height:1.6;">Um modulo JavaScript falhou durante a carga inicial da interface.</p>
        <pre style="white-space:pre-wrap;word-break:break-word;background:#f5f8ff;border-radius:18px;padding:18px;font-size:13px;line-height:1.5;overflow:auto;">${message}${stack ? `\n\n${stack}` : ""}</pre>
      </div>
    </div>
  `;
}

import("/static/js/main.js?v=20260410d").catch((error) => {
  console.error("Agent UI bootstrap failed:", error);
  renderBootError(error);
});
