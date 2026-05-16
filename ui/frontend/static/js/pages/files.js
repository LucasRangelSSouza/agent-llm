import { state } from "../core/state.js?v=20260410d";
import { formatDateTime, renderSwitch } from "../core/utils.js?v=20260410d";

function formatBytes(value) {
  const size = Number(value || 0);
  if (!size) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function renderFilesPage() {
  return `
    <section class="page-section">
      <header class="page-header compact-header">
        <div>
          <h1>Arquivos</h1>
          <p class="subtitle">Arquivos por tenant com upload no MinIO e referencia reutilizavel nos agentes.</p>
        </div>
      </header>
      <div class="toolbar">
        <div class="button-row">
          <span class="badge">${state.files.length} arquivo(s)</span>
          ${renderSwitch({ checked: state.filters.filesIncludeInactive, label: "Ver inativos", action: "toggle-filter", actionValue: "filesIncludeInactive" })}
        </div>
        <button class="btn btn-primary" data-action="open-file-form">Inserir arquivo</button>
      </div>
      <div class="data-grid glass">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Arquivo atual</th>
              <th>Tenant</th>
              <th>Tamanho</th>
              <th>Atualizado</th>
              <th>Status</th>
              <th>Acoes</th>
            </tr>
          </thead>
          <tbody>
            ${(state.files || []).map((item) => `
              <tr class="${item.is_active === false ? "row-inactive" : ""}">
                <td>${item.name}</td>
                <td>${item.original_filename || "-"}</td>
                <td>${item.tenant_name || item.tenant_id || "-"}</td>
                <td>${formatBytes(item.size_bytes)}</td>
                <td>${item.updated_at ? formatDateTime(item.updated_at) : "-"}</td>
                <td><span class="status-pill ${item.is_active === false ? "status-warn" : "status-ok"}">${item.is_active === false ? "inativo" : "ativo"}</span></td>
                <td>
                  <div class="table-actions">
                    <button class="btn btn-secondary" data-action="edit-file" data-id="${item.id}">Editar</button>
                    <button class="btn btn-secondary" data-action="toggle-status" data-entity="files" data-id="${item.id}" data-next-active="${item.is_active === false ? "true" : "false"}">${item.is_active === false ? "Reativar" : "Inativar"}</button>
                  </div>
                </td>
              </tr>
            `).join("") || `<tr><td colspan="7" class="empty-state">Nenhum arquivo cadastrado.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
