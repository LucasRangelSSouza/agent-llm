import {
  addDraftAgent,
  bootstrapSession,
  createChat,
  deleteTemplate,
  deployTemplate,
  exportTemplate,
  hideAllChats,
  hideChat,
  loadAIService,
  loadAIServiceCatalog,
  loadAIServices,
  loadChats,
  loadDatasources,
  loadDatasource,
  loadFile,
  loadFiles,
  loadMessages,
  loadSecret,
  loadSecrets,
  loadTemplateDetail,
  loadTemplates,
  loadTenants,
  loadToolkits,
  loadUsers,
  loadUserProfiles,
  login,
  logout,
  openTemplateCreate,
  openTemplateEditor,
  saveAIService,
  saveDatasource,
  saveFile,
  saveSecret,
  saveTemplateVersion,
  saveTenant,
  saveUser,
  saveUserProfile,
  sendChatMessage,
  setTemplateStatus,
  testDatasource,
  toggleEntityStatus,
} from "./core/api.js?v=20260410d";
import { defaultAIServicePayload, defaultDatasourcePayload, persistPreferences, state } from "./core/state.js?v=20260410d";
import { renderMainShell } from "./components/layout.js?v=20260410d";
import { renderModal } from "./components/modals.js?v=20260410d";
import { renderAIServicesPage } from "./pages/ai-services.js?v=20260410d";
import { renderChatPage } from "./pages/chat.js?v=20260410d";
import { renderDatasourcesPage } from "./pages/datasources.js?v=20260410d";
import { renderFilesPage } from "./pages/files.js?v=20260410d";
import { renderLoginPage } from "./pages/login.js?v=20260410d";
import { renderSecretsPage } from "./pages/secrets.js?v=20260410d";
import { renderTemplateEditorPage } from "./pages/template-editor.js?v=20260410d";
import { renderTemplatesListPage } from "./pages/templates-list.js?v=20260410d";
import { renderTenantsPage } from "./pages/tenants.js?v=20260410d";
import { renderUsersPage } from "./pages/users.js?v=20260410d";
import { PROFILE_ACTIONS, PROFILE_RESOURCES, renderProfilesPage } from "./pages/user-profiles.js?v=20260410d";

const app = document.querySelector("#app");
let toastTimer = null;
let chatMutationObserver = null;
let chatResizeObserver = null;
let observedChatThread = null;

function renderFatalError(error) {
  const message = error?.message || "Erro desconhecido no frontend";
  const stack = error?.stack || "";
  if (!app) return;
  app.innerHTML = `
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px;">
      <div style="max-width:900px;width:100%;background:rgba(255,255,255,0.82);backdrop-filter:blur(24px);border:1px solid rgba(120,140,180,0.18);border-radius:28px;padding:28px 32px;box-shadow:0 30px 60px rgba(57,85,144,0.12);font-family:Arial,sans-serif;color:#1e2b45;">
        <h1 style="margin:0 0 12px;font-size:28px;">Erro ao carregar a interface</h1>
        <p style="margin:0 0 18px;line-height:1.6;">O frontend encontrou uma excecao antes de terminar a inicializacao.</p>
        <pre style="white-space:pre-wrap;word-break:break-word;background:#f5f8ff;border-radius:18px;padding:18px;font-size:13px;line-height:1.5;overflow:auto;">${message}${stack ? `\n\n${stack}` : ""}</pre>
      </div>
    </div>
  `;
}

if (!app) {
  throw new Error("Elemento #app nao encontrado no DOM.");
}

window.addEventListener("error", (event) => {
  renderFatalError(event.error || new Error(event.message || "Erro inesperado"));
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason instanceof Error ? event.reason : new Error(String(event.reason || "Promise rejeitada"));
  renderFatalError(reason);
});

function applyTheme() {
  document.documentElement.dataset.theme = state.preferences.theme;
}

function disconnectChatAutoPin() {
  if (chatMutationObserver) {
    chatMutationObserver.disconnect();
    chatMutationObserver = null;
  }
  if (chatResizeObserver) {
    chatResizeObserver.disconnect();
    chatResizeObserver = null;
  }
  observedChatThread = null;
}

