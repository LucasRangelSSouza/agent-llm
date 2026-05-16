import { canManageTenants, state } from "../core/state.js?v=20260410d";
import { escapeHtml, normalizeDatasourceType } from "../core/utils.js?v=20260410d";

function renderTemplateVersionOptions() {
  const versions = state.templateDetail?.versions || [];
  if (!versions.length) return "";
  return `
    <div class="field inline-field">
      <label>Versao base</label>
      <select data-action="select-template-version">
        ${versions
          .map(
            (version) => `
          <option value="${version.id}" ${version.id === state.templateVersionId ? "selected" : ""}>
            v${version.version_number}${version.is_active ? " • ativa" : ""}
          </option>
        `,
          )
          .join("")}
      </select>
    </div>
  `;
}

function renderSelectedBadges(items) {
  if (!items.length) {
    return `<div class="empty-state compact">Nada selecionado ainda.</div>`;
  }

  return `
    <div class="selection-badges">
      ${items
        .map(
          (item) => `
        <span class="selection-badge">${escapeHtml(item)}</span>
      `,
        )
        .join("")}
    </div>
  `;
}

function renderAgentCard(agent, index, allAgents) {
  const availableInteractions = allAgents.filter((_, itemIndex) => itemIndex !== index).map((item) => item.name);
  const selectedInteractions = (agent.allowed_interactions || []).filter((item) => availableInteractions.includes(item));
  const selectedFiles = (state.files || []).filter((item) => (agent.file_ids || []).includes(item.id)).map((item) => item.name);
  const selectedSecrets = (state.secrets || []).filter((item) => (agent.secret_ids || []).includes(item.id)).map((item) => item.name);

  return `
    <details class="agent-card glass" ${agent.isCollapsed ? "" : "open"} data-agent-card-index="${index}">
      <summary class="agent-card-summary">
        <div>
          <strong>${escapeHtml(agent.name || `Agente ${index + 1}`)}</strong>
          <span class="meta-inline">${escapeHtml(agent.agent_type || "AssistantAgent")}</span>
        </div>
        <div class="button-row">
          <button class="btn btn-secondary btn-small" type="button" data-action="remove-template-agent" data-index="${index}">Remover</button>
        </div>
      </summary>
      <div class="agent-card-body">
        <div class="form-grid two-cols">
          <div class="field">
            <label>Nome do agente</label>
            <input value="${escapeHtml(agent.name || "")}" data-agent-index="${index}" data-agent-field="name" />
          </div>
          <div class="field">
            <label>Tipo</label>
            <select data-agent-index="${index}" data-agent-field="agent_type">
              ${(state.toolkitCatalog?.agent_types || [])
                .map(
                  (type) => `
                <option value="${type}" ${agent.agent_type === type ? "selected" : ""}>${type}</option>
              `,
                )
                .join("")}
            </select>
          </div>
          <div class="field full">
            <label>Prompt do agente</label>
            <textarea data-agent-index="${index}" data-agent-field="prompt">${escapeHtml(agent.prompt || "")}</textarea>
          </div>
        </div>

        <div class="selector-section">
          <div class="selector-section-header">
            <h3>Toolkits disponiveis</h3>
            <span class="nav-note">Selecione em um modal para evitar poluicao visual.</span>
          </div>
          ${renderSelectedBadges(agent.tools || [])}
          <div class="button-row">
            <button class="btn btn-secondary btn-small" type="button" data-action="open-template-agent-tools" data-agent-index="${index}">
              Selecionar toolkits
            </button>
          </div>
        </div>

        <div class="selector-section">
          <div class="selector-section-header">
            <h3>Allowed interactions</h3>
            <span class="nav-note">Defina quais outros agentes este agente pode acionar.</span>
          </div>
          ${renderSelectedBadges(selectedInteractions)}
          <div class="button-row">
            <button class="btn btn-secondary btn-small" type="button" data-action="open-template-agent-interactions" data-agent-index="${index}">
              Selecionar interacoes
            </button>
          </div>
        </div>

        <div class="selector-section">
          <div class="selector-section-header">
            <h3>Arquivos vinculados</h3>
            <span class="nav-note">Use o mesmo padrao de selecao dos demais relacionamentos.</span>
          </div>
          ${renderSelectedBadges(selectedFiles)}
          <div class="button-row">
            <button class="btn btn-secondary btn-small" type="button" data-action="open-template-agent-files" data-agent-index="${index}">
              Selecionar arquivos
            </button>
          </div>
        </div>

        <div class="selector-section">
          <div class="selector-section-header">
            <h3>Secrets vinculados</h3>
            <span class="nav-note">Secrets ficam no escopo do agente, nao no template geral.</span>
          </div>
          ${renderSelectedBadges(selectedSecrets)}
          <div class="button-row">
            <button class="btn btn-secondary btn-small" type="button" data-action="open-template-agent-secrets" data-agent-index="${index}">
              Selecionar secrets
            </button>
          </div>
        </div>
      </div>
    </details>
  `;
}

