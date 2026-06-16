import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Eye, Loader2, RefreshCcw, Upload, X } from 'lucide-react';
import * as api from '@/lib/api';
import { clearAreaInsightsCache } from '@/lib/areaInsightsCache';
import { clearChartDataCaches } from '@/lib/chartDataCache';

export default function ProvinceRegionsManager() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<api.ProvinceRegionsStatus | null>(null);
  const [preview, setPreview] = useState<api.ProvinceRegionsPreview | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [showPreviewRows, setShowPreviewRows] = useState(false);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadStatus = async () => {
    try {
      const st = await api.getProvinceRegionsStatus();
      setStatus(st);
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : String(e) });
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handlePreview = async (file: File) => {
    setLoading(true);
    setMessage(null);
    setPreview(null);
    setSelectedFile(file);
    setShowPreviewRows(false);
    try {
      const data = await api.previewProvinceRegions(file);
      setPreview(data);
      if (data.missing_columns.length > 0) {
        setMessage({ type: 'error', text: `File thiếu cột: ${data.missing_columns.join(', ')}` });
      } else {
        setMessage({ type: 'success', text: `Đã kiểm tra file: ${data.valid_rows} tỉnh/thành hợp lệ.` });
      }
    } catch (e) {
      setSelectedFile(null);
      setMessage({ type: 'error', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (!selectedFile || !preview || preview.missing_columns.length > 0) return;
    setImporting(true);
    setMessage(null);
    clearAreaInsightsCache();
    clearChartDataCaches();
    try {
      const res = await api.importProvinceRegions(selectedFile);
      setMessage({ type: 'success', text: `${res.message} Đã lưu ${res.result.saved_rows} tỉnh/thành.` });
      setPreview(null);
      setSelectedFile(null);
      await loadStatus();
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setImporting(false);
    }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-800">Phân miền tỉnh/thành</h3>
          <p className="mt-1 text-sm text-slate-500">
            Import file Excel chứa tỉnh/thành phố và cột miền để mục Khu vực lọc theo Miền Bắc, Miền Trung, Miền Nam.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => fileRef.current?.click()}
            disabled={loading || importing}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            Chọn file kiểm tra
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f) handlePreview(f);
            }}
          />
          <button
            onClick={loadStatus}
            disabled={loading || importing}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCcw size={16} />
            Làm mới
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Info label="Trạng thái" value={status?.has_province_regions ? 'Đã import' : 'Chưa import'} />
        <Info label="Số tỉnh/thành" value={String(status?.total_rows ?? 0)} />
        <Info label="File đang lưu" value={status?.uploaded_file ?? 'Chưa có'} />
      </div>

      <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm leading-6 text-blue-700">
        File cần có cột <span className="font-mono">province_code</span>,{' '}
        <span className="font-mono">province_name</span>, <span className="font-mono">mien_code</span>,{' '}
        <span className="font-mono">mien</span>. Cột <span className="font-mono">aliases</span> là tùy chọn.
      </div>

      {message && (
        <div
          className={`mt-4 flex gap-2 rounded-lg border px-3 py-2 text-sm ${
            message.type === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {message.type === 'success' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
          <span>{message.text}</span>
        </div>
      )}

      {preview && (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h4 className="font-semibold text-slate-800">Kết quả kiểm tra file</h4>
              <p className="mt-1 text-sm text-slate-500">
                Sheet {preview.sheet} · {preview.total_rows} dòng · {preview.valid_rows} dòng hợp lệ · {preview.invalid_rows} dòng bỏ qua
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setShowPreviewRows((v) => !v)}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                <Eye size={16} />
                {showPreviewRows ? 'Ẩn mẫu dữ liệu' : 'Xem mẫu dữ liệu'}
              </button>
              <button
                onClick={() => {
                  setPreview(null);
                  setSelectedFile(null);
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                <X size={16} />
                Hủy
              </button>
              <button
                onClick={handleImport}
                disabled={!selectedFile || preview.missing_columns.length > 0 || importing}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                Import file này
              </button>
            </div>
          </div>

          {preview.missing_columns.length > 0 && (
            <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              File thiếu cột bắt buộc: {preview.missing_columns.join(', ')}
            </p>
          )}

          {showPreviewRows && <RowsTable rows={preview.sample_rows} />}
        </div>
      )}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-800" title={value}>{value}</p>
    </div>
  );
}

function RowsTable({ rows }: { rows: Array<Record<string, string>> }) {
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  if (rows.length === 0) {
    return <p className="mt-3 text-sm text-slate-500">Không có dữ liệu để hiển thị.</p>;
  }
  return (
    <div className="mt-3 max-h-[360px] overflow-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="sticky top-0 bg-slate-100 text-xs uppercase text-slate-500">
          <tr>
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 text-left font-semibold">{col}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => (
            <tr key={index} className="align-top">
              {columns.map((col) => (
                <td key={col} className="max-w-[320px] px-3 py-2 text-slate-700">
                  <div className="line-clamp-4">{row[col]}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
