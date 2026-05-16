import { state, persistToken, defaultAIServicePayload, defaultDatasourcePayload, defaultTemplateDraft, defaultTemplateAgent } from "./state.js?v=20260410d";

export async function apiFetch(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = {
    ...(options.headers || {}),
  };
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    if (response.status === 401) {
      persistToken("");
      state.user = null;
    }
    const detail = payload?.detail || payload?.message || "Erro inesperado";
    throw new Error(detail);
  }
  return payload;
}

export async function bootstrapSession() {
  if (!state.token) return false;
  try {
    const payload = await apiFetch("/api/auth/me", { method: "GET" });
    state.user = payload.user;
    return true;
  } catch {
    persistToken("");
    state.user = null;
    return false;
  }
}

export async function login(email, password) {
  const payload = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  persistToken(payload.token);
  state.user = payload.user;
  return payload;
}

export function logout() {
  if (state.token) {
    fetch("/api/auth/logout", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${state.token}`,
      },
    }).catch(() => {});
  }
  persistToken("");
  state.user = null;
  state.view = "chat";
  state.chats = [];
  state.activeChatId = null;
  state.messages = [];
}

export async function loadChats() {
  const payload = await apiFetch("/api/chats", { method: "GET" });
  state.chats = payload.items || [];
  return state.chats;
}

export async function hideChat(chatId) {
  await apiFetch(`/api/chats/${chatId}/hide`, { method: "PUT" });
  return loadChats();
}

export async function hideAllChats() {
  await apiFetch("/api/chats/hide-all", { method: "PUT" });
  return loadChats();
}

export async function loadMessages(chatId) {
  const payload = await apiFetch(`/api/chats/${chatId}/messages`, { method: "GET" });
  state.activeChatId = chatId;
  state.messages = payload.items || [];
  return state.messages;
}

export async function createChat() {
  const payload = await apiFetch("/api/chats", { method: "POST" });
  state.activeChatId = payload.item.id;
  state.messages = [];
  return payload.item;
}

export async function sendChatMessage(question, files = []) {
  if (!state.activeChatId) {
    await createChat();
  }
  let body;
  if (files?.length) {
    body = new FormData();
    body.append("chat_id", state.activeChatId);
    body.append("question", question);
    files.forEach((file) => body.append("files", file));
  } else {
    body = JSON.stringify({
      chat_id: state.activeChatId,
      question,
    });
  }
  const payload = await apiFetch("/api/chat/send", {
    method: "POST",
    body,
  });
  state.activeChatId = payload.chat_id;
  return payload;
}

export async function loadUserProfiles() {
  const payload = await apiFetch(`/api/user-profiles?include_inactive=${state.filters.userProfilesIncludeInactive}`, { method: "GET" });
  state.userProfiles = payload.items || [];
  return state.userProfiles;
}

export async function saveUserProfile(item) {
  if (item.id) {
    return apiFetch(`/api/user-profiles/${item.id}`, { method: "PUT", body: JSON.stringify(item) });
  }
  return apiFetch("/api/user-profiles", { method: "POST", body: JSON.stringify(item) });
}

export async function loadTenants() {
  const payload = await apiFetch(`/api/tenants?include_inactive=${state.filters.tenantsIncludeInactive}`, { method: "GET" });
  state.tenants = payload.items || [];
  return state.tenants;
}

export async function saveTenant(item) {
  if (item.id) {
    return apiFetch(`/api/tenants/${item.id}`, { method: "PUT", body: JSON.stringify(item) });
  }
  return apiFetch("/api/tenants", { method: "POST", body: JSON.stringify(item) });
}

export async function loadUsers() {
  const payload = await apiFetch(`/api/users?include_inactive=${state.filters.usersIncludeInactive}`, { method: "GET" });
  state.users = payload.items || [];
  return state.users;
}

export async function saveUser(item) {
  if (item.id) {
    const payload = { ...item };
    if (!payload.password) delete payload.password;
    return apiFetch(`/api/users/${item.id}`, { method: "PUT", body: JSON.stringify(payload) });
  }
  return apiFetch("/api/users", { method: "POST", body: JSON.stringify(item) });
}

export async function loadDatasources() {
  const payload = await apiFetch(`/api/datasources?include_inactive=${state.filters.datasourcesIncludeInactive}`, { method: "GET" });
  state.datasources = payload.items || [];
  return state.datasources;
}

export async function loadFiles() {
  const payload = await apiFetch(`/api/files?include_inactive=${state.filters.filesIncludeInactive}`, { method: "GET" });
  state.files = payload.items || [];
  return state.files;
}

export async function loadFile(id) {
  const payload = await apiFetch(`/api/files/${id}`, { method: "GET" });
  return payload.item.form;
}

export async function saveFile(item) {
  const body = new FormData();
  if (item.id) body.append("id", item.id);
  if (item.tenant_id) body.append("tenant_id", item.tenant_id);
  body.append("name", item.name || "");
  body.append("description", item.description || "");
  body.append("is_active", item.is_active ? "true" : "false");
  if (item.upload) body.append("upload", item.upload);

  if (item.id) {
    return apiFetch(`/api/files/${item.id}`, { method: "PUT", body });
  }
  return apiFetch("/api/files", { method: "POST", body });
}

export async function loadSecrets() {
  const payload = await apiFetch(`/api/secrets?include_inactive=${state.filters.secretsIncludeInactive}`, { method: "GET" });
  state.secrets = payload.items || [];
  return state.secrets;
}

export async function loadSecret(id) {
  const payload = await apiFetch(`/api/secrets/${id}`, { method: "GET" });
  return payload.item.form;
}

export async function saveSecret(item) {
  if (item.id) {
    return apiFetch(`/api/secrets/${item.id}`, { method: "PUT", body: JSON.stringify(item) });
  }
  return apiFetch("/api/secrets", { method: "POST", body: JSON.stringify(item) });
}

export async function loadAIServiceCatalog() {
  const payload = await apiFetch("/api/ai-services/catalog", { method: "GET" });
  state.aiServiceCatalog = payload || { providers: [] };
  return state.aiServiceCatalog;
}

export async function loadAIServices(includeInactive = state.filters.aiServicesIncludeInactive) {
  const payload = await apiFetch(`/api/ai-services?include_inactive=${includeInactive}`, { method: "GET" });
  state.aiServices = payload.items || [];
  return state.aiServices;
}

export async function loadAIService(id) {
  const payload = await apiFetch(`/api/ai-services/${id}`, { method: "GET" });
  return { id: payload.item.id, ...defaultAIServicePayload(), ...payload.item.form };
}

export async function saveAIService(item) {
  if (item.id || item.ai_service_id) {
    const id = item.id || item.ai_service_id;
    return apiFetch(`/api/ai-services/${id}`, { method: "PUT", body: JSON.stringify(item) });
  }
  return apiFetch("/api/ai-services", { method: "POST", body: JSON.stringify(item) });
}

export async function loadDatasource(id) {
  const payload = await apiFetch(`/api/datasources/${id}`, { method: "GET" });
  return { id: payload.item.id, ...defaultDatasourcePayload(), ...payload.item.form };
}

export async function testDatasource(item) {
  return apiFetch("/api/datasources/test", {
    method: "POST",
    body: JSON.stringify(item),
  });
}

export async function saveDatasource(item) {
  if (item.id || item.datasource_id) {
    const id = item.id || item.datasource_id;
    return apiFetch(`/api/datasources/${id}`, { method: "PUT", body: JSON.stringify(item) });
  }
  return apiFetch("/api/datasources", { method: "POST", body: JSON.stringify(item) });
}

export async function toggleEntityStatus(entity, id, nextActive) {
  return apiFetch(`/api/${entity}/${id}/status`, {
    method: "PUT",
    body: JSON.stringify({ is_active: nextActive }),
  });
}

export async function loadToolkits() {
  const payload = await apiFetch("/api/toolkits", { method: "GET" });
  state.toolkitCatalog = payload || { agent_types: [], toolkits: [], tools: [] };
  return state.toolkitCatalog;
}

export async function loadTemplates() {
  const payload = await apiFetch(`/api/templates?include_inactive=${state.filters.templatesIncludeInactive}`, { method: "GET" });
  state.templates = payload.items || [];
  return state.templates;
}

export async function loadTemplateDetail(templateId) {
  const payload = await apiFetch(`/api/templates/${templateId}`, { method: "GET" });
  state.templateDetail = payload;
  return payload;
}

export async function loadTemplateVersion(versionId) {
  const payload = await apiFetch(`/api/template-versions/${versionId}`, { method: "GET" });
  const item = payload.item;
  state.templateVersionId = item.id;
  state.templateDraft = {
    id: item.id,
    template_id: item.template_id,
    tenant_id: item.tenant_id,
    version_number: item.version_number,
    based_on_version_id: item.id,
    name: item.template.name,
    module_name: item.template.module_name,
    description: item.template.description || "",
    general_prompt: item.general_prompt || "",
    ai_service_id: item.ai_service_id || null,
    datasource_ids: [...(item.datasource_ids || [])],
    agents: (item.agents || []).map((agent, index) => ({
      ...agent,
      sort_order: index,
      isCollapsed: false,
      tools: [...(agent.tools || [])],
      allowed_interactions: [...(agent.allowed_interactions || [])],
      file_ids: [...(agent.file_ids || [])],
      secret_ids: [...(agent.secret_ids || [])],
    })),
  };
  return state.templateDraft;
}

export async function openTemplateCreate() {
  await loadToolkits();
  await loadDatasources();
  await loadFiles();
  await loadSecrets();
  await loadAIServiceCatalog();
  await loadAIServices();
  if (state.user?.role === "master") await loadTenants();
  state.templateDetail = null;
  state.templateVersionId = null;
  state.templateDraft = defaultTemplateDraft();
  state.view = "template-editor";
}

export async function openTemplateEditor(templateId, versionId = null) {
  await loadToolkits();
  await loadDatasources();
  await loadFiles();
  await loadSecrets();
  await loadAIServiceCatalog();
  await loadAIServices(true);
  if (state.user?.role === "master") await loadTenants();
  const detail = await loadTemplateDetail(templateId);
  const nextVersionId = versionId || detail.versions?.[0]?.id || null;
  if (nextVersionId) {
    await loadTemplateVersion(nextVersionId);
  } else {
    state.templateDraft = {
      ...defaultTemplateDraft(),
      template_id: templateId,
      tenant_id: detail.template?.tenant_id || state.user?.tenant_id || "",
      name: detail.template?.name || "",
      module_name: detail.template?.module_name || "",
      description: detail.template?.description || "",
      ai_service_id: null,
    };
  }
  state.view = "template-editor";
}

export async function saveTemplateVersion() {
  const draft = state.templateDraft;
  const payload = {
    tenant_id: draft.tenant_id || null,
    name: (draft.name || "").trim(),
    module_name: (draft.module_name || "").trim(),
    description: draft.description || "",
    general_prompt: draft.general_prompt || "",
    ai_service_id: draft.ai_service_id || null,
    datasource_ids: [...(draft.datasource_ids || [])],
    based_on_version_id: draft.based_on_version_id || draft.id || null,
    agents: (draft.agents || []).map((agent, index) => ({
      name: (agent.name || "").trim(),
      agent_type: agent.agent_type,
      prompt: agent.prompt || "",
      tools: [...(agent.tools || [])],
      allowed_interactions: [...(agent.allowed_interactions || [])],
      file_ids: [...(agent.file_ids || [])],
      secret_ids: [...(agent.secret_ids || [])],
      sort_order: index,
    })),
  };

  const path = draft.template_id ? `/api/templates/${draft.template_id}/versions` : "/api/templates";
  const response = await apiFetch(path, { method: "POST", body: JSON.stringify(payload) });
  await loadTemplates();
  await openTemplateEditor(response.item.template_id, response.item.id);
  return response.item;
}

export async function deployTemplate(templateId, versionId) {
  const response = await apiFetch("/api/templates/deploy", {
    method: "POST",
    body: JSON.stringify({ template_id: templateId, version_id: versionId }),
  });
  await loadTemplates();
  if (response?.item?.template_id) {
    await loadTemplateDetail(response.item.template_id);
  }
  return response.item;
}

export async function setTemplateStatus(templateId, nextActive) {
  return apiFetch(`/api/templates/${templateId}/status`, {
    method: "PUT",
    body: JSON.stringify({ is_active: nextActive }),
  });
}

export async function deleteTemplate(templateId) {
  return apiFetch(`/api/templates/${templateId}`, { method: "DELETE" });
}

export async function exportTemplate(templateId, versionId = null) {
  const url = versionId
    ? `/api/templates/${templateId}/export?version_id=${encodeURIComponent(versionId)}`
    : `/api/templates/${templateId}/export`;

  const headers = {};
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(url, { method: "GET", headers });
  if (!response.ok) {
    let detail = "Erro ao exportar template";
    try {
      const payload = await response.json();
      detail = payload?.detail || detail;
    } catch {}
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
  const filename = filenameMatch?.[1] || `${templateId}.json`;
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(downloadUrl);
}

export function resetTemplateDraft() {
  state.templateDraft = defaultTemplateDraft();
}

export function addDraftAgent() {
  const agents = [...(state.templateDraft?.agents || []), defaultTemplateAgent((state.templateDraft?.agents || []).length)];
  state.templateDraft = {
    ...(state.templateDraft || defaultTemplateDraft()),
    agents: agents.map((agent, index) => ({ ...agent, sort_order: index })),
  };
}