export function renderTemplateEditorPage() {
  const draft = state.templateDraft;
  if (!draft) {
    return `
      <section class="page-section">
        <div class="empty-state glass">Carregando editor do template...</div>
      </section>
    `;
  }

  const selectedDatasourceIds = new Set(draft.datasource_ids || []);
  const selectedAIService = (state.aiServices || []).find((item) => item.id === draft.ai_service_id);
  const availableDatasources = (state.datasources || []).filter((item) => item.is_active !== false || selectedDatasourceIds.has(item.id));
  const selectedDatasourceLabels = availableDatasources
    .filter((item) => selectedDatasourceIds.has(item.id))
    .map((item) => `${item.name} (${normalizeDatasourceType(item.kind)})`);

  const tenantSelect = canManageTenants()
    ? `
      <select data-template-field="tenant_id">
        ${(state.tenants || [])
          .map(
            (tenant) => `
          <option value="${tenant.id}" ${draft.tenant_id === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>
        `,
          )
          .join("")}
      </select>
    `
    : `<input value="${escapeHtml(draft.tenant_id || state.user?.tenant_id || "Tenant atual")}" disabled />`;

  return `
    <section class="page-section template-editor-page">
      <header class="page-header compact-header">
        <div>
          <div class="page-breadcrumbs">
            <button class="btn btn-ghost btn-small" data-action="back-to-templates">← Templates</button>
          </div>
          <h1>${draft.template_id ? "Editar template" : "Novo template"}</h1>
          <p class="subtitle">Salvar sempre gera uma nova versao. O deploy continua separado e controlado por tenant.</p>
        </div>
        <div class="button-row">
          ${renderTemplateVersionOptions()}
          ${draft.template_id ? `<button class="btn btn-secondary" data-action="export-current-template">Exportar</button>` : ""}
          ${draft.template_id ? `<button class="btn btn-secondary" data-action="open-current-template-deploy">Deploy</button>` : ""}
          <button class="btn btn-primary" data-action="save-template-version">Salvar nova versao</button>
        </div>
      </header>

      <div class="editor-grid">
        <section class="editor-panel glass">
          <div class="section-title">
            <h2>Dados gerais</h2>
          </div>
          <div class="form-grid two-cols">
            <div class="field">
              <label>Nome do template</label>
              <input value="${escapeHtml(draft.name || "")}" data-template-field="name" />
            </div>
            <div class="field">
              <label>Nome do modulo</label>
              <input value="${escapeHtml(draft.module_name || "")}" data-template-field="module_name" />
            </div>
            <div class="field ${canManageTenants() ? "" : "readonly-field"}">
              <label>Tenant</label>
              ${tenantSelect}
            </div>
            <div class="field">
              <label>Descricao curta</label>
              <input value="${escapeHtml(draft.description || "")}" data-template-field="description" />
            </div>
            <div class="field full">
              <label>Prompt geral / descricao mestre</label>
              <textarea data-template-field="general_prompt">${escapeHtml(draft.general_prompt || "")}</textarea>
            </div>
          </div>
        </section>

        <section class="editor-panel glass">
          <div class="section-title">
            <div>
              <h2>Servico de IA</h2>
              <span class="nav-note">Cada template usa exatamente uma conexao de IA.</span>
            </div>
            <button class="btn btn-secondary btn-small" data-action="open-template-ai-service">
              Selecionar servico
            </button>
          </div>
          ${renderSelectedBadges(
            selectedAIService ? [`${selectedAIService.name} (${selectedAIService.model_name || selectedAIService.provider_label || selectedAIService.provider})`] : [],
          )}
        </section>

        <section class="editor-panel glass">
          <div class="section-title">
            <div>
              <h2>Datasources do template</h2>
              <span class="nav-note">Qualquer agente deste template podera usar os datasources marcados.</span>
            </div>
            <button class="btn btn-secondary btn-small" data-action="open-template-datasources">
              Selecionar datasources
            </button>
          </div>
          ${renderSelectedBadges(selectedDatasourceLabels)}
        </section>
      </div>

      <section class="editor-panel glass agents-panel">
        <div class="section-title">
          <div>
            <h2>Agentes do template</h2>
            <span class="nav-note">Os nomes devem terminar com <code>_agent</code>.</span>
          </div>
          <div class="button-row">
            <button class="btn btn-secondary btn-small" data-action="expand-all-template-agents">Expandir todos</button>
            <button class="btn btn-secondary btn-small" data-action="collapse-all-template-agents">Colapsar todos</button>
            <button class="btn btn-primary" data-action="add-template-agent">Adicionar agente</button>
          </div>
        </div>
        <div class="agent-list">
          ${(draft.agents || []).map((agent, index) => renderAgentCard(agent, index, draft.agents || [])).join("")}
        </div>
      </section>
    </section>
  `;
}
