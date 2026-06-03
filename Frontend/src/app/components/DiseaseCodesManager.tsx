import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCcw,
  Search,
} from 'lucide-react';
import * as api from '@/lib/api';

export default function DiseaseCodesManager() {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<api.DiseaseCodesStatus | null>(null);
  const [data, setData] = useState<api.DiseaseCodesListResponse | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(id);
  }, [search]);

  const load = useCallback(async () => {
    if (!expanded) return;

    setLoading(true);
    setError(null);
    try {
      const [st, list] = await Promise.all([
        api.getDiseaseCodesStatus(),
        api.listDiseaseCodes({
          search: debouncedSearch || undefined,
          onlyMissingGroup: onlyMissing,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
      ]);
      setStatus(st);
      setData(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, expanded, onlyMissing, page, pageSize]);

  useEffect(() => {
    if (expanded) load();
  }, [expanded, load]);

  const totalPages = useMemo(() => {
    const total = data?.total ?? 0;
    return Math.max(1, Math.ceil(total / pageSize));
  }, [data?.total, pageSize]);

  if (!expanded) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-left hover:bg-slate-50 transition-colors"
        >
          <div>
            <h3 className="text-base font-semibold text-slate-800">Kiểm tra danh sách mã bệnh DS-MaBenh</h3>
            <p className="text-sm text-slate-500 mt-1">
              Bấm để mở bảng tìm kiếm MAICD, tên bệnh, nhóm bệnh và kiểm tra mã thiếu nhóm.
            </p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 bg-white">
            Mở danh sách mã bệnh
            <ChevronDown size={16} />
          </span>
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200 shadow-sm space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-800">Danh sách mã bệnh đã import</h3>
          <p className="text-sm text-slate-500 mt-1">
            Dùng để kiểm tra DS-MaBenh, tìm MAICD, tên bệnh và nhóm bệnh trước khi import DS-BenhNhan.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
            Làm mới mã bệnh
          </button>
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50"
          >
            Thu gọn
            <ChevronUp size={16} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-slate-200 p-3 bg-slate-50">
          <div className="text-xs text-slate-500">Tổng mã bệnh</div>
          <div className="text-xl font-semibold text-slate-800">{status?.total_codes ?? 0}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 bg-slate-50">
          <div className="text-xs text-slate-500">Số nhóm bệnh</div>
          <div className="text-xl font-semibold text-slate-800">{status?.distinct_groups ?? 0}</div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 bg-slate-50">
          <div className="text-xs text-slate-500">Mã thiếu nhóm</div>
          <div className={`text-xl font-semibold ${(data?.missing_group_total ?? 0) > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
            {data?.missing_group_total ?? 0}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 bg-slate-50">
          <div className="text-xs text-slate-500">File đang dùng</div>
          <div className="text-sm font-medium text-slate-700 truncate" title={status?.uploaded_file ?? ''}>
            {status?.uploaded_file ?? 'Chưa có'}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[260px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm MAICD, tên bệnh, IDNHOMICD, MANHOMBAOCAO, tên nhóm bệnh..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={onlyMissing}
            onChange={(e) => {
              setOnlyMissing(e.target.checked);
              setPage(1);
            }}
            className="rounded border-slate-300"
          />
          Chỉ xem mã thiếu nhóm bệnh
        </label>
        <select
          value={pageSize}
          onChange={(e) => {
            setPageSize(Number(e.target.value));
            setPage(1);
          }}
          className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm"
        >
          {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n} dòng</option>)}
        </select>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {!error && status && !status.has_disease_codes && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
          Chưa có DS-MaBenh. Hãy import file DS-MaBenh trước, sau đó mới import DS-BenhNhan để phân tích.
        </div>
      )}

      {!error && (data?.missing_group_total ?? 0) === 0 && (status?.has_disease_codes ?? false) && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          <CheckCircle2 size={16} className="mt-0.5" />
          <span>Không phát hiện mã bệnh nào trong DS-MaBenh bị thiếu thông tin nhóm bệnh.</span>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left font-medium">MAICD</th>
              <th className="px-3 py-2 text-left font-medium min-w-[220px]">Tên bệnh</th>
              <th className="px-3 py-2 text-left font-medium">IDNHOMICD</th>
              <th className="px-3 py-2 text-left font-medium">MANHOMBAOCAO</th>
              <th className="px-3 py-2 text-left font-medium min-w-[260px]">Tên nhóm bệnh</th>
              <th className="px-3 py-2 text-left font-medium">Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                  <span className="inline-flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> Đang tải...</span>
                </td>
              </tr>
            )}
            {!loading && (data?.rows.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-400">Không có dữ liệu phù hợp.</td>
              </tr>
            )}
            {!loading && data?.rows.map((row) => (
              <tr key={row.id} className="border-t border-slate-100 hover:bg-slate-50 align-top">
                <td className="px-3 py-2 font-mono font-semibold text-slate-700">{row.icd_code}</td>
                <td className="px-3 py-2 text-slate-700">{row.disease_name ?? '—'}</td>
                <td className="px-3 py-2 text-slate-700">{row.group_id ?? '—'}</td>
                <td className="px-3 py-2 text-slate-700">{row.report_group_code ?? '—'}</td>
                <td className="px-3 py-2 text-slate-700">{row.group_name ?? '—'}</td>
                <td className="px-3 py-2">
                  {row.missing_group ? (
                    <span className="inline-flex rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">Thiếu nhóm</span>
                  ) : (
                    <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">OK</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
        <span>
          Hiển thị {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, data?.total ?? 0)} / {data?.total ?? 0}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage(1)}
            disabled={page <= 1}
            className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
          >«</button>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
          >‹</button>
          <span className="px-2">Trang {page} / {totalPages}</span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
          >›</button>
          <button
            onClick={() => setPage(totalPages)}
            disabled={page >= totalPages}
            className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
          >»</button>
        </div>
      </div>
    </div>
  );
}
