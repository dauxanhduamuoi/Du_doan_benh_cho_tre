// Tiện ích xuất báo cáo client-side từ dữ liệu backend.

export type ReportFormat = 'pdf' | 'excel' | 'csv' | 'word';

export interface ReportColumn {
  key: string;
  label: string;
  align?: 'left' | 'right';
  format?: (v: unknown, row: Record<string, unknown>) => string;
}

export interface ReportBundle {
  title: string;
  subtitle?: string;
  generatedAt: string; // ISO
  columns: ReportColumn[];
  rows: Record<string, unknown>[];
  summary?: { label: string; value: string | number }[];
  recommendations?: string[];
}

function slugify(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/gi, 'd')
    .replace(/[^a-zA-Z0-9-_]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase();
}

function renderCell(col: ReportColumn, row: Record<string, unknown>): string {
  const raw = row[col.key];
  if (col.format) return col.format(raw, row);
  if (raw === null || raw === undefined) return '';
  return String(raw);
}

function formatGeneratedAt(iso: string): string {
  return new Date(iso).toLocaleString('vi-VN');
}

function toCsv(bundle: ReportBundle): string {
  const escape = (v: string) => {
    if (/[",\n\r]/.test(v)) return `"${v.replace(/"/g, '""')}"`;
    return v;
  };
  const line = (values: Array<string | number>) => values.map((v) => escape(String(v))).join(',');
  const lines: string[] = [line([bundle.title])];

  if (bundle.subtitle) lines.push(line(['Mô tả', bundle.subtitle]));
  lines.push(line(['Tạo lúc', formatGeneratedAt(bundle.generatedAt)]));
  lines.push('');

  if (bundle.summary?.length) {
    lines.push(line(['Tóm tắt']));
    lines.push(line(['Chỉ số', 'Giá trị']));
    for (const item of bundle.summary) {
      lines.push(line([item.label, item.value]));
    }
    lines.push('');
  }

  if (bundle.rows.length > 0) {
    lines.push(line(['Bảng số liệu']));
    lines.push(line(bundle.columns.map((c) => c.label)));
    for (const row of bundle.rows) {
      lines.push(line(bundle.columns.map((col) => renderCell(col, row))));
    }
    lines.push('');
  }

  if (bundle.recommendations?.length) {
    lines.push(line(['Khuyến nghị']));
    bundle.recommendations.forEach((recommendation, index) => {
      lines.push(line([index + 1, recommendation]));
    });
    lines.push('');
  }

  return `${lines.join('\n')}\n`;
}

function toJson(bundle: ReportBundle): string {
  return JSON.stringify(bundle, null, 2);
}

function toHtml(bundle: ReportBundle): string {
  const table = bundle.rows.length > 0
    ? `<table><thead><tr>${bundle.columns
        .map((c) => `<th style="text-align:${c.align ?? 'left'}">${escapeHtml(c.label)}</th>`)
        .join('')}</tr></thead><tbody>${bundle.rows
        .map(
          (r) =>
            `<tr>${bundle.columns
              .map(
                (c) =>
                  `<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:${c.align ?? 'left'}">${escapeHtml(
                    renderCell(c, r),
                  )}</td>`,
              )
              .join('')}</tr>`,
        )
        .join('')}</tbody></table>`
    : '';

  const summary = bundle.summary?.length
    ? `<section style="margin:16px 0"><h3 style="margin:0 0 8px 0">Tóm tắt</h3><ul style="margin:0;padding-left:18px">${bundle.summary
        .map((s) => `<li><strong>${escapeHtml(s.label)}:</strong> ${escapeHtml(String(s.value))}</li>`)
        .join('')}</ul></section>`
    : '';

  const recs = bundle.recommendations?.length
    ? `<section style="margin:16px 0"><h3 style="margin:0 0 8px 0">Khuyến nghị</h3><ul style="margin:0;padding-left:18px">${bundle.recommendations
        .map((r) => `<li>${escapeHtml(r)}</li>`)
        .join('')}</ul></section>`
    : '';

  return `<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>${escapeHtml(bundle.title)}</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a;margin:24px;max-width:960px}
h1{margin:0 0 4px 0;font-size:20px}
.sub{color:#64748b;margin:0 0 16px 0;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th{text-align:left;padding:8px 10px;background:#f1f5f9;border-bottom:1px solid #cbd5e1;color:#334155}
tr:nth-child(even) td{background:#f8fafc}
@media print{.noprint{display:none}}
button{margin-right:6px;padding:6px 10px;border:1px solid #cbd5e1;background:#fff;border-radius:6px;cursor:pointer}
</style></head><body>
<div class="noprint" style="margin-bottom:12px"><button onclick="window.print()">In</button></div>
<h1>${escapeHtml(bundle.title)}</h1>
<p class="sub">${bundle.subtitle ? escapeHtml(bundle.subtitle) + ' · ' : ''}Tạo lúc ${formatGeneratedAt(bundle.generatedAt)}</p>
${summary}
${table}
${recs}
</body></html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      default: return '&#39;';
    }
  });
}

export interface DownloadResult {
  filename: string;
  sizeBytes: number;
  mime: string;
}

export function downloadReport(bundle: ReportBundle, format: ReportFormat): DownloadResult {
  // csv → .csv; excel → .csv (Excel mở được); word/pdf → .html (in bằng trình duyệt).
  let content = '';
  let mime = 'text/plain';
  let ext = 'txt';

  if (format === 'csv' || format === 'excel') {
    content = toCsv(bundle);
    mime = 'text/csv;charset=utf-8';
    ext = 'csv';
  } else if (format === 'word' || format === 'pdf') {
    content = toHtml(bundle);
    mime = 'text/html;charset=utf-8';
    ext = 'html';
  } else {
    content = toJson(bundle);
    mime = 'application/json';
    ext = 'json';
  }

  // Thêm BOM cho CSV để Excel hiểu UTF-8 tiếng Việt
  const payload = ext === 'csv' ? `\uFEFF${content}` : content;
  const blob = new Blob([payload], { type: mime });
  const url = URL.createObjectURL(blob);

  const filename = `${slugify(bundle.title)}-${bundle.generatedAt.slice(0, 10)}.${ext}`;

  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);

  return { filename, sizeBytes: blob.size, mime };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
