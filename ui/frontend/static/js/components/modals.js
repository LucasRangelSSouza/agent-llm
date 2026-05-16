import { state } from "../core/state.js?v=20260410d";
import { escapeHtml, normalizeAIProvider, normalizeDatasourceType, renderSelectionOption, renderSwitch } from "../core/utils.js?v=20260410d";
import { PROFILE_ACTIONS, PROFILE_RESOURCES } from "../pages/user-profiles.js?v=20260410d";

function renderTemplateSelectionModal(modal) {
  const draft = state.templateDraft;
  if (!draft) return "";

  if (modal.type === "template-ai-service") {
    const selectedId = draft.ai_service_id || "";
    const availableServices = (state.aiServices || []).filter((item) => item.is_active !== false || item.id === selectedId);
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>Selecionar servico de IA</h2>
              <p class="subtitle">Escolha a conexao de IA principal usada por este template.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                availableServices
                  .map((item) =>
                    renderSelectionOption({
                      checked: selectedId === item.id,
                      label: item.name,
                      caption: `${normalizeAIProvider(item.provider)} • ${item.model_name || "-"}`,
                      dataAttrs: `data-template-ai-service="${item.id}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Nenhum servico de IA disponivel.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "template-datasources") {
    const selected = new Set(draft.datasource_ids || []);
    const availableDatasources = (state.datasources || []).filter((item) => item.is_active !== false || selected.has(item.id));
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>Selecionar datasources</h2>
              <p class="subtitle">Todos os agentes deste template poderao usar os datasources marcados.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                availableDatasources
                  .map((item) =>
                    renderSelectionOption({
                      checked: selected.has(item.id),
                      label: item.name,
                      caption: `${normalizeDatasourceType(item.kind)}${item.tenant_name ? ` • ${item.tenant_name}` : ""}`,
                      dataAttrs: `data-template-datasource="${item.id}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Nenhum datasource disponivel.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "template-agent-tools") {
    const agentIndex = modal.payload?.agentIndex ?? -1;
    const agent = draft.agents?.[agentIndex];
    const selected = new Set(agent?.tools || []);
    const tools = state.toolkitCatalog?.tools || [];
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>Selecionar toolkits</h2>
              <p class="subtitle">Ferramentas disponiveis para ${escapeHtml(agent?.name || "este agente")}.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                tools
                  .map((tool) =>
                    renderSelectionOption({
                      checked: selected.has(tool),
                      label: tool,
                      dataAttrs: `data-agent-index="${agentIndex}" data-agent-tool="${tool}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Nenhum toolkit disponivel.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "template-agent-interactions") {
    const agentIndex = modal.payload?.agentIndex ?? -1;
    const agent = draft.agents?.[agentIndex];
    const availableAgents = (draft.agents || []).filter((_, idx) => idx !== agentIndex);
    const selected = new Set(agent?.allowed_interactions || []);
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-md">
          <div class="modal-header">
            <div>
              <h2>Allowed interactions</h2>
              <p class="subtitle">Escolha com quais agentes ${escapeHtml(agent?.name || "este agente")} pode interagir.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                availableAgents
                  .map((otherAgent) =>
                    renderSelectionOption({
                      checked: selected.has(otherAgent.name),
                      label: otherAgent.name,
                      caption: otherAgent.agent_type || "",
                      dataAttrs: `data-agent-index="${agentIndex}" data-agent-interaction="${otherAgent.name}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Adicione outro agente para liberar interacoes.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "template-agent-files") {
    const agentIndex = modal.payload?.agentIndex ?? -1;
    const agent = draft.agents?.[agentIndex];
    const selected = new Set(agent?.file_ids || []);
    const availableFiles = (state.files || []).filter((item) => item.is_active !== false || selected.has(item.id));
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>Selecionar arquivos</h2>
              <p class="subtitle">Arquivos vinculados a ${escapeHtml(agent?.name || "este agente")}.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                availableFiles
                  .map((item) =>
                    renderSelectionOption({
                      checked: selected.has(item.id),
                      label: item.name,
                      caption: `${item.original_filename || "-"}${item.tenant_name ? ` | ${item.tenant_name}` : ""}`,
                      dataAttrs: `data-agent-index="${agentIndex}" data-agent-file="${item.id}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Nenhum arquivo disponivel.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "template-agent-secrets") {
    const agentIndex = modal.payload?.agentIndex ?? -1;
    const agent = draft.agents?.[agentIndex];
    const selected = new Set(agent?.secret_ids || []);
    const availableSecrets = (state.secrets || []).filter((item) => item.is_active !== false || selected.has(item.id));
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>Selecionar secrets</h2>
              <p class="subtitle">Secrets vinculados a ${escapeHtml(agent?.name || "este agente")}.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body selector-modal-body">
            <div class="selection-list">
              ${
                availableSecrets
                  .map((item) =>
                    renderSelectionOption({
                      checked: selected.has(item.id),
                      label: item.name,
                      caption: item.secret_value || "",
                      dataAttrs: `data-agent-index="${agentIndex}" data-agent-secret="${item.id}"`,
                    }),
                  )
                  .join("") || `<div class="empty-state compact">Nenhum secret disponivel.</div>`
              }
            </div>
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Concluir</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  return "";
}

export function renderModal() {
  const modal = state.modal;
  if (!modal) return "";

  if (
    modal.type === "template-ai-service" ||
    modal.type === "template-datasources" ||
    modal.type === "template-agent-tools" ||
    modal.type === "template-agent-interactions" ||
    modal.type === "template-agent-files" ||
    modal.type === "template-agent-secrets"
  ) {
    return renderTemplateSelectionModal(modal);
  }

  if (modal.type === "preferences") {
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-sm">
          <div class="modal-header">
            <div>
              <h2>Preferencias</h2>
              <p class="subtitle">Ajustes gerais da interface.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <div class="modal-body">
            ${renderSwitch({
              checked: state.preferences.theme === "dark",
              label: "Modo escuro",
              action: "toggle-theme",
            })}
            <div class="modal-actions">
              <button class="btn btn-primary" type="button" data-action="close-modal">Fechar</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (modal.type === "deploy-template") {
    const template = state.templates.find((item) => item.id === modal.payload?.template_id);
    const versions = state.templateDetail?.template?.id === template?.id ? state.templateDetail.versions || [] : [];
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-md">
          <div class="modal-header">
            <div>
              <h2>Deploy do template</h2>
              <p class="subtitle">Selecione a versao que ficara ativa para o tenant.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body" id="deploy-template-form">
            <div class="field">
              <label>Template</label>
              <select name="template_id">
                ${(state.templates || [])
                  .map(
                    (item) => `
                  <option value="${item.id}" ${item.id === modal.payload?.template_id ? "selected" : ""}>
                    ${escapeHtml(item.name)}${item.tenant_name ? ` • ${escapeHtml(item.tenant_name)}` : ""}
                  </option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field">
              <label>Versao</label>
              <select name="version_id">
                ${versions
                  .map(
                    (version) => `
                  <option value="${version.id}" ${version.id === modal.payload?.version_id ? "selected" : ""}>
                    v${version.version_number}${version.is_active ? " • ativa" : ""}
                  </option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Deployar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "tenant-form") {
    const item = modal.payload || {};
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-md">
          <div class="modal-header">
            <div>
              <h2>${item.id ? "Editar tenant" : "Novo tenant"}</h2>
              <p class="subtitle">Cadastro simples da empresa e seus dados institucionais.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form" id="tenant-form">
            <input type="hidden" name="id" value="${item.id || ""}" />
            <div class="field"><label>Nome da empresa</label><input name="name" value="${escapeHtml(item.name || "")}" required /></div>
            <div class="field"><label>CNPJ</label><input name="cnpj" value="${escapeHtml(item.cnpj || "")}" /></div>
            <div class="field full"><label>Razao social</label><input name="legal_name" value="${escapeHtml(item.legal_name || "")}" /></div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "user-form") {
    const item = modal.payload || {};
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>${item.id ? "Editar usuario" : "Novo usuario"}</h2>
              <p class="subtitle">Perfil, papel, tenant e credenciais de acesso.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form two-cols" id="user-form">
            <input type="hidden" name="id" value="${item.id || ""}" />
            <div class="field"><label>Nome completo</label><input name="full_name" value="${escapeHtml(item.full_name || "")}" required /></div>
            <div class="field"><label>E-mail</label><input type="email" name="email" value="${escapeHtml(item.email || "")}" required /></div>
            <div class="field"><label>Telefone</label><input name="phone" value="${escapeHtml(item.phone || "")}" /></div>
            <div class="field">
              <label>Papel</label>
              <select name="role">
                ${["user", "admin", "master"]
                  .map(
                    (role) => `
                  <option value="${role}" ${item.role === role ? "selected" : ""}>${role}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field full"><label>Sobre / cargo</label><textarea name="about">${escapeHtml(item.about || "")}</textarea></div>
            <div class="field full">
              <label>Perfil de usuario</label>
              <select name="profile_id">
                ${(state.userProfiles || [])
                  .filter((profile) => profile.is_active !== false || profile.id === item.profile_id)
                  .map((profile) => `<option value="${profile.id}" ${item.profile_id === profile.id ? "selected" : ""}>${escapeHtml(profile.name)}${profile.tenant_name ? ` - ${escapeHtml(profile.tenant_name)}` : ""}</option>`)
                  .join("")}
              </select>
            </div>
            <div class="field"><label>Senha ${item.id ? "(opcional)" : ""}</label><input type="password" name="password" autocomplete="current-password" ${item.id ? "" : "required"} /></div>
            <div class="field">
              <label>Tenant</label>
              <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                ${(state.tenants || [])
                  .map(
                    (tenant) => `
                  <option value="${tenant.id}" ${(item.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field full">
              ${renderSwitch({ checked: item.is_active !== false, label: "Usuario ativo", inputName: "is_active" })}
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "user-profile-form") {
    const item = modal.payload || {};
    const permissions = item.permissions || {};
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-xl">
          <div class="modal-header">
            <div>
              <h2>${item.id ? "Editar perfil" : "Novo perfil"}</h2>
              <p class="subtitle">Configure as permissoes por tela para os usuarios vinculados a este perfil.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form" id="user-profile-form">
            <input type="hidden" name="id" value="${item.id || ""}" />
            <div class="form-grid two-cols">
              <div class="field"><label>Nome do perfil</label><input name="name" value="${escapeHtml(item.name || "")}" required /></div>
              <div class="field ${state.user?.role === "master" ? "" : "readonly-field"}">
                <label>Tenant</label>
                <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                  ${(state.tenants || [])
                    .map((tenant) => `<option value="${tenant.id}" ${(item.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>`)
                    .join("")}
                </select>
              </div>
            </div>
            <div class="permission-matrix">
              <table>
                <thead>
                  <tr>
                    <th></th>
                    ${PROFILE_ACTIONS.map(([, label]) => `<th>${escapeHtml(label)}</th>`).join("")}
                  </tr>
                </thead>
                <tbody>
                  ${PROFILE_RESOURCES.map(([resource, label]) => `
                    <tr>
                      <td><strong>${escapeHtml(label)}</strong></td>
                      ${PROFILE_ACTIONS.map(([action]) => `
                        <td>
                          ${renderSwitch({
                            checked: Boolean(permissions?.[resource]?.[action]),
                            label: "",
                            inputName: `permission_${resource}_${action}`,
                          })}
                        </td>
                      `).join("")}
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
            <div class="field full">
              ${renderSwitch({ checked: item.is_active !== false, label: "Perfil ativo", inputName: "is_active" })}
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "datasource-form") {
    const payload = modal.payload || {};
    const isRelational = ["postgresql", "mysql", "mariadb", "sqlserver"].includes(payload.kind);
    return `
      <div class="modal-overlay" data-action="close-modal">
        <div class="modal glass modal-xl">
          <div class="modal-header">
            <div>
              <h2>${payload.id ? "Editar datasource" : "Novo datasource"}</h2>
              <p class="subtitle">Cadastre a conexao, teste com chamada real e so entao salve.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form two-cols" id="datasource-form">
            <input type="hidden" name="id" value="${payload.id || ""}" />
            <div class="field"><label>Nome da conexao</label><input name="name" value="${escapeHtml(payload.name || "")}" required /></div>
            <div class="field">
              <label>Tipo</label>
              <select name="kind" data-action="change-datasource-type">
                ${["postgresql", "mysql", "mariadb", "sqlserver", "sqlite", "athena", "bigquery"]
                  .map(
                    (kind) => `
                  <option value="${kind}" ${payload.kind === kind ? "selected" : ""}>${kind}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field ${state.user?.role === "master" ? "" : "readonly-field"}">
              <label>Tenant</label>
              <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                ${(state.tenants || [])
                  .map(
                    (tenant) => `
                  <option value="${tenant.id}" ${(payload.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field full">
              ${renderSwitch({ checked: payload.is_active !== false, label: "Conexao ativa", inputName: "is_active" })}
            </div>
            <div class="field full"><label>Descricao</label><textarea name="description">${escapeHtml(payload.description || "")}</textarea></div>

            ${
              isRelational
                ? `
              <div class="field"><label>Host</label><input name="host" value="${escapeHtml(payload.host || "")}" /></div>
              <div class="field"><label>Porta</label><input name="port" value="${escapeHtml(payload.port || "")}" /></div>
              <div class="field"><label>Database</label><input name="database_name" value="${escapeHtml(payload.database_name || "")}" /></div>
              <div class="field"><label>Schema</label><input name="schema_name" value="${escapeHtml(payload.schema_name || "")}" /></div>
              <div class="field"><label>Usuario</label><input name="username" value="${escapeHtml(payload.username || "")}" /></div>
              <div class="field"><label>Senha</label><input type="text" name="password" value="${escapeHtml(payload.password || "")}" placeholder="${payload.has_password ? "Senha ja cadastrada" : ""}" /></div>
              <div class="field full"><label>SSL</label><input name="ssl_mode" value="${escapeHtml(payload.ssl_mode || "")}" /></div>
            `
                : ""
            }

            ${
              payload.kind === "sqlite"
                ? `
              <div class="field"><label>Modo</label><select name="sqlite_mode"><option value="url" ${payload.sqlite_mode === "url" ? "selected" : ""}>URL</option><option value="path" ${payload.sqlite_mode === "path" ? "selected" : ""}>Path</option></select></div>
              <div class="field"><label>Path</label><input name="sqlite_path" value="${escapeHtml(payload.sqlite_path || "")}" /></div>
              <div class="field full"><label>URL</label><input name="sqlite_url" value="${escapeHtml(payload.sqlite_url || "")}" /></div>
            `
                : ""
            }

            ${
              payload.kind === "athena"
                ? `
              <div class="field"><label>Regiao</label><input name="region_name" value="${escapeHtml(payload.region_name || "")}" /></div>
              <div class="field"><label>Database</label><input name="database_name" value="${escapeHtml(payload.database_name || "")}" /></div>
              <div class="field"><label>Catalogo</label><input name="catalog_name" value="${escapeHtml(payload.catalog_name || "")}" /></div>
              <div class="field"><label>Workgroup</label><input name="workgroup" value="${escapeHtml(payload.workgroup || "")}" /></div>
              <div class="field"><label>AWS Access Key</label><input name="aws_access_key_id" value="${escapeHtml(payload.aws_access_key_id || "")}" /></div>
              <div class="field"><label>AWS Secret Key</label><input type="text" name="aws_secret_access_key" value="${escapeHtml(payload.aws_secret_access_key || "")}" placeholder="${payload.has_aws_secret_access_key ? "Secret ja cadastrada" : ""}" /></div>
              <div class="field"><label>AWS Session Token</label><input type="text" name="aws_session_token" value="${escapeHtml(payload.aws_session_token || "")}" placeholder="${payload.has_aws_session_token ? "Token ja cadastrado" : ""}" /></div>
              <div class="field full"><label>Bucket temporario / output S3</label><input name="output_location" value="${escapeHtml(payload.output_location || "")}" /></div>
            `
                : ""
            }

            ${
              payload.kind === "bigquery"
                ? `
              <div class="field"><label>Project ID</label><input name="project_id" value="${escapeHtml(payload.project_id || "")}" /></div>
              <div class="field"><label>Dataset</label><input name="dataset_name" value="${escapeHtml(payload.dataset_name || "")}" /></div>
              <div class="field"><label>Location</label><input name="location" value="${escapeHtml(payload.location || "")}" /></div>
              <div class="field"><label>Bucket temporario GCS</label><input name="gcs_temp_bucket" value="${escapeHtml(payload.gcs_temp_bucket || "")}" /></div>
              <div class="field full"><label>Service Account JSON</label><textarea name="service_account_json" placeholder="${payload.has_service_account_json ? "JSON ja cadastrado" : ""}">${escapeHtml(payload.service_account_json || "")}</textarea></div>
            `
                : ""
            }

            ${modal.testResult ? `<div class="${modal.testResult.ok ? "success-banner" : "error-banner"} full">${escapeHtml(modal.testResult.message)}</div>` : ""}
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-secondary" type="button" data-action="test-datasource">${modal.testing ? "Testando..." : "Testar conexao"}</button>
              <button class="btn btn-primary" type="submit">${modal.saving ? "Salvando..." : "Salvar"}</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "ai-service-form") {
    const payload = modal.payload || {};
    const providers = state.aiServiceCatalog?.providers || [];
    const provider = providers.find((item) => item.value === payload.provider) || providers[0] || null;
    const requiresApiKey = provider?.requires_api_key ?? provider?.requiresApiKey ?? true;
    const modelOptions = provider?.models || [];

    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>${payload.id ? "Editar servico de IA" : "Novo servico de IA"}</h2>
              <p class="subtitle">Cadastre por tenant a chave, o provider e o modelo principal que este servico usa.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form two-cols" id="ai-service-form">
            <input type="hidden" name="id" value="${payload.id || ""}" />
            <div class="field"><label>Nome do servico</label><input name="name" value="${escapeHtml(payload.name || "")}" required /></div>
            <div class="field">
              <label>Provider</label>
              <select name="provider" data-action="change-ai-provider">
                ${providers
                  .map(
                    (item) => `
                  <option value="${item.value}" ${payload.provider === item.value ? "selected" : ""}>${item.label}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field ${state.user?.role === "master" ? "" : "readonly-field"}">
              <label>Tenant</label>
              <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                ${(state.tenants || [])
                  .map(
                    (tenant) => `
                  <option value="${tenant.id}" ${(payload.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>
                `,
                  )
                  .join("")}
              </select>
            </div>
            <div class="field">
              <label>Modelo</label>
              <input name="model_name" value="${escapeHtml(payload.model_name || "")}" list="ai-model-options" required />
              <datalist id="ai-model-options">
                ${modelOptions.map((item) => `<option value="${escapeHtml(item)}"></option>`).join("")}
              </datalist>
            </div>
            <div class="field full"><label>Descricao</label><textarea name="description">${escapeHtml(payload.description || "")}</textarea></div>
            <div class="field full">
              <label>API Key ${requiresApiKey ? "" : "(opcional)"}</label>
              <input type="text" name="api_key" value="${escapeHtml(payload.api_key || "")}" placeholder="${payload.has_api_key ? "Chave ja cadastrada" : ""}" />
            </div>
            <div class="field"><label>Endpoint customizado</label><input name="endpoint_url" value="${escapeHtml(payload.endpoint_url || "")}" /></div>
            <div class="field"><label>Organization / workspace</label><input name="organization_id" value="${escapeHtml(payload.organization_id || "")}" /></div>
            <div class="field full">
              ${renderSwitch({ checked: payload.is_active !== false, label: "Servico ativo", inputName: "is_active" })}
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "file-form") {
    const payload = modal.payload || {};
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>${payload.id ? "Editar arquivo" : "Novo arquivo"}</h2>
              <p class="subtitle">O registro continua o mesmo mesmo quando voce troca o arquivo fisico.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form two-cols" id="file-form">
            <input type="hidden" name="id" value="${payload.id || ""}" />
            <div class="field"><label>Nome do arquivo</label><input name="name" value="${escapeHtml(payload.name || "")}" required /></div>
            <div class="field ${state.user?.role === "master" ? "" : "readonly-field"}">
              <label>Tenant</label>
              <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                ${(state.tenants || [])
                  .map((tenant) => `<option value="${tenant.id}" ${(payload.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>`)
                  .join("")}
              </select>
            </div>
            <div class="field full"><label>Descricao</label><textarea name="description">${escapeHtml(payload.description || "")}</textarea></div>
            <div class="field full"><label>Arquivo atual</label><input value="${escapeHtml(payload.original_filename || payload.file_url || "-")}" disabled /></div>
            <div class="field full"><label>${payload.id ? "Trocar arquivo" : "Upload do arquivo"}</label><input type="file" name="upload" ${payload.id ? "" : "required"} /></div>
            <div class="field full">
              ${renderSwitch({ checked: payload.is_active !== false, label: "Arquivo ativo", inputName: "is_active" })}
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  if (modal.type === "secret-form") {
    const payload = modal.payload || {};
    return `
      <div class="modal-overlay">
        <div class="modal glass modal-lg">
          <div class="modal-header">
            <div>
              <h2>${payload.id ? "Editar secret" : "Novo secret"}</h2>
              <p class="subtitle">Secrets ficam visiveis na tela para quem tiver permissao de acesso.</p>
            </div>
            <button class="icon-button subtle" type="button" data-action="close-modal">&times;</button>
          </div>
          <form class="modal-body modal-form two-cols" id="secret-form">
            <input type="hidden" name="id" value="${payload.id || ""}" />
            <div class="field"><label>Nome</label><input name="name" value="${escapeHtml(payload.name || "")}" required /></div>
            <div class="field ${state.user?.role === "master" ? "" : "readonly-field"}">
              <label>Tenant</label>
              <select name="tenant_id" ${state.user?.role !== "master" ? "disabled" : ""}>
                ${(state.tenants || [])
                  .map((tenant) => `<option value="${tenant.id}" ${(payload.tenant_id || state.user?.tenant_id) === tenant.id ? "selected" : ""}>${escapeHtml(tenant.name)}</option>`)
                  .join("")}
              </select>
            </div>
            <div class="field full"><label>Descricao</label><textarea name="description">${escapeHtml(payload.description || "")}</textarea></div>
            <div class="field full"><label>Valor do secret</label><textarea name="secret_value" required>${escapeHtml(payload.secret_value || "")}</textarea></div>
            <div class="field full">
              ${renderSwitch({ checked: payload.is_active !== false, label: "Secret ativo", inputName: "is_active" })}
            </div>
            <div class="modal-actions">
              <button class="btn btn-secondary" type="button" data-action="close-modal">Cancelar</button>
              <button class="btn btn-primary" type="submit">Salvar</button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  return "";
}