function keepChatPinned() {
  const thread = document.querySelector(".chat-thread");
  const mainScroll = document.querySelector(".main-scroll");

  if (!thread && !mainScroll) return;

  const scrollElementToBottom = (element) => {
    if (!element) return;
    element.scrollTo({
      top: element.scrollHeight,
      behavior: "auto",
    });
  };

  const scrollToBottom = () => {
    scrollElementToBottom(thread);
    if (state.view === "chat") {
      scrollElementToBottom(mainScroll);
    }
    const lastRow = thread?.lastElementChild;
    if (lastRow?.scrollIntoView) {
      lastRow.scrollIntoView({ block: "end", inline: "nearest" });
    }
  };

  scrollToBottom();
  requestAnimationFrame(() => {
    scrollToBottom();
      requestAnimationFrame(scrollToBottom);
  });
  window.setTimeout(scrollToBottom, 40);
  window.setTimeout(scrollToBottom, 180);
  window.setTimeout(scrollToBottom, 320);
  window.setTimeout(scrollToBottom, 520);
}

function bindChatAutoPin() {
  const thread = document.querySelector(".chat-thread");
  if (state.view !== "chat" || !thread) {
    disconnectChatAutoPin();
    return;
  }

  if (observedChatThread === thread) return;

  disconnectChatAutoPin();
  observedChatThread = thread;

  chatMutationObserver = new MutationObserver(() => {
    keepChatPinned();
  });
  chatMutationObserver.observe(thread, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  if (typeof ResizeObserver !== "undefined") {
    chatResizeObserver = new ResizeObserver(() => {
      keepChatPinned();
    });
    chatResizeObserver.observe(thread);
    Array.from(thread.children).forEach((node) => {
      if (node instanceof HTMLElement) {
        chatResizeObserver.observe(node);
      }
    });
  }
}

function resetError() {
  state.error = "";
}

function showToast(message, type = "success") {
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  state.toast = { message, type };
  renderApp();
  toastTimer = window.setTimeout(() => {
    state.toast = null;
    renderApp();
  }, 3000);
}

function can(resource, action = "view") {
  if (state.user?.role === "master") return true;
  return Boolean(state.user?.permissions?.[resource]?.[action]);
}

function guard(resource, action = "view") {
  if (can(resource, action)) return true;
  showToast("Usuario sem permissao nesse recurso", "error");
  return false;
}

async function setView(view) {
  resetError();
  state.view = view;
  if (view === "chat") {
    await loadChats();
  }
  if (view === "tenants") {
    await loadTenants();
  }
  if (view === "users") {
    await Promise.all([loadUsers(), loadUserProfiles(), state.user?.role === "master" ? loadTenants() : Promise.resolve()]);
  }
  if (view === "user-profiles") {
    await Promise.all([loadUserProfiles(), state.user?.role === "master" ? loadTenants() : Promise.resolve()]);
  }
  if (view === "datasources") {
    await Promise.all([loadDatasources(), state.user?.role === "master" ? loadTenants() : Promise.resolve()]);
  }
  if (view === "files") {
    await Promise.all([loadFiles(), state.user?.role === "master" ? loadTenants() : Promise.resolve()]);
  }
  if (view === "secrets") {
    await Promise.all([loadSecrets(), state.user?.role === "master" ? loadTenants() : Promise.resolve()]);
  }
  if (view === "ai-services") {
    await Promise.all([
      loadAIServiceCatalog(),
      loadAIServices(),
      state.user?.role === "master" ? loadTenants() : Promise.resolve(),
    ]);
  }
  if (view === "templates") {
    await Promise.all([
      loadTemplates(),
      loadToolkits(),
      loadDatasources(),
      loadAIServiceCatalog(),
      loadAIServices(),
      state.user?.role === "master" ? loadTenants() : Promise.resolve(),
    ]);
  }
  renderApp();
}

function openModal(type, payload = {}) {
  state.modal = {
    type,
    payload,
    testing: false,
    saving: false,
    testResult: null,
    testedFingerprint: "",
  };
  renderApp();
}

function closeModal() {
  state.modal = null;
  renderApp();
}

function computeDatasourceFingerprint(payload) {
  const clone = { ...payload };
  delete clone.id;
  delete clone.datasource_id;
  delete clone.has_password;
  delete clone.has_aws_secret_access_key;
  delete clone.has_aws_session_token;
  delete clone.has_service_account_json;
  return JSON.stringify(clone);
}

function keepSecretValue(nextValue, currentValue, keepExisting) {
  if (nextValue) return nextValue;
  if (keepExisting) return currentValue || "";
  return "";
}

function readDatasourceForm() {
  const form = document.querySelector("#datasource-form");
  if (!form) return null;
  const formData = new FormData(form);
  const current = state.modal?.payload || defaultDatasourcePayload();
  return {
    ...current,
    id: formData.get("id") || current.id || null,
    datasource_id: formData.get("id") || current.datasource_id || null,
    name: formData.get("name") || "",
    kind: formData.get("kind") || current.kind,
    description: formData.get("description") || "",
    tenant_id: formData.get("tenant_id") || current.tenant_id || state.user?.tenant_id || null,
    is_active: formData.get("is_active") === "on",
    host: formData.get("host") || "",
    port: formData.get("port") ? Number(formData.get("port")) : null,
    database_name: formData.get("database_name") || "",
    schema_name: formData.get("schema_name") || "",
    username: formData.get("username") || "",
    password: keepSecretValue(formData.get("password"), current.password, current.has_password),
    ssl_mode: formData.get("ssl_mode") || "",
    catalog_name: formData.get("catalog_name") || "",
    region_name: formData.get("region_name") || "",
    output_location: formData.get("output_location") || "",
    workgroup: formData.get("workgroup") || "",
    aws_access_key_id: formData.get("aws_access_key_id") || "",
    aws_secret_access_key: keepSecretValue(formData.get("aws_secret_access_key"), current.aws_secret_access_key, current.has_aws_secret_access_key),
    aws_session_token: keepSecretValue(formData.get("aws_session_token"), current.aws_session_token, current.has_aws_session_token),
    project_id: formData.get("project_id") || "",
    dataset_name: formData.get("dataset_name") || "",
    location: formData.get("location") || "",
    gcs_temp_bucket: formData.get("gcs_temp_bucket") || "",
    service_account_json: keepSecretValue(formData.get("service_account_json"), current.service_account_json, current.has_service_account_json),
    sqlite_mode: formData.get("sqlite_mode") || "url",
    sqlite_path: formData.get("sqlite_path") || "",
    sqlite_url: formData.get("sqlite_url") || "",
    has_password: Boolean(current.has_password || formData.get("password")),
    has_aws_secret_access_key: Boolean(current.has_aws_secret_access_key || formData.get("aws_secret_access_key")),
    has_aws_session_token: Boolean(current.has_aws_session_token || formData.get("aws_session_token")),
    has_service_account_json: Boolean(current.has_service_account_json || formData.get("service_account_json")),
  };
}

function readAIServiceForm() {
  const form = document.querySelector("#ai-service-form");
  if (!form) return null;
  const formData = new FormData(form);
  const current = state.modal?.payload || defaultAIServicePayload();
  return {
    ...current,
    id: formData.get("id") || current.id || null,
    ai_service_id: formData.get("id") || current.ai_service_id || null,
    tenant_id: formData.get("tenant_id") || current.tenant_id || state.user?.tenant_id || null,
    provider: formData.get("provider") || current.provider || "openai",
    name: formData.get("name") || "",
    description: formData.get("description") || "",
    model_name: formData.get("model_name") || "",
    api_key: keepSecretValue(formData.get("api_key"), current.api_key, current.has_api_key),
    endpoint_url: formData.get("endpoint_url") || "",
    organization_id: formData.get("organization_id") || "",
    is_active: formData.get("is_active") === "on",
    has_api_key: Boolean(current.has_api_key || formData.get("api_key")),
  };
}

function updateTemplateField(field, value) {
  state.templateDraft = {
    ...state.templateDraft,
    [field]: value,
  };
  renderApp({ preserveScroll: true });
}

function updateTemplateAgentField(index, field, value) {
  const agents = [...(state.templateDraft?.agents || [])];
  const previousName = agents[index]?.name;
  agents[index] = { ...agents[index], [field]: value };

  if (field === "name" && previousName && previousName !== value) {
    for (let agentIndex = 0; agentIndex < agents.length; agentIndex += 1) {
      if (agentIndex === index) continue;
      agents[agentIndex] = {
        ...agents[agentIndex],
        allowed_interactions: (agents[agentIndex].allowed_interactions || []).map((item) => (item === previousName ? value : item)),
      };
    }
  }

  state.templateDraft = { ...state.templateDraft, agents };
  renderApp({ preserveScroll: true });
}

function removeTemplateAgent(index) {
  const nextAgents = (state.templateDraft?.agents || []).filter((_, agentIndex) => agentIndex !== index);
  const validNames = new Set(nextAgents.map((agent) => agent.name));
  state.templateDraft = {
    ...state.templateDraft,
    agents: nextAgents.map((agent, order) => ({
      ...agent,
      sort_order: order,
      allowed_interactions: (agent.allowed_interactions || []).filter((name) => validNames.has(name)),
    })),
  };
  renderApp({ preserveScroll: true });
}

function toggleTemplateDatasource(id, checked) {
  const datasourceIds = new Set(state.templateDraft?.datasource_ids || []);
  if (checked) datasourceIds.add(id);
  else datasourceIds.delete(id);
  state.templateDraft = {
    ...state.templateDraft,
    datasource_ids: [...datasourceIds],
  };
  renderApp({ preserveScroll: true });
}

function setTemplateAIService(id, checked) {
  state.templateDraft = {
    ...state.templateDraft,
    ai_service_id: checked ? id : null,
  };
  renderApp({ preserveScroll: true });
}

function toggleAgentTool(index, tool, checked) {
  const tools = new Set(state.templateDraft?.agents?.[index]?.tools || []);
  if (checked) tools.add(tool);
  else tools.delete(tool);
  updateTemplateAgentField(index, "tools", [...tools]);
}

function toggleAgentInteraction(index, target, checked) {
  const interactions = new Set(state.templateDraft?.agents?.[index]?.allowed_interactions || []);
  if (checked) interactions.add(target);
  else interactions.delete(target);
  updateTemplateAgentField(index, "allowed_interactions", [...interactions]);
}

function toggleAgentFile(index, fileId, checked) {
  const fileIds = new Set(state.templateDraft?.agents?.[index]?.file_ids || []);
  if (checked) fileIds.add(fileId);
  else fileIds.delete(fileId);
  updateTemplateAgentField(index, "file_ids", [...fileIds]);
}

function toggleAgentSecret(index, secretId, checked) {
  const secretIds = new Set(state.templateDraft?.agents?.[index]?.secret_ids || []);
  if (checked) secretIds.add(secretId);
  else secretIds.delete(secretId);
  updateTemplateAgentField(index, "secret_ids", [...secretIds]);
}

function setTemplateAgentCollapsed(index, isCollapsed) {
  const agents = [...(state.templateDraft?.agents || [])];
  if (!agents[index]) return;
  agents[index] = { ...agents[index], isCollapsed };
  state.templateDraft = { ...state.templateDraft, agents };
}

function setAllTemplateAgentsCollapsed(isCollapsed) {
  state.templateDraft = {
    ...state.templateDraft,
    agents: (state.templateDraft?.agents || []).map((agent) => ({ ...agent, isCollapsed })),
  };
  renderApp({ preserveScroll: true });
}

function renderContent() {
  if (!state.token || !state.user) return renderLoginPage();
  if (state.view === "tenants") return renderMainShell(renderTenantsPage());
  if (state.view === "users") return renderMainShell(renderUsersPage());
  if (state.view === "user-profiles") return renderMainShell(renderProfilesPage());
  if (state.view === "datasources") return renderMainShell(renderDatasourcesPage());
  if (state.view === "files") return renderMainShell(renderFilesPage());
  if (state.view === "secrets") return renderMainShell(renderSecretsPage());
  if (state.view === "ai-services") return renderMainShell(renderAIServicesPage());
  if (state.view === "templates") return renderMainShell(renderTemplatesListPage());
  if (state.view === "template-editor") return renderMainShell(renderTemplateEditorPage());
  return renderMainShell(renderChatPage());
}

function afterRender() {
  applyTheme();
  bindChatAutoPin();
  keepChatPinned();
  renderPlotlyEmbeds();
}

function renderPlotlyEmbeds() {
  if (typeof window.Plotly === "undefined") return;
  const targets = document.querySelectorAll(".plotly-embed[data-plotly]:not([data-rendered='true'])");
  targets.forEach((target) => {
    try {
      const payload = JSON.parse(decodeURIComponent(target.dataset.plotly || ""));
      window.Plotly.newPlot(
        target,
        payload.data || [],
        payload.layout || {},
        {
          responsive: true,
          displaylogo: false,
        },
      );
      target.dataset.rendered = "true";
    } catch (error) {
      target.innerHTML = `<div class="plotly-error">Não foi possível renderizar o gráfico interativo.</div>`;
      target.dataset.rendered = "true";
    }
  });
}

function renderApp(options = {}) {
  const preserveScroll = Boolean(options.preserveScroll);
  const mainScroll = preserveScroll ? document.querySelector(".main-scroll") : null;
  const previousScrollTop = mainScroll?.scrollTop ?? 0;
  app.innerHTML = `${renderContent()}${renderModal()}`;
  if (preserveScroll) {
    requestAnimationFrame(() => {
      const nextMainScroll = document.querySelector(".main-scroll");
      if (nextMainScroll) nextMainScroll.scrollTop = previousScrollTop;
    });
  }
  afterRender();
}

async function bootstrap() {
  try {
    app.innerHTML = `
      <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:Arial,sans-serif;color:#415172;">
        Carregando interface...
      </div>
    `;
    const ok = await bootstrapSession();
    if (ok) {
      await loadChats();
      if (state.chats.length) {
        await loadMessages(state.chats[0].id);
      }
    }
    renderApp();
  } catch (error) {
    renderFatalError(error);
  }
}

document.addEventListener("click", async (event) => {
  const overlay = event.target.classList?.contains("modal-overlay");
  if (overlay) {
    closeModal();
    return;
  }

  const actionEl = event.target.closest("[data-action]");
  if (!actionEl) return;
  const action = actionEl.dataset.action;

  try {
    resetError();

    if (action === "close-modal") return closeModal();
    if (action === "logout") {
      logout();
      return renderApp();
    }
    if (action === "open-preferences") return guard("preferences", "view") && openModal("preferences");
    if (action === "toggle-theme") {
      state.preferences.theme = state.preferences.theme === "dark" ? "light" : "dark";
      persistPreferences();
      return renderApp();
    }
    if (action === "toggle-filter") {
      const key = actionEl.dataset.actionValue;
      state.filters[key] = !state.filters[key];
      return setView(state.view === "template-editor" ? "templates" : state.view);
    }
    if (action === "new-chat") {
      await createChat();
      state.view = "chat";
      return renderApp();
    }
    if (action === "view-tenants") return setView("tenants");
    if (action === "view-users") return guard("users", "view") && setView("users");
    if (action === "view-user-profiles") return guard("user_profiles", "view") && setView("user-profiles");
    if (action === "view-datasources") return guard("datasources", "view") && setView("datasources");
    if (action === "view-files") return guard("files", "view") && setView("files");
    if (action === "view-secrets") return guard("secrets", "view") && setView("secrets");
    if (action === "view-ai-services") return guard("ai_services", "view") && setView("ai-services");
    if (action === "view-templates") return guard("templates", "view") && setView("templates");
    if (action === "open-chat") {
      state.view = "chat";
      await loadMessages(actionEl.dataset.chatId);
      return renderApp();
    }
    if (action === "hide-chat") {
      await hideChat(actionEl.dataset.chatId);
      if (state.activeChatId === actionEl.dataset.chatId) {
        state.activeChatId = state.chats[0]?.id || null;
        state.messages = [];
      }
      return renderApp();
    }
    if (action === "hide-all-chats") {
      await hideAllChats();
      state.activeChatId = null;
      state.messages = [];
      return renderApp();
    }
    if (action === "open-tenant-form") return openModal("tenant-form", {});
    if (action === "edit-tenant") {
      const item = state.tenants.find((tenant) => tenant.id === actionEl.dataset.id);
      return openModal("tenant-form", item);
    }
    if (action === "open-user-form") return guard("users", "create") && openModal("user-form", {});
    if (action === "edit-user") {
      if (!guard("users", "edit")) return;
      const item = state.users.find((user) => user.id === actionEl.dataset.id);
      return openModal("user-form", item);
    }
    if (action === "open-user-profile-form") return guard("user_profiles", "create") && openModal("user-profile-form", {});
    if (action === "edit-user-profile") {
      if (!guard("user_profiles", "edit")) return;
      const item = state.userProfiles.find((profile) => profile.id === actionEl.dataset.id);
      return openModal("user-profile-form", item);
    }
    if (action === "open-datasource-form") return guard("datasources", "create") && openModal("datasource-form", defaultDatasourcePayload());
    if (action === "open-file-form") return guard("files", "create") && openModal("file-form", {});
    if (action === "open-secret-form") return guard("secrets", "create") && openModal("secret-form", {});
    if (action === "open-ai-service-form") return guard("ai_services", "create") && openModal("ai-service-form", defaultAIServicePayload());
    if (action === "edit-datasource") {
      if (!guard("datasources", "edit")) return;
      const payload = await loadDatasource(actionEl.dataset.id);
      return openModal("datasource-form", payload);
    }
    if (action === "edit-ai-service") {
      if (!guard("ai_services", "edit")) return;
      const payload = await loadAIService(actionEl.dataset.id);
      return openModal("ai-service-form", payload);
    }
    if (action === "edit-file") {
      if (!guard("files", "edit")) return;
      const payload = await loadFile(actionEl.dataset.id);
      return openModal("file-form", payload);
    }
    if (action === "edit-secret") {
      if (!guard("secrets", "edit")) return;
      const payload = await loadSecret(actionEl.dataset.id);
      return openModal("secret-form", payload);
    }
    if (action === "test-datasource") {
      const payload = readDatasourceForm();
      state.modal.testing = true;
      renderApp();
      try {
        const result = await testDatasource(payload);
        state.modal.payload = { ...state.modal.payload, ...payload };
        state.modal.testResult = { ok: true, message: result.message };
        state.modal.testedFingerprint = computeDatasourceFingerprint(payload);
      } catch (error) {
        state.modal.testResult = { ok: false, message: error.message };
      } finally {
        state.modal.testing = false;
        renderApp();
      }
      return;
    }
    if (action === "toggle-status") {
      const permissionMap = {
        users: "users",
        datasources: "datasources",
        files: "files",
        secrets: "secrets",
        "ai-services": "ai_services",
        templates: "templates",
        "user-profiles": "user_profiles",
      };
      if (!guard(permissionMap[actionEl.dataset.entity] || actionEl.dataset.entity, "deactivate")) return;
      await toggleEntityStatus(actionEl.dataset.entity, actionEl.dataset.id, actionEl.dataset.nextActive === "true");
      showToast("Status atualizado com sucesso.");
      return setView(state.view);
    }
    if (action === "create-template") {
      if (!guard("templates", "create")) return;
      await openTemplateCreate();
      return renderApp();
    }
    if (action === "edit-template") {
      if (!guard("templates", "edit")) return;
      await openTemplateEditor(actionEl.dataset.id);
      return renderApp();
    }
    if (action === "export-template") {
      await exportTemplate(actionEl.dataset.id);
      showToast("Template exportado com sucesso.");
      return;
    }
    if (action === "back-to-templates") return setView("templates");
    if (action === "open-deploy-template" || action === "open-current-template-deploy") {
      const templateId = actionEl.dataset.id || state.templateDraft?.template_id || state.templateDetail?.template?.id;
      if (templateId) {
        await loadTemplateDetail(templateId);
        openModal("deploy-template", {
          template_id: templateId,
          version_id: state.templateVersionId || state.templateDetail?.versions?.[0]?.id || "",
        });
      }
      return;
    }
    if (action === "save-template-version") {
      await saveTemplateVersion();
      showToast("Template salvo com sucesso.");
      return renderApp();
    }
    if (action === "export-current-template") {
      const templateId = state.templateDraft?.template_id;
      const versionId = state.templateVersionId || state.templateDraft?.id || null;
      if (!templateId) throw new Error("Template ainda nao salvo.");
      await exportTemplate(templateId, versionId);
      showToast("Template exportado com sucesso.");
      return;
    }
    if (action === "toggle-template-status") {
      await setTemplateStatus(actionEl.dataset.id, actionEl.dataset.nextActive === "true");
      showToast("Status do template atualizado com sucesso.");
      return setView("templates");
    }
    if (action === "delete-template") {
      if (!window.confirm("Deseja realmente excluir este template?")) return;
      await deleteTemplate(actionEl.dataset.id);
      return setView("templates");
    }
    if (action === "add-template-agent") {
      addDraftAgent();
      return renderApp();
    }
    if (action === "remove-template-agent") {
      removeTemplateAgent(Number(actionEl.dataset.index));
      return;
    }
    if (action === "open-template-datasources") {
      return openModal("template-datasources");
    }
    if (action === "open-template-ai-service") {
      return openModal("template-ai-service");
    }
    if (action === "open-template-agent-tools") {
      return openModal("template-agent-tools", { agentIndex: Number(actionEl.dataset.agentIndex) });
    }
    if (action === "open-template-agent-interactions") {
      return openModal("template-agent-interactions", { agentIndex: Number(actionEl.dataset.agentIndex) });
    }
    if (action === "open-template-agent-files") {
      return openModal("template-agent-files", { agentIndex: Number(actionEl.dataset.agentIndex) });
    }
    if (action === "open-template-agent-secrets") {
      return openModal("template-agent-secrets", { agentIndex: Number(actionEl.dataset.agentIndex) });
    }
    if (action === "collapse-all-template-agents") {
      return setAllTemplateAgentsCollapsed(true);
    }
    if (action === "expand-all-template-agents") {
      return setAllTemplateAgentsCollapsed(false);
    }
  } catch (error) {
    state.error = error.message;
    if (state.modal) {
      state.modal.testResult = { ok: false, message: error.message };
    }
    renderApp();
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;

  try {
    if (target.matches("[data-action='toggle-theme']")) {
      state.preferences.theme = target.checked ? "dark" : "light";
      persistPreferences();
      return renderApp();
    }

    if (target.matches("[data-action='toggle-filter']")) {
      const key = target.dataset.actionValue;
      state.filters[key] = target.checked;
      return setView(state.view === "template-editor" ? "templates" : state.view);
    }

    if (target.matches("[data-template-field]")) {
      updateTemplateField(target.dataset.templateField, target.value);
      return;
    }

    if (target.matches("[data-template-datasource]")) {
      toggleTemplateDatasource(target.dataset.templateDatasource, target.checked);
      return;
    }

    if (target.matches("[data-template-ai-service]")) {
      setTemplateAIService(target.dataset.templateAiService, target.checked);
      return;
    }

    if (target.matches("[data-agent-field]")) {
      updateTemplateAgentField(Number(target.dataset.agentIndex), target.dataset.agentField, target.value);
      return;
    }

    if (target.matches("[data-agent-tool]")) {
      toggleAgentTool(Number(target.dataset.agentIndex), target.dataset.agentTool, target.checked);
      return;
    }

    if (target.matches("[data-agent-interaction]")) {
      toggleAgentInteraction(Number(target.dataset.agentIndex), target.dataset.agentInteraction, target.checked);
      return;
    }

    if (target.matches("[data-agent-file]")) {
      toggleAgentFile(Number(target.dataset.agentIndex), target.dataset.agentFile, target.checked);
      return;
    }

    if (target.matches("[data-agent-secret]")) {
      toggleAgentSecret(Number(target.dataset.agentIndex), target.dataset.agentSecret, target.checked);
      return;
    }

    if (target.matches("[data-action='select-template-version']")) {
      await openTemplateEditor(state.templateDraft?.template_id, target.value);
      return renderApp();
    }

    if (target.matches("[data-action='change-datasource-type']")) {
      state.modal.payload = { ...readDatasourceForm(), kind: target.value };
      state.modal.testedFingerprint = "";
      state.modal.testResult = null;
      return renderApp();
    }

    if (target.matches("[data-action='change-ai-provider']")) {
      const nextPayload = { ...readAIServiceForm(), provider: target.value };
      const providerCatalog = (state.aiServiceCatalog?.providers || []).find((item) => item.value === target.value);
      if (providerCatalog?.models?.length && !providerCatalog.models.includes(nextPayload.model_name)) {
        nextPayload.model_name = providerCatalog.models[0];
      }
      state.modal.payload = nextPayload;
      return renderApp();
    }

    if (target.matches("#deploy-template-form select[name='template_id']")) {
      await loadTemplateDetail(target.value);
      state.modal.payload.template_id = target.value;
      state.modal.payload.version_id = state.templateDetail?.versions?.[0]?.id || "";
      return renderApp();
    }
  } catch (error) {
    state.error = error.message;
    renderApp();
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;

  if (target.matches("[data-template-field]")) {
    state.templateDraft = {
      ...state.templateDraft,
      [target.dataset.templateField]: target.value,
    };
  }

  if (target.matches("[data-agent-field]")) {
    const index = Number(target.dataset.agentIndex);
    const agents = [...(state.templateDraft?.agents || [])];
    const previousName = agents[index]?.name;
    agents[index] = {
      ...agents[index],
      [target.dataset.agentField]: target.value,
    };
    if (target.dataset.agentField === "name" && previousName && previousName !== target.value) {
      for (let agentIndex = 0; agentIndex < agents.length; agentIndex += 1) {
        if (agentIndex === index) continue;
        agents[agentIndex] = {
          ...agents[agentIndex],
          allowed_interactions: (agents[agentIndex].allowed_interactions || []).map((item) => (item === previousName ? target.value : item)),
        };
      }
    }
    state.templateDraft = {
      ...state.templateDraft,
      agents,
    };
  }
});

document.addEventListener("toggle", (event) => {
  const details = event.target;
  if (!details.matches?.("[data-agent-card-index]")) return;
  setTemplateAgentCollapsed(Number(details.dataset.agentCardIndex), !details.open);
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!target.matches("#chat-files")) return;
  const preview = document.querySelector("#selected-files-preview");
  if (!preview) return;
  const files = Array.from(target.files || []);
  preview.innerHTML = files.map((file) => `<span class="file-pill">${file.name}</span>`).join("");
});

document.addEventListener("submit", async (event) => {
  try {
    if (event.target.matches("#login-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      resetError();
      await login(form.get("email"), form.get("password"));
      await loadChats();
      if (state.chats.length) await loadMessages(state.chats[0].id);
      return renderApp();
    }

    if (event.target.matches("#chat-form")) {
      event.preventDefault();
      const textarea = document.querySelector("#chat-question");
      const fileInput = document.querySelector("#chat-files");
      const question = textarea.value.trim();
      const files = Array.from(fileInput?.files || []);
      if (!question && !files.length) return;
      resetError();
      state.loading = true;
      const attachmentNote = files.length ? `\n\nArquivos anexados: ${files.map((file) => file.name).join(", ")}` : "";
      state.messages = [...state.messages, { role: "user", content: `${question || "Arquivo enviado"}${attachmentNote}` }];
      renderApp();
      try {
        await sendChatMessage(question || "Analise os arquivos enviados.", files);
        await loadChats();
        await loadMessages(state.activeChatId);
      } catch (error) {
        state.messages = [...state.messages, { role: "assistant", content: `Erro: ${error.message}` }];
      } finally {
        state.loading = false;
        renderApp();
      }
      return;
    }

    if (event.target.matches("#tenant-form")) {
      event.preventDefault();
      await saveTenant(Object.fromEntries(new FormData(event.target).entries()));
      closeModal();
      showToast("Tenant salvo com sucesso.");
      return setView("tenants");
    }

    if (event.target.matches("#user-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      await saveUser({
        id: form.get("id") || null,
        full_name: form.get("full_name"),
        email: form.get("email"),
        phone: form.get("phone"),
        about: form.get("about"),
        password: form.get("password"),
        role: form.get("role"),
        profile_id: form.get("profile_id") || null,
        tenant_id: form.get("tenant_id") || state.user?.tenant_id || null,
        is_active: form.get("is_active") === "on",
      });
      closeModal();
      showToast("Usuario salvo com sucesso.");
      return setView("users");
    }

    if (event.target.matches("#user-profile-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      const permissions = {};
      PROFILE_RESOURCES.forEach(([resource]) => {
        permissions[resource] = {};
        PROFILE_ACTIONS.forEach(([action]) => {
          permissions[resource][action] = form.get(`permission_${resource}_${action}`) === "on";
        });
      });
      await saveUserProfile({
        id: form.get("id") || null,
        name: form.get("name"),
        tenant_id: form.get("tenant_id") || state.user?.tenant_id || null,
        permissions,
        is_active: form.get("is_active") === "on",
      });
      closeModal();
      showToast("Perfil salvo com sucesso.");
      return setView("user-profiles");
    }

    if (event.target.matches("#datasource-form")) {
      event.preventDefault();
      const payload = readDatasourceForm();
      if (state.modal.testedFingerprint !== computeDatasourceFingerprint(payload)) {
        state.modal.testResult = { ok: false, message: "Teste a conexao com os dados atuais antes de salvar." };
        return renderApp();
      }
      state.modal.saving = true;
      renderApp();
      try {
        await saveDatasource(payload);
        closeModal();
        showToast("Datasource salvo com sucesso.");
        return setView("datasources");
      } catch (error) {
        state.modal.saving = false;
        state.modal.testResult = { ok: false, message: error.message };
        return renderApp();
      }
    }

    if (event.target.matches("#ai-service-form")) {
      event.preventDefault();
      const payload = readAIServiceForm();
      await saveAIService(payload);
      closeModal();
      showToast("Servico de IA salvo com sucesso.");
      return setView("ai-services");
    }

    if (event.target.matches("#file-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      await saveFile({
        id: form.get("id") || null,
        name: form.get("name"),
        description: form.get("description"),
        tenant_id: form.get("tenant_id") || state.user?.tenant_id || null,
        is_active: form.get("is_active") === "on",
        upload: form.get("upload")?.size ? form.get("upload") : null,
      });
      closeModal();
      showToast("Arquivo salvo com sucesso.");
      return setView("files");
    }

    if (event.target.matches("#secret-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      await saveSecret({
        id: form.get("id") || null,
        name: form.get("name"),
        description: form.get("description"),
        tenant_id: form.get("tenant_id") || state.user?.tenant_id || null,
        secret_value: form.get("secret_value") || "",
        is_active: form.get("is_active") === "on",
      });
      closeModal();
      showToast("Secret salvo com sucesso.");
      return setView("secrets");
    }

    if (event.target.matches("#deploy-template-form")) {
      event.preventDefault();
      const form = new FormData(event.target);
      await deployTemplate(form.get("template_id"), form.get("version_id"));
      closeModal();
      showToast("Template deployado com sucesso.");
      if (state.view === "template-editor" && state.templateDraft?.template_id) {
        await openTemplateEditor(state.templateDraft.template_id);
        return renderApp();
      }
      return setView("templates");
    }
  } catch (error) {
    state.error = error.message;
    renderApp();
  }
});

bootstrap();
