import { state } from "../core/state.js?v=20260410d";
import { renderMessageContent } from "../core/utils.js?v=20260410d";

export function renderSendButton() {
  if (state.loading) {
    return `
      <button class="icon-button loading" type="submit" disabled aria-label="Processando">
        <span class="spinner"></span>
      </button>
    `;
  }
  return `
    <button class="icon-button" type="submit" aria-label="Enviar">
      <svg class="send-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 4l14 8-14 8 3.8-8L5 4z"></path>
      </svg>
    </button>
  `;
}

export function renderChatPage() {
  return `
    <section class="page-section chat-page">
      <header class="page-header compact-header">
        <div>
          <h1>Assistente Agent</h1>
          <p class="subtitle">Conversa com a API principal usando <code>user_id</code>, <code>chat_id</code> e a sess&atilde;o autenticada como <code>session_id</code>.</p>
        </div>
        <div class="button-row">
          <span class="badge email-badge">${state.user?.email || ""}</span>
        </div>
      </header>
      <div class="chat-shell">
        <div class="chat-thread">
          ${(state.messages || []).map((message) => `
            <div class="chat-row ${message.role === "user" ? "user" : "assistant"}">
              <div class="chat-bubble ${message.role === "user" ? "user" : "assistant"} glass">
                ${renderMessageContent(message)}
              </div>
            </div>
          `).join("") || `
            <div class="chat-empty">
              <h2>Como posso ajudar hoje?</h2>
              <p>Pergunte sobre os seus dados, relat&oacute;rios, auditoria, proje&ccedil;&otilde;es ou qualquer fluxo que o seu template disponibilizar.</p>
            </div>
          `}
        </div>
        <form class="composer glass" id="chat-form">
          <div class="composer-main">
            <textarea id="chat-question" placeholder="Pergunte alguma coisa" ${state.loading ? "disabled" : ""}></textarea>
            <div class="file-pill-row" id="selected-files-preview"></div>
          </div>
          <div class="composer-actions">
            <label class="icon-button subtle file-upload-button" aria-label="Anexar arquivos">
              <input id="chat-files" type="file" multiple ${state.loading ? "disabled" : ""} />
              <span>+</span>
            </label>
            ${renderSendButton()}
          </div>
        </form>
      </div>
    </section>
  `;
}
