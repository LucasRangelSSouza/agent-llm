import { state } from "../core/state.js?v=20260410d";

export function renderLoginPage() {
  return `
    <div class="login-shell">
      <form class="login-card glass" id="login-form">
        <div class="brand-badge">A</div>
        <h1>Agent Workspace</h1>
        <p class="subtitle">Login administrativo para operar tenants, usu&aacute;rios, templates, datasources e chat com a IA.</p>
        <div class="form-grid">
          <div class="field">
            <label>E-mail</label>
            <input type="email" name="email" placeholder="master@agent.local" required />
          </div>
          <div class="field">
            <label>Senha</label>
            <input type="password" name="password" placeholder="Sua senha" required />
          </div>
          <button class="btn btn-primary" type="submit">Entrar</button>
        </div>
        ${state.error ? `<div class="error-banner">${state.error}</div>` : ""}
      </form>
    </div>
  `;
}
