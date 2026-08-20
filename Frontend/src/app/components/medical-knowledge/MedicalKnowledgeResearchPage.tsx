import { useEffect, useState } from 'react';
import { BookOpenText, Loader2 } from 'lucide-react';
import { useAuth } from '@/app/contexts/AuthContext';
import {
  getMedicalKnowledgeOptions,
  importPubMedSources,
  medicalKnowledgeErrorMessage,
  searchPubMed,
  type MedicalKnowledgeOptions,
  type PubMedSearchResponse,
} from '@/lib/medicalKnowledgeApi';
import PubMedResults from './PubMedResults';
import PubMedSearchForm from './PubMedSearchForm';
import MedicalDraftWorkspace from './MedicalDraftWorkspace';
import ServiceConfigurationPanel from './ServiceConfigurationPanel';

export function canResearchMedicalKnowledge(role: string | null | undefined): boolean {
  return role === 'admin' || role === 'staff';
}

export default function MedicalKnowledgeResearchPage() {
  const { user } = useAuth();
  const [options, setOptions] = useState<MedicalKnowledgeOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [diseaseGroupId, setDiseaseGroupId] = useState('');
  const [weatherFactor, setWeatherFactor] = useState('');
  const [diseaseTerms, setDiseaseTerms] = useState<string[]>([]);
  const [maxResults, setMaxResults] = useState<10 | 15 | 25>(10);
  const [yearFrom, setYearFrom] = useState<number | null>(null);
  const [yearTo, setYearTo] = useState<number | null>(null);
  const [searchResult, setSearchResult] = useState<PubMedSearchResponse | null>(null);
  const [selectedPmids, setSelectedPmids] = useState<Set<string>>(new Set());
  const [importedPmids, setImportedPmids] = useState<Set<string>>(new Set());
  const [importedSourceIds, setImportedSourceIds] = useState<number[]>([]);
  const [searching, setSearching] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const authorized = canResearchMedicalKnowledge(user?.role);

  useEffect(() => {
    if (!authorized) {
      setOptionsLoading(false);
      return;
    }
    let cancelled = false;
    getMedicalKnowledgeOptions()
      .then((value) => {
        if (!cancelled) setOptions(value);
      })
      .catch((reason) => {
        if (!cancelled) setError(medicalKnowledgeErrorMessage(reason));
      })
      .finally(() => {
        if (!cancelled) setOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authorized]);

  function clearResearchResult() {
    setSearchResult(null);
    setSelectedPmids(new Set());
    setError(null);
    setSuccess(null);
  }

  function changeDiseaseGroup(value: string) {
    setDiseaseGroupId(value);
    setDiseaseTerms([]);
    setImportedPmids(new Set());
    setImportedSourceIds([]);
    clearResearchResult();
  }

  function changeWeatherFactor(value: string) {
    setWeatherFactor(value);
    setImportedPmids(new Set());
    setImportedSourceIds([]);
    clearResearchResult();
  }

  async function runSearch() {
    setSearching(true);
    setError(null);
    setSuccess(null);
    setSearchResult(null);
    setSelectedPmids(new Set());
    try {
      const response = await searchPubMed({
        disease_group_id: diseaseGroupId,
        weather_factor: weatherFactor,
        disease_terms: diseaseTerms,
        max_results: maxResults,
        year_from: yearFrom,
        year_to: yearTo,
      });
      setSearchResult(response);
    } catch (reason) {
      setError(medicalKnowledgeErrorMessage(reason));
    } finally {
      setSearching(false);
    }
  }

  function togglePmid(pmid: string) {
    setSelectedPmids((current) => {
      const next = new Set(current);
      if (next.has(pmid)) next.delete(pmid);
      else next.add(pmid);
      return next;
    });
  }

  function toggleAll() {
    if (!searchResult) return;
    const allSelected = searchResult.results.every((paper) => selectedPmids.has(paper.pmid));
    setSelectedPmids(allSelected ? new Set() : new Set(searchResult.results.map((paper) => paper.pmid)));
  }

  async function importSelected() {
    const pmids = Array.from(selectedPmids);
    if (pmids.length === 0) return;
    setImporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await importPubMedSources(pmids);
      setImportedPmids((current) => new Set([...current, ...response.sources.map((source) => source.pmid)]));
      setImportedSourceIds((current) => Array.from(new Set([
        ...current,
        ...response.sources.map((source) => source.id),
      ])));
      setSelectedPmids(new Set());
      const parts = [`Đã thêm ${response.count} tài liệu vào kho nguồn.`];
      if (response.created_count > 0) parts.push(`${response.created_count} tài liệu mới đã được lưu.`);
      if (response.reused_count > 0) parts.push(`${response.reused_count} tài liệu đã có sẵn nên được sử dụng lại.`);
      setSuccess(parts.join(' '));
    } catch (reason) {
      setError(medicalKnowledgeErrorMessage(reason));
    } finally {
      setImporting(false);
    }
  }

  if (!authorized) {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        Bạn không có quyền sử dụng chức năng này.
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-blue-700 via-blue-600 to-cyan-600 p-5 text-white shadow-lg sm:p-7">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-white/15 p-2.5"><BookOpenText size={24} /></div>
          <div>
            <h1 className="text-xl font-bold sm:text-2xl">Kho kiến thức y khoa</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-blue-50 sm:text-base">
              Tìm tài liệu khoa học về mối liên hệ giữa nhóm bệnh và các yếu tố thời tiết. Tài liệu được chọn sẽ được lưu làm nguồn tham khảo để tạo giải thích y khoa ở bước sau.
            </p>
          </div>
        </div>
      </section>

      <ServiceConfigurationPanel />

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {success && (
        <div role="status" aria-live="polite" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {success}
        </div>
      )}

      {optionsLoading ? (
        <div role="status" className="flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white p-10 text-sm text-slate-500">
          <Loader2 size={18} className="animate-spin" /> Đang tải danh mục nghiên cứu…
        </div>
      ) : options ? (
        <PubMedSearchForm
          diseaseGroups={options.disease_groups}
          weatherFactors={options.weather_factors}
          diseaseGroupId={diseaseGroupId}
          weatherFactor={weatherFactor}
          diseaseTerms={diseaseTerms}
          maxResults={maxResults}
          yearFrom={yearFrom}
          yearTo={yearTo}
          loading={searching}
          onDiseaseGroupChange={changeDiseaseGroup}
          onWeatherFactorChange={changeWeatherFactor}
          onDiseaseTermsChange={setDiseaseTerms}
          onMaxResultsChange={setMaxResults}
          onYearFromChange={setYearFrom}
          onYearToChange={setYearTo}
          onSubmit={runSearch}
        />
      ) : null}

      {searchResult && (
        <PubMedResults
          response={searchResult}
          selectedPmids={selectedPmids}
          importedPmids={importedPmids}
          importing={importing}
          onToggle={togglePmid}
          onToggleAll={toggleAll}
          onImport={importSelected}
        />
      )}

      {options && (
        <MedicalDraftWorkspace
          diseaseGroupId={diseaseGroupId}
          weatherFactor={weatherFactor}
          importedSourceIds={importedSourceIds}
          llmAvailable={options.llm_draft_generation_available}
        />
      )}
    </div>
  );
}
