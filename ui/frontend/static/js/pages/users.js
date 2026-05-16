import { state } from "../core/state.js?v=20260410d";
import { renderSwitch } from "../core/utils.js?v=20260410d";

export function renderUsersPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Usu&aacute;rios</h1>
          <p class="subtitle">Gest&atilde;o de acesso com v&iacute;nculo de tenant, papel, telefone e especialidade.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.users.length} usu&aacute;rio(s)</span>
          ${renderSwitch({ checked: state.filters.usersIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "usersIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-user-form">Inserir usu&aacute;rio</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>E-mail</th>
              <th>Tenant</th>
              <th>Papel</th>
              <th>Perfil</th>
              <th>Telefone</th>
              <th>Status</th>
              <th>A&ccedil;&otilde;es</th>
            </tr>
          </thead>
          <tbody>
            ${(state.users || []).map((user) => `
              <tr class="${user.is_active === false ? "row-inactive" : ""}">
                <td>${user.full_name}</td>
                <td>${user.email}</td>
                <td>${user.tenant_name || user.tenant_id || "-"}</td>
                <td>${user.role}</td>
                <td>${user.profile_name || "-"}</td>
                <td>${user.phone || "-"}</td>
                <td><span class="status-pill ${user.is_active === false ? "status-warn" : "status-ok"}">${user.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-user" data-id="${user.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="users" data-id="${user.id}" data-next-active="${user.is_active === false ? "true" : "false"}">${user.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="8" class="empty-state">Nenhum usu&aacute;rio cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
