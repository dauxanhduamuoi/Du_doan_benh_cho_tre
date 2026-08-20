import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Loader2, Plus, Search, X } from 'lucide-react';
import type { DiseaseGroupOption, WeatherFactorOption } from '@/lib/medicalKnowledgeApi';

interface Props {
  diseaseGroups: DiseaseGroupOption[];
  weatherFactors: WeatherFactorOption[];
  diseaseGroupId: string;
  weatherFactor: string;
  diseaseTerms: string[];
  maxResults: 10 | 15 | 25;
  yearFrom: number | null;
  yearTo: number | null;
  loading: boolean;
  onDiseaseGroupChange: (value: string) => void;
  onWeatherFactorChange: (value: string) => void;
  onDiseaseTermsChange: (values: string[]) => void;
  onMaxResultsChange: (value: 10 | 15 | 25) => void;
  onYearFromChange: (value: number | null) => void;
  onYearToChange: (value: number | null) => void;
  onSubmit: () => void;
}

export default function PubMedSearchForm(props: Props) {
  const [draftTerm, setDraftTerm] = useState('');
  const [termError, setTermError] = useState<string | null>(null);

  useEffect(() => {
    setDraftTerm('');
    setTermError(null);
  }, [props.diseaseGroupId]);

  function addTerm() {
    const term = draftTerm.trim();
    if (!term) {
      setTermError('Hãy nhập từ khóa trước khi thêm.');
      return;
    }
    if (term.length < 2 || term.length > 120) {
      setTermError('Mỗi từ khóa cần có từ 2 đến 120 ký tự.');
      return;
    }
    if (/["\[\]\r\n]/.test(term)) {
      setTermError('Từ khóa không được chứa dấu ngoặc vuông, dấu ngoặc kép hoặc xuống dòng.');
      return;
    }
    if (props.diseaseTerms.some((value) => value.toLocaleLowerCase() === term.toLocaleLowerCase())) {
      setTermError('Từ khóa này đã được thêm.');
      return;
    }
    if (props.diseaseTerms.length >= 8) {
      setTermError('Chỉ có thể thêm tối đa 8 từ khóa.');
      return;
    }
    props.onDiseaseTermsChange([...props.diseaseTerms, term]);
    setDraftTerm('');
    setTermError(null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      addTerm();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    props.onSubmit();
  }

  const canSearch = Boolean(
    props.diseaseGroupId &&
      props.weatherFactor &&
      props.diseaseTerms.length > 0 &&
      !props.loading &&
      (props.yearFrom === null || (props.yearFrom >= 1800 && props.yearFrom <= 2100)) &&
      (props.yearTo === null || (props.yearTo >= 1800 && props.yearTo <= 2100)) &&
      (props.yearFrom === null || props.yearTo === null || props.yearFrom <= props.yearTo),
  );

  return (
    <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <label htmlFor="medical-disease-group" className="mb-1.5 block text-sm font-semibold text-slate-800">
            1. Nhóm bệnh
          </label>
          <select
            id="medical-disease-group"
            value={props.diseaseGroupId}
            onChange={(event) => props.onDiseaseGroupChange(event.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-800 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Chọn nhóm bệnh</option>
            {props.diseaseGroups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.id} — {group.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="medical-weather-factor" className="mb-1.5 block text-sm font-semibold text-slate-800">
            2. Yếu tố thời tiết
          </label>
          <select
            id="medical-weather-factor"
            value={props.weatherFactor}
            onChange={(event) => props.onWeatherFactorChange(event.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-800 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Chọn yếu tố thời tiết</option>
            {props.weatherFactors.map((factor) => (
              <option key={factor.value} value={factor.value}>
                {factor.label_vi}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-6">
        <label htmlFor="pubmed-disease-term" className="mb-1 block text-sm font-semibold text-slate-800">
          3. Từ khóa bệnh dùng để tìm PubMed
        </label>
        <p className="mb-3 text-sm leading-6 text-slate-500">
          PubMed chủ yếu sử dụng thuật ngữ y khoa tiếng Anh. Hãy nhập một hoặc vài thuật ngữ mô tả đúng nhóm bệnh.
        </p>
        {props.diseaseTerms.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2" aria-label="Các từ khóa đã thêm">
            {props.diseaseTerms.map((term) => (
              <span key={term.toLocaleLowerCase()} className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1.5 text-sm text-blue-800">
                <span className="break-words">{term}</span>
                <button
                  type="button"
                  onClick={() => props.onDiseaseTermsChange(props.diseaseTerms.filter((value) => value !== term))}
                  aria-label={`Xóa từ khóa ${term}`}
                  className="rounded-full p-0.5 hover:bg-blue-100"
                >
                  <X size={14} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="pubmed-disease-term"
            value={draftTerm}
            onChange={(event) => {
              setDraftTerm(event.target.value);
              if (termError) setTermError(null);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Ví dụ: infectious diarrhea"
            className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          <button
            type="button"
            onClick={addTerm}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700 hover:bg-blue-100"
          >
            <Plus size={16} /> Thêm từ khóa
          </button>
        </div>
        {termError && <p role="alert" className="mt-2 text-sm text-red-600">{termError}</p>}
        {props.diseaseTerms.length === 0 && !termError && (
          <p className="mt-2 text-xs text-slate-400">Cần ít nhất 1 và tối đa 8 từ khóa.</p>
        )}
      </div>

      <details className="mt-6 rounded-xl border border-slate-200 bg-slate-50">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">Tùy chọn nâng cao</summary>
        <div className="grid gap-4 border-t border-slate-200 p-4 sm:grid-cols-3">
          <div>
            <label htmlFor="pubmed-max-results" className="mb-1 block text-sm text-slate-700">Số kết quả</label>
            <select
              id="pubmed-max-results"
              value={props.maxResults}
              onChange={(event) => props.onMaxResultsChange(Number(event.target.value) as 10 | 15 | 25)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value={10}>10</option>
              <option value={15}>15</option>
              <option value={25}>25</option>
            </select>
          </div>
          <div>
            <label htmlFor="pubmed-year-from" className="mb-1 block text-sm text-slate-700">Từ năm</label>
            <input
              id="pubmed-year-from"
              type="number"
              min={1800}
              max={2100}
              value={props.yearFrom ?? ''}
              onChange={(event) => props.onYearFromChange(event.target.value ? Number(event.target.value) : null)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="pubmed-year-to" className="mb-1 block text-sm text-slate-700">Đến năm</label>
            <input
              id="pubmed-year-to"
              type="number"
              min={1800}
              max={2100}
              value={props.yearTo ?? ''}
              onChange={(event) => props.onYearToChange(event.target.value ? Number(event.target.value) : null)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </div>
        </div>
      </details>

      {props.yearFrom !== null && props.yearTo !== null && props.yearFrom > props.yearTo && (
        <p role="alert" className="mt-3 text-sm text-red-600">Năm bắt đầu không được lớn hơn năm kết thúc.</p>
      )}

      <button
        type="submit"
        disabled={!canSearch}
        className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300 sm:w-auto"
      >
        {props.loading ? <Loader2 size={17} className="animate-spin" /> : <Search size={17} />}
        {props.loading ? 'Đang tìm tài liệu…' : 'Tìm tài liệu PubMed'}
      </button>
    </form>
  );
}
