import { state } from "../core/state.js?v=20260410d";
import { formatDateTime, renderSwitch } from "../core/utils.js?v=20260410d";

export function renderSecretsPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Secrets</h1>
          <p class="subtitle">Segredos por tenant para chaves de API, tokens e credenciais vinculaveis aos agentes.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.secrets.length} secret(s)</span>
          ${renderSwitch({ checked: state.filters.secretsIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "secretsIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-secret-form">Inserir secret</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Valor</th>
              <th>Tenant</th>
              <th>Atualizado</th>
              <th>Status</th>
              <th>Acoes</th>
            </tr>
          </thead>
          <tbody>
            ${(state.secrets || []).map((item) => `
              <tr class="${item.is_active === false ? "row-inactive" : ""}">
                <td>${item.name}</td>
                <td><code>${item.secret_value || "-"}</code></td>
                <td>${item.tenant_name || item.tenant_id || "-"}</td>
                <td>${item.updated_at ? formatDateTime(item.updated_at) : "-"}</td>
                <td><span class="status-pill ${item.is_active === false ? "status-warn" : "status-ok"}">${item.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-secret" data-id="${item.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="secrets" data-id="${item.id}" data-next-active="${item.is_active === false ? "true" : "false"}">${item.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="6" class="empty-state">Nenhum secret cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
