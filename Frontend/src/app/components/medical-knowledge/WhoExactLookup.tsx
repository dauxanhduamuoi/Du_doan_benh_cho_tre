import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';
import {
  lookupMedicalEvidenceExact, importMedicalEvidenceProviderSources,
  type ReviewedProviderSource, type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeApi';

interface Props {
  diseaseGroupId: string;
  factor: MedicalFactorSelector;
  disabled: boolean;
  onStart: () => void;
  onBusyChange: (busy: boolean) => void;
  onImported: () => Promise<void>;
}

const guidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export default function WhoExactLookup(props: Props) {
  const [identifier, setIdentifier] = useState('');
  const [result, setResult] = useState<ReviewedProviderSource | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const busyCallback = useRef(props.onBusyChange);
  busyCallback.current = props.onBusyChange;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; busyCallback.current(false); };
  }, []);

  function setLoading(value: boolean) {
    setBusy(value);
    props.onBusyChange(value);
  }

  async function lookup() {
    const value = identifier.trim().toLowerCase();
    if (!guidPattern.test(value)) {
      setError('Nhập GUID của ấn phẩm WHO. Chưa hỗ trợ mã Biblio dạng số hoặc URL.');
      return;
    }
    props.onStart();
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const response = await lookupMedicalEvidenceExact('WHO', value, props.diseaseGroupId, props.factor);
      if (!mounted.current) return;
      if (response.lookup_mode !== 'EXACT' || response.result.provider_id !== 'WHO'
          || response.requested_identifier.toLowerCase() !== value
          || response.result.external_id.toLowerCase() !== value) {
        throw new Error('Identity mismatch');
      }
      // Exact identity is intentionally not passed through the Guided filter.
      setResult(response.result);
    } catch (reason) {
      if (mounted.current) setError(reason instanceof ApiError && reason.status === 404
        ? 'Không tìm thấy ấn phẩm WHO với GUID này.' : 'Không thể xác minh đúng ấn phẩm WHO. Vui lòng thử lại.');
    } finally {
      if (mounted.current) setLoading(false);
    }
  }

  async function addToLibrary() {
    if (!result) return;
    setError(null);
    setLoading(true);
    try {
      const imported = await importMedicalEvidenceProviderSources(props.diseaseGroupId, props.factor, [{
        provider_id: result.provider_id, external_id: result.external_id,
        canonical_url: result.url, title: result.title, source_kind: result.source_kind,
        authors: result.authors, publisher_or_journal: result.publisher_or_journal,
        publication_date: result.publication_date, publication_year: result.publication_year,
        doi: result.doi,
      }]);
      if (!mounted.current) return;
      const item = imported.sources.find(source => source.provider_id === result.provider_id
        && source.external_id.toLowerCase() === result.external_id.toLowerCase());
      if (!item?.source_id) throw new Error('Import failed');
      setResult({ ...result, in_topic_library: true, source_id: item.source_id });
      await props.onImported();
    } catch {
      if (mounted.current) setError('Chưa thêm được ấn phẩm WHO vào kho chủ đề.');
    } finally {
      if (mounted.current) setLoading(false);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <details>
        <summary className="cursor-pointer font-semibold text-slate-800">Tìm chính xác ấn phẩm WHO</summary>
        <label htmlFor="who-exact-guid" className="mt-3 block text-sm font-semibold">GUID của ấn phẩm WHO</label>
        <p className="my-2 text-xs text-slate-500">Chỉ hỗ trợ GUID của WHO Publications REST. Mã Biblio dạng số và URL chưa được hỗ trợ.</p>
        <div className="flex gap-2">
          <input id="who-exact-guid" value={identifier} onChange={event => setIdentifier(event.target.value)} className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm" />
          <button type="button" disabled={busy || props.disabled} onClick={lookup} className="rounded-lg bg-slate-800 px-3 py-2 text-sm text-white disabled:opacity-50">{busy ? 'Đang xử lý…' : 'Tìm theo GUID WHO'}</button>
        </div>
      </details>
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      {result && <div className="mt-4 space-y-2 border-t pt-4">
        <h3 className="font-bold">Tài liệu chính xác theo GUID WHO</h3>
        <p className="text-xs text-slate-600">Không lọc theo mức phù hợp chủ đề. Thêm vào kho tham khảo không đồng nghĩa đủ điều kiện tạo bản nháp AI.</p>
        <p className="font-semibold">{result.title}</p>
        <p className="break-all text-xs text-slate-500">GUID: {result.external_id}</p>
        {result.abstract_text && <p className="text-sm text-slate-600">{result.abstract_text}</p>}
        <button type="button" disabled={busy || result.in_topic_library} onClick={addToLibrary} className="rounded-lg bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-50">{result.in_topic_library ? 'Đã có trong kho chủ đề' : 'Thêm ấn phẩm WHO vào kho chủ đề'}</button>
      </div>}
    </section>
  );
}
