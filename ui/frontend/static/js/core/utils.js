import { AI_SERVICE_PROVIDERS, DATASOURCE_TYPES, state } from "./state.js?v=20260410d";

export function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderInlineMarkdown(text) {
  return text
    .replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, '<img class="markdown-inline-image" src="$2" alt="$1" loading="lazy" />')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function isTableRow(value) {
  const trimmed = value.trim();
  return trimmed.includes("|") && /^\|?.+\|.+\|?$/.test(trimmed);
}

function isTableSeparator(value) {
  const trimmed = value.trim();
  if (!trimmed) return false;
  const normalized = trimmed.replace(/\|/g, "").replace(/:/g, "").replace(/-/g, "").trim();
  return normalized === "" && trimmed.includes("-");
}

function splitTableCells(row) {
  const trimmed = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function renderTableBlock(lines) {
  const headerCells = splitTableCells(lines[0]);
  const bodyRows = lines.slice(2).map(splitTableCells);
  return `
    <div class="markdown-table-wrap">
      <table>
        <thead>
          <tr>${headerCells.map((cell) => `<th>${renderInlineMarkdown(escapeHtml(cell))}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${bodyRows.map((cells) => `<tr>${cells.map((cell) => `<td>${renderInlineMarkdown(escapeHtml(cell))}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

export function renderMarkdown(content) {
  const source = String(content || "").replace(/\r\n/g, "\n");
  const lines = source.split("\n");
  const html = [];
  let index = 0;
  let paragraph = [];
  let listType = null;
  let listItems = [];
  let inCodeBlock = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderInlineMarkdown(escapeHtml(paragraph.join("\n"))).replace(/\n/g, "<br />")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    const tag = listType === "ol" ? "ol" : "ul";
    html.push(`<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdown(escapeHtml(item))}</li>`).join("")}</${tag}>`);
    listItems = [];
    listType = null;
  };

  const flushCode = () => {
    if (!codeLines.length) return;
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  while (index < lines.length) {
    const rawLine = lines[index];
    const line = rawLine || "";
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flushParagraph();
      flushList();
      if (inCodeBlock) {
        flushCode();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      index += 1;
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      index += 1;
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      index += 1;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(escapeHtml(headingMatch[2]))}</h${level}>`);
      index += 1;
      continue;
    }

    if (isTableRow(trimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      flushParagraph();
      flushList();
      const tableLines = [line, lines[index + 1]];
      index += 2;
      while (index < lines.length && isTableRow(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      html.push(renderTableBlock(tableLines));
      continue;
    }

    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(orderedMatch[2]);
      index += 1;
      continue;
    }

    const listMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (listMatch) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(listMatch[1]);
      index += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushParagraph();
      flushList();
      const quoteLines = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      html.push(`<blockquote>${renderInlineMarkdown(escapeHtml(quoteLines.join("\n"))).replace(/\n/g, "<br />")}</blockquote>`);
      continue;
    }

    paragraph.push(line);
    index += 1;
  }

  flushParagraph();
  flushList();
  flushCode();

  return html.join("") || `<p>${renderInlineMarkdown(escapeHtml(source))}</p>`;
}

export function renderMessageContent(message) {
  const content = String(message?.content || "");
  if (message?.role === "assistant") {
    return renderAssistantContent(content);
  }
  return escapeHtml(content).replace(/\n/g, "<br />");
}

function renderAssistantContent(content) {
  const richPayload = tryParseRichPayload(content);
  if (!richPayload) {
    return `<div class="markdown-body">${renderMarkdown(content)}</div>`;
  }

  const blocks = [];
  const markdownText = [richPayload.markdown, richPayload.answer, richPayload.body_text, richPayload.text]
    .find((value) => typeof value === "string" && value.trim());
  if (markdownText) {
    blocks.push(`<div class="markdown-body">${renderMarkdown(markdownText)}</div>`);
  }

  const plotlyPayload = richPayload.plotly_json || richPayload.plotly || null;
  if (plotlyPayload) {
    blocks.push(renderPlotlyBlock(plotlyPayload, richPayload.label || "Gráfico"));
  }

  const imageUrls = collectImageUrls(richPayload);
  if (imageUrls.length) {
    blocks.push(`
      <div class="chat-media-grid">
        ${imageUrls.map((url) => `<img class="chat-inline-image" src="${escapeHtml(url)}" alt="Imagem da resposta" loading="lazy" />`).join("")}
      </div>
    `);
  }

  const files = collectFileLinks(richPayload);
  if (files.length) {
    blocks.push(`
      <div class="chat-file-list">
        ${files.map((file) => `
          <a class="chat-file-card" href="${escapeHtml(file.url)}" target="_blank" rel="noreferrer">
            <span class="chat-file-name">${escapeHtml(file.label)}</span>
            <span class="chat-file-meta">Abrir arquivo</span>
          </a>
        `).join("")}
      </div>
    `);
  }

  if (!blocks.length) {
    return `<div class="markdown-body">${renderMarkdown(content)}</div>`;
  }
  return blocks.join("");
}

function tryParseRichPayload(content) {
  const text = String(content || "").trim();
  if (!text || (!text.startsWith("{") && !text.startsWith("["))) return null;
  try {
    const parsed = JSON.parse(text);
    if (!parsed || Array.isArray(parsed)) return null;
    if (
      parsed.plotly_json ||
      parsed.plotly ||
      parsed.image_public_url ||
      parsed.image_url ||
      parsed.public_url ||
      parsed.files ||
      parsed.markdown ||
      parsed.answer ||
      parsed.body_text
    ) {
      return parsed;
    }
  } catch {}
  return null;
}

function renderPlotlyBlock(payload, label) {
  const encoded = encodeURIComponent(JSON.stringify(payload));
  return `
    <div class="plotly-card">
      <div class="plotly-card-title">${escapeHtml(label || "Gráfico")}</div>
      <div class="plotly-embed" data-plotly="${encoded}"></div>
    </div>
  `;
}

function collectImageUrls(payload) {
  const candidates = [
    payload.image_public_url,
    payload.image_url,
    payload.graph_http_url,
    payload.graph_url,
    payload.public_url,
  ].filter(Boolean);
  return candidates.filter((url) => /\.(png|jpg|jpeg|gif|webp|svg)(\?|$)/i.test(String(url)));
}

function collectFileLinks(payload) {
  const links = [];
  if (payload.public_url && !/\.(png|jpg|jpeg|gif|webp|svg)(\?|$)/i.test(String(payload.public_url))) {
    links.push({ url: payload.public_url, label: payload.file_name || payload.label || "Arquivo" });
  }
  if (Array.isArray(payload.files)) {
    payload.files.forEach((file) => {
      if (file?.url) {
        links.push({ url: file.url, label: file.label || file.name || file.original_filename || "Arquivo" });
      }
    });
  }
  return links;
}

export function normalizeDatasourceType(type) {
  return DATASOURCE_TYPES.find((item) => item.value === type)?.label || type;
}

export function normalizeAIProvider(type) {
  return AI_SERVICE_PROVIDERS.find((item) => item.value === type)?.label || type;
}

export function formatDateTime(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

export function renderSwitch({ checked, label, action = "", actionValue = "", inputName = "" }) {
  return `
    <label class="switch-row">
      <span>${label}</span>
      <span class="switch ${checked ? "active" : ""}" ${action ? `data-action="${action}"` : ""} ${actionValue ? `data-action-value="${actionValue}"` : ""}>
        <input
          type="checkbox"
          ${checked ? "checked" : ""}
          ${inputName ? `name="${inputName}"` : ""}
        />
        <span class="switch-track"></span>
        <span class="switch-thumb"></span>
      </span>
    </label>
  `;
}

export function renderCheckboxCard({ checked, label, value, dataAttrs = "" }) {
  return `
    <label class="check-card ${checked ? "active" : ""}">
      <input type="checkbox" value="${escapeHtml(value)}" ${checked ? "checked" : ""} ${dataAttrs} />
      <span class="check-indicator"></span>
      <span class="check-label">${escapeHtml(label)}</span>
    </label>
  `;
}

export function renderSelectionOption({ checked, label, caption = "", dataAttrs = "" }) {
  return `
    <label class="selection-option">
      <div class="selection-option-copy">
        <div class="selection-option-title">${escapeHtml(label)}</div>
        ${caption ? `<div class="selection-option-caption">${escapeHtml(caption)}</div>` : ""}
      </div>
      <span class="switch ${checked ? "active" : ""}">
        <input type="checkbox" ${checked ? "checked" : ""} ${dataAttrs} />
        <span class="switch-track"></span>
        <span class="switch-thumb"></span>
      </span>
    </label>
  `;
}

export function getThemeLabel() {
  return state.preferences.theme === "dark" ? "escuro" : "claro";
}
