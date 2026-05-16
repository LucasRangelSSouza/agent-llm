import { state } from "../core/state.js?v=20260410d";
import { renderSwitch } from "../core/utils.js?v=20260410d";

export function renderTenantsPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Tenants</h1>
          <p class="subtitle">Cadastro central de empresas. Apenas o perfil master enxerga e altera essa &aacute;rea.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.tenants.length} tenant(s)</span>
          ${renderSwitch({ checked: state.filters.tenantsIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "tenantsIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-tenant-form">Inserir tenant</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Empresa</th>
              <th>CNPJ</th>
              <th>Raz&atilde;o social</th>
              <th>Status</th>
              <th>A&ccedil;&otilde;es</th>
            </tr>
          </thead>
          <tbody>
            ${(state.tenants || []).map((tenant) => `
              <tr class="${tenant.is_active === false ? "row-inactive" : ""}">
                <td>${tenant.name}</td>
                <td>${tenant.cnpj || "-"}</td>
                <td>${tenant.legal_name || "-"}</td>
                <td><span class="status-pill ${tenant.is_active === false ? "status-warn" : "status-ok"}">${tenant.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-tenant" data-id="${tenant.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="tenants" data-id="${tenant.id}" data-next-active="${tenant.is_active === false ? "true" : "false"}">${tenant.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="5" class="empty-state">Nenhum tenant cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
