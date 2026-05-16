import { canManageTenants, state } from "../core/state.js?v=20260410d";
import { renderSwitch } from "../core/utils.js?v=20260410d";

export function renderTemplatesListPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Templates</h1>
          <p class="subtitle">Cada tenant pode ter v&aacute;rios templates, mas apenas uma vers&atilde;o deployada por vez.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.templates.length} template(s)</span>
          ${renderSwitch({ checked: state.filters.templatesIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "templatesIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="create-template">Criar template</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Template</th>
              <th>M&oacute;dulo</th>
              ${canManageTenants() ? "<th>Tenant</th>" : ""}
              <th>Vers&atilde;o ativa</th>
              <th>Status</th>
              <th>A&ccedil;&otilde;es</th>
            </tr>
          </thead>
          <tbody>
            ${(state.templates || []).map((item) => `
              <tr class="${item.is_active === false ? "row-inactive" : ""}">
                <td>${item.name}</td>
                <td>${item.module_name}</td>
                ${canManageTenants() ? `<td>${item.tenant_name || "-"}</td>` : ""}
                <td>${item.active_version_number ? `v${item.active_version_number}` : "-"}</td>
                <td><span class="status-pill ${item.is_active === false ? "status-warn" : "status-ok"}">${item.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-template" data-id="${item.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="export-template" data-id="${item.id}" ${item.versions_count ? "" : "disabled"}>Exportar</button>
                    <button class="btn btn-secondary" data-action="open-deploy-template" data-id="${item.id}">Deploy</button>
                    <button class="btn btn-secondary" data-action="toggle-template-status" data-id="${item.id}" data-next-active="${item.is_active === false ? "true" : "false"}" ${item.active_version_id && item.is_active !== false ? "disabled" : ""}>${item.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="${canManageTenants() ? "6" : "5"}" class="empty-state">Nenhum template cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
