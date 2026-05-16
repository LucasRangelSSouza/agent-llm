import { canManageAdminAreas, canManageTenants, hasPermission, state } from "../core/state.js?v=20260410d";
import { escapeHtml, formatDateTime } from "../core/utils.js?v=20260410d";

export function renderSidebar() {
  const canAdmin = canManageAdminAreas();
  const canTenants = canManageTenants();
  const activeView = state.view === "template-editor" ? "templates" : state.view;
  const menu = [
    { view: "chat", label: "Novo chat", note: "Inicia uma nova conversa", action: "new-chat" },
    ...(canTenants ? [{ view: "tenants", label: "Tenants", note: "Empresas e ambientes", action: "view-tenants" }] : []),
    ...(canAdmin
      ? [
          ...(hasPermission("templates", "view") ? [{ view: "templates", label: "Templates", note: "Orquestracao dos agentes", action: "view-templates" }] : []),
          ...(hasPermission("ai_services", "view") ? [{ view: "ai-services", label: "Servicos de IA", note: "Chaves, modelos e providers", action: "view-ai-services" }] : []),
          ...(hasPermission("datasources", "view") ? [{ view: "datasources", label: "Datasources", note: "Conexoes e fontes", action: "view-datasources" }] : []),
          ...(hasPermission("files", "view") ? [{ view: "files", label: "Arquivos", note: "Uploads por tenant e referencias", action: "view-files" }] : []),
          ...(hasPermission("secrets", "view") ? [{ view: "secrets", label: "Secrets", note: "Chaves e tokens por tenant", action: "view-secrets" }] : []),
          ...(hasPermission("users", "view") ? [{ view: "users", label: "Usuarios", note: "Usuarios e acessos", action: "view-users" }] : []),
          ...(hasPermission("user_profiles", "view") ? [{ view: "user-profiles", label: "Perfis de Usuario", note: "Matriz de permissoes", action: "view-user-profiles" }] : []),
        ]
      : []),
    ...(hasPermission("preferences", "view") ? [{ view: "preferences", label: "Preferencias", note: "Tema e ajustes da interface", action: "open-preferences" }] : []),
  ];

  return `
    <aside class="sidebar glass">
      <div class="sidebar-scroll">
        <div class="sidebar-top">
          <div class="sidebar-logo">
            <div class="sidebar-logo-mark">A</div>
            <div>
              <div class="nav-label">Agent UI</div>
              <div class="nav-note">${escapeHtml(state.user?.full_name || "")}</div>
            </div>
          </div>
          ${menu
            .map(
              (item) => `
            <button class="nav-button ${activeView === item.view ? "active" : ""}" data-action="${item.action}">
              <div class="nav-label">${item.label}</div>
              <div class="nav-note">${item.note}</div>
            </button>
          `,
            )
            .join("")}
        </div>
        <div class="sidebar-section-title">
          <span>Chats anteriores</span>
          ${(state.chats || []).length ? `<button class="btn btn-ghost btn-small" data-action="hide-all-chats">Limpar</button>` : ""}
        </div>
        <div class="recent-list">
          ${(state.chats || [])
            .map(
              (chat) => `
            <div class="recent-chat-row ${state.activeChatId === chat.id ? "active" : ""}">
              <button class="recent-chat ${state.activeChatId === chat.id ? "active" : ""}" data-action="open-chat" data-chat-id="${chat.id}">
                <div class="recent-title">${escapeHtml(chat.title || "Chat")}</div>
                <div class="recent-meta">${formatDateTime(chat.updated_at || chat.created_at)}</div>
              </button>
              <button class="icon-button subtle recent-chat-close" data-action="hide-chat" data-chat-id="${chat.id}" title="Ocultar chat">&times;</button>
            </div>
          `,
            )
            .join("") || `<div class="empty-state compact">Nenhum chat ainda.</div>`}
        </div>
        <div class="sidebar-footer">
          <div class="profile-meta">
            <strong>${escapeHtml(state.user?.full_name || "")}</strong>
            <span class="nav-note">${escapeHtml(state.user?.role || "")}</span>
          </div>
          <div class="sidebar-footer-actions">
            <button class="btn btn-ghost" data-action="logout">Sair</button>
          </div>
        </div>
      </div>
    </aside>
  `;
}

export function renderMainShell(content) {
  const errorBanner = state.error
    ? `<div class="error-banner global-error-banner">${escapeHtml(state.error)}</div>`
    : "";
  const toast = state.toast
    ? `<div class="toast toast-${escapeHtml(state.toast.type || "success")}">${escapeHtml(state.toast.message || "")}</div>`
    : "";
  const isChatView = state.view === "chat";

  return `
    <div class="app-shell">
      ${renderSidebar()}
      <main class="main-panel glass">
        <div class="main-scroll ${isChatView ? "chat-main-scroll" : ""}">
          ${toast}
          ${errorBanner}
          ${content}
        </div>
      </main>
    </div>
  `;
}
