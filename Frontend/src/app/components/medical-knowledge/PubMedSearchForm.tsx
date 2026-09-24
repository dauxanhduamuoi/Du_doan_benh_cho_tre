import { useState, type FormEvent } from 'react';
import { Loader2, Search } from 'lucide-react';
import type { DiseaseGroupOption } from '@/lib/medicalKnowledgeApi';
import {
  factorIsComplete,
  type ExplanationFactorOption,
  type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeFactors';
import MedicalTopicSelector from './MedicalTopicSelector';

interface Props {
  diseaseGroups: DiseaseGroupOption[];
  factorOptions: ExplanationFactorOption[];
  diseaseGroupId: string;
  factor: MedicalFactorSelector | null;
  searchMode: 'GUIDED' | 'FREE';
  freeQuery: string;
  diseaseTerms: string[];
  defaultDiseaseTerm: string | null;
  maxResults: 10 | 15 | 20 | 25;
  selectedProviderCount?: number;
  yearFrom: number | null;
  yearTo: number | null;
  loading: boolean;
  pmid: string;
  pmidLoading: boolean;
  onDiseaseGroupChange: (value: string) => void;
  onFactorChange: (value: MedicalFactorSelector | null) => void;
  onSearchModeChange: (value: 'GUIDED' | 'FREE') => void;
  onFreeQueryChange: (value: string) => void;
  onDiseaseTermsChange: (values: string[]) => void;
  onMaxResultsChange: (value: 10 | 15 | 20 | 25) => void;
  onYearFromChange: (value: number | null) => void;
  onYearToChange: (value: number | null) => void;
  onSubmit: () => void;
  onPmidChange: (value: string) => void;
  onPmidLookup: () => void;
  showTopicSelector?: boolean;
}

export default function PubMedSearchForm(props: Props) {
  const [termDraft, setTermDraft] = useState('');
  const [termError, setTermError] = useState<string | null>(null);
  const [pmidError, setPmidError] = useState<string | null>(null);
  const yearsValid = (props.yearFrom === null || (props.yearFrom >= 1800 && props.yearFrom <= 2100))
    && (props.yearTo === null || (props.yearTo >= 1800 && props.yearTo <= 2100))
    && (props.yearFrom === null || props.yearTo === null || props.yearFrom <= props.yearTo);
  const canSearch = Boolean(
    props.diseaseGroupId
    && factorIsComplete(props.factor)
    && (props.searchMode === 'FREE' ? props.freeQuery.trim() : props.diseaseTerms.length)
    && yearsValid
    && !props.loading
    && !props.pmidLoading,
  );
  const canLookup = Boolean(props.diseaseGroupId && factorIsComplete(props.factor) && !props.loading && !props.pmidLoading);
  const selectedProviderCount = props.selectedProviderCount ?? 1;

  function addTerm() {
    const value = termDraft.trim();
    if (value.length < 2 || value.length > 120 || /["\[\]\r\n]/.test(value)) {
      setTermError('Từ khóa cần có 2–120 ký tự và không chứa cú pháp PubMed đặc biệt.');
      return;
    }
    if (props.diseaseTerms.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setTermError('Từ khóa này đã được thêm.');
      return;
    }
    if (props.diseaseTerms.length >= 8) {
      setTermError('Chỉ có thể thêm tối đa 8 từ khóa.');
      return;
    }
    props.onDiseaseTermsChange([...props.diseaseTerms, value]);
    setTermDraft('');
    setTermError(null);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    props.onSubmit();
  }

  function lookup() {
    const value = props.pmid.trim();
    if (!/^[0-9]{1,16}$/.test(value)) {
      setPmidError('PMID chỉ gồm các chữ số.');
      return;
    }
    setPmidError(null);
    props.onPmidChange(value);
    props.onPmidLookup();
  }

  return (
    <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      {props.showTopicSelector !== false && (
        <MedicalTopicSelector
          compact
          diseaseGroups={props.diseaseGroups}
          factorOptions={props.factorOptions}
          diseaseGroupId={props.diseaseGroupId}
          factor={props.factor}
          onDiseaseGroupChange={props.onDiseaseGroupChange}
          onFactorChange={props.onFactorChange}
        />
      )}

      <fieldset className={props.showTopicSelector === false ? '' : 'mt-6'}>
        <legend className="mb-2 text-sm font-semibold text-slate-800">Chế độ tìm kiếm</legend>
        <div className="flex flex-wrap gap-2">
          {([['GUIDED', 'Tìm có hướng dẫn'], ['FREE', 'Tìm kiếm PubMed tự do']] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={props.searchMode === value} onClick={() => props.onSearchModeChange(value)} className={`rounded-lg px-4 py-2 text-sm font-semibold ${props.searchMode === value ? 'bg-blue-600 text-white' : 'border border-slate-300 bg-white text-slate-700'}`}>{label}</button>
          ))}
        </div>
      </fieldset>

      {props.searchMode === 'FREE' ? (
        <div className="mt-5">
          <label htmlFor="pubmed-free-query" className="mb-1.5 block text-sm font-semibold text-slate-800">Truy vấn PubMed tự do</label>
          <textarea id="pubmed-free-query" value={props.freeQuery} maxLength={1000} onChange={(event) => props.onFreeQueryChange(event.target.value)} placeholder={'Ví dụ: intestinal infection children AND ("sex differences"[Title/Abstract])'} className="min-h-24 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm" />
          <p className="mt-1 text-xs font-semibold text-amber-700">Chỉ áp dụng cho PubMed / PMC. Dấu ngoặc, dấu ngoặc kép và field tag PubMed được giữ nguyên.</p>
        </div>
      ) : (
        <div className="mt-5">
          <label htmlFor="pubmed-disease-term" className="mb-1.5 block text-sm font-semibold text-slate-800">3. Từ khóa tìm kiếm</label>
          <p className="mb-1 text-sm text-blue-700">Tìm kiếm mặc định ưu tiên các nghiên cứu trên trẻ em.</p>
          <p className="mb-3 text-sm text-blue-700">Tìm có hướng dẫn sẽ chuyển từ khóa sang cú pháp phù hợp cho từng nguồn đã chọn.</p>
          <div className="mb-3 flex flex-wrap gap-2" aria-label="Các từ khóa đã thêm">
            {props.diseaseTerms.map((term) => (
              <span key={term} className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1.5 text-sm text-blue-800">
                <span>{term}</span>
                <button type="button" aria-label={`Xóa từ khóa ${term}`} onClick={() => props.onDiseaseTermsChange(props.diseaseTerms.filter((item) => item !== term))}>×</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input id="pubmed-disease-term" value={termDraft} onChange={(event) => { setTermDraft(event.target.value); setTermError(null); }} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addTerm(); } }} placeholder="Ví dụ: infectious diarrhea" className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2.5 text-sm" />
            <button type="button" onClick={addTerm} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700">Thêm từ khóa</button>
          </div>
          {termError && <p role="alert" className="mt-2 text-sm text-red-600">{termError}</p>}
          {props.defaultDiseaseTerm && !(props.diseaseTerms.length === 1 && props.diseaseTerms[0] === props.defaultDiseaseTerm) && <button type="button" onClick={() => props.onDiseaseTermsChange([props.defaultDiseaseTerm!])} className="mt-2 text-xs font-semibold text-blue-700">Khôi phục từ khóa mặc định</button>}
        </div>
      )}

      <details className="mt-6 rounded-xl border border-slate-200 bg-slate-50">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">Tùy chọn nâng cao</summary>
        <div className="border-t border-slate-200 p-4">
          <label htmlFor="pubmed-direct-pmid" className="mb-1 block text-sm font-semibold text-slate-800">Tra cứu trực tiếp PubMed bằng PMID</label>
          <p className="mb-3 text-sm text-slate-500">Chỉ áp dụng cho PubMed / PMC; PMID không áp dụng cho WHO.</p>
          <div className="flex gap-2">
            <input id="pubmed-direct-pmid" inputMode="numeric" value={props.pmid} onChange={(event) => props.onPmidChange(event.target.value)} placeholder="Ví dụ: 34201085" className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" />
            <button type="button" onClick={lookup} disabled={!canLookup} className="inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">{props.pmidLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}{props.pmidLoading ? 'Đang tìm bài…' : 'Tìm bài'}</button>
          </div>
          {pmidError && <p role="alert" className="mt-2 text-sm text-red-600">{pmidError}</p>}
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div><label htmlFor="results-per-provider" className="mb-1 block text-xs font-semibold text-slate-700">Số kết quả mỗi nguồn</label><select id="results-per-provider" aria-label="Số kết quả mỗi nguồn" value={props.maxResults} onChange={(event) => props.onMaxResultsChange(Number(event.target.value) as 10 | 15 | 20 | 25)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value={10}>10 kết quả</option><option value={15}>15 kết quả</option><option value={20}>20 kết quả</option><option value={25}>25 kết quả</option></select></div>
            <input aria-label="Từ năm" type="number" min={1800} max={2100} value={props.yearFrom ?? ''} onChange={(event) => props.onYearFromChange(event.target.value ? Number(event.target.value) : null)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input aria-label="Đến năm" type="number" min={1800} max={2100} value={props.yearTo ?? ''} onChange={(event) => props.onYearToChange(event.target.value ? Number(event.target.value) : null)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <p className="mt-2 text-xs text-slate-500">Mỗi nguồn đã chọn trả tối đa {props.maxResults} tài liệu. {selectedProviderCount} nguồn × {props.maxResults} → tối đa {selectedProviderCount * props.maxResults} kết quả.</p>
        </div>
      </details>

      <button type="submit" disabled={!canSearch} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:bg-slate-300">{props.loading ? <Loader2 size={17} className="animate-spin" /> : <Search size={17} />}{props.loading ? 'Đang tìm tài liệu…' : props.searchMode === 'FREE' ? 'Tìm tài liệu PubMed' : 'Tìm tài liệu'}</button>
    </form>
  );
}
