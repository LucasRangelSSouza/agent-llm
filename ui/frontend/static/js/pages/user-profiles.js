import { hasPermission, state } from "../core/state.js?v=20260410d";
import { escapeHtml, renderSwitch } from "../core/utils.js?v=20260410d";

export const PROFILE_RESOURCES = [
  ["templates", "Templates"],
  ["ai_services", "Servicos de IA"],
  ["datasources", "Datasources"],
  ["files", "Arquivos"],
  ["secrets", "Secrets"],
  ["users", "Usuarios"],
  ["preferences", "Preferencias"],
  ["user_profiles", "Perfis de Usuario"],
];

export const PROFILE_ACTIONS = [
  ["view", "Visualizar"],
  ["edit", "Editar"],
  ["create", "Criar"],
  ["view_inactive", "Visualizar Inativos"],
  ["deactivate", "Inativar"],
];

export function renderProfilesPage() {
  return `
    <section class="page-section">
      <header class="page-header">
        <div>
          <h1>Perfis de Usuario</h1>
          <p class="subtitle">Defina as permissoes por tela para os usuarios do tenant.</p>
        </div>
        <div class="button-row">
          ${renderSwitch({
            checked: state.filters.userProfilesIncludeInactive,
            label: "Ver inativos",
            action: "toggle-filter",
            actionValue: "userProfilesIncludeInactive",
          })}
          <button class="btn btn-primary" data-action="open-user-profile-form">Criar perfil</button>
        </div>
      </header>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Perfil</th>
              <th>Tenant</th>
              <th>Status</th>
              <th>Acoes</th>
            </tr>
          </thead>
          <tbody>
            ${(state.userProfiles || []).map((profile) => `
              <tr class="${profile.is_active === false ? "row-inactive" : ""}">
                <td><strong>${escapeHtml(profile.name)}</strong></td>
                <td>${escapeHtml(profile.tenant_name || "Global")}</td>
                <td><span class="status-pill ${profile.is_active === false ? "status-warn" : "status-ok"}">${profile.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary btn-small" data-action="edit-user-profile" data-id="${profile.id}">Editar</button>
                    <button class="btn btn-secondary btn-small" data-action="toggle-status" data-entity="user-profiles" data-id="${profile.id}" data-next-active="${profile.is_active === false}">
                      ${profile.is_active === false ? "Reativar" : "Inativar"}
                    </button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="4"><div class="empty-state">Nenhum perfil cadastrado.</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

export function canViewProfiles() {
  return hasPermission("user_profiles", "view");
}
