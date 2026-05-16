import { state } from "../core/state.js?v=20260410d";
import { formatDateTime, normalizeAIProvider, renderSwitch } from "../core/utils.js?v=20260410d";

export function renderAIServicesPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Servicos de IA</h1>
          <p class="subtitle">Credenciais e modelos por tenant para OpenAI, Claude, Gemini, Grok, DeepSeek e opcoes locais GGUF.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.aiServices.length} servico(s)</span>
          ${renderSwitch({ checked: state.filters.aiServicesIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "aiServicesIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-ai-service-form">Inserir servico</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Provider</th>
              <th>Modelo</th>
              <th>API Key</th>
              <th>Tenant</th>
              <th>Atualizado em</th>
              <th>Status</th>
              <th>Acoes</th>
            </tr>
          </thead>
          <tbody>
            ${(state.aiServices || []).map((item) => `
              <tr class="${item.is_active === false ? "row-inactive" : ""}">
                <td>${item.name}</td>
                <td>${normalizeAIProvider(item.provider)}</td>
                <td>${item.model_name || "-"}</td>
                <td><code>${item.api_key || "-"}</code></td>
                <td>${item.tenant_name || item.tenant_id || "-"}</td>
                <td>${item.updated_at ? formatDateTime(item.updated_at) : "-"}</td>
                <td><span class="status-pill ${item.is_active === false ? "status-warn" : "status-ok"}">${item.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-ai-service" data-id="${item.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="ai-services" data-id="${item.id}" data-next-active="${item.is_active === false ? "true" : "false"}">${item.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="8" class="empty-state">Nenhum servico de IA cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
