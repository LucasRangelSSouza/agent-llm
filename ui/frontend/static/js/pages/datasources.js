import { state } from "../core/state.js?v=20260410d";
import { formatDateTime, normalizeDatasourceType, renderSwitch } from "../core/utils.js?v=20260410d";

export function renderDatasourcesPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Datasources</h1>
          <p class="subtitle">Conex&otilde;es reutiliz&aacute;veis para SQL, Athena e BigQuery com teste obrigat&oacute;rio antes de salvar.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.datasources.length} datasource(s)</span>
          ${renderSwitch({ checked: state.filters.datasourcesIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "datasourcesIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-datasource-form">Inserir datasource</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Tipo</th>
              <th>Tenant</th>
              <th>Resumo</th>
              <th>Credenciais</th>
              <th>&Uacute;ltimo teste</th>
              <th>Status</th>
              <th>A&ccedil;&otilde;es</th>
            </tr>
          </thead>
          <tbody>
            ${(state.datasources || []).map((item) => `
              <tr class="${item.is_active === false ? "row-inactive" : ""}">
                <td>${item.name}</td>
                <td>${normalizeDatasourceType(item.kind)}</td>
                <td>${item.tenant_name || item.tenant_id || "-"}</td>
                <td>${item.summary || "-"}</td>
                <td><code>${item.credentials?.aws_access_key_id || item.credentials?.username || item.credentials?.service_account_json || "-"}</code></td>
                <td>${item.last_test_at ? formatDateTime(item.last_test_at) : "Nunca testado"}</td>
                <td><span class="status-pill ${item.is_active === false ? "status-warn" : "status-ok"}">${item.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-datasource" data-id="${item.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="datasources" data-id="${item.id}" data-next-active="${item.is_active === false ? "true" : "false"}">${item.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="8" class="empty-state">Nenhum datasource cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
