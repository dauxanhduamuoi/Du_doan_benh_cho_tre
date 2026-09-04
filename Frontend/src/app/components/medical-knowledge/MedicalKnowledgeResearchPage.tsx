import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BookCheck, BookOpenText, Bot, ChevronDown, FileSearch, Library,
  Loader2, Settings2, Sparkles, X,
} from 'lucide-react';
import { useAuth } from '@/app/contexts/AuthContext';
import {
  getMedicalKnowledgeOptions,
  getMedicalKnowledgeTopicSources,
  importPubMedSources,
  lookupPubMedByPmid,
  directPmidErrorMessage,
  isTopicSourceAiReadable,
  MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES,
  medicalKnowledgeErrorMessage,
  searchPubMed,
  type MedicalKnowledgeOptions,
  type DiseaseGroupOption,
  type PubMedSearchResponse,
  type TopicSourceLibrary,
  type TopicSourceLibraryItem,
  evidenceContentLabel,
} from '@/lib/medicalKnowledgeApi';
import {
  factorIsComplete,
  factorLabel,
  factorTopicKey,
  type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeFactors';
import PubMedResults from './PubMedResults';
import PubMedSearchForm from './PubMedSearchForm';
import MedicalDraftWorkspace from './MedicalDraftWorkspace';
import ServiceConfigurationPanel from './ServiceConfigurationPanel';
import MedicalTopicSourceLibrary from './MedicalTopicSourceLibrary';
import AutoMedicalKnowledgePanel from './AutoMedicalKnowledgePanel';
import MedicalTopicSelector from './MedicalTopicSelector';

export const KNOWLEDGE_VIEW_QUERY_KEY = 'knowledgeView';
export type KnowledgeView = 'reviewed' | 'auto';
type ReviewedSourceView = 'search' | 'library' | 'selection';

export function resolveKnowledgeView(search: string): KnowledgeView {
  return new URLSearchParams(search).get(KNOWLEDGE_VIEW_QUERY_KEY) === 'auto' ? 'auto' : 'reviewed';
}

export function canResearchMedicalKnowledge(role: string | null | undefined): boolean {
  return role === 'admin' || role === 'staff';
}

export function getDefaultPubMedDiseaseKeyword(
  diseaseGroup: DiseaseGroupOption | undefined,
): string | null {
  if (!diseaseGroup) return null;
  const structuredEnglishName = diseaseGroup.english_name?.trim();
  if (structuredEnglishName) return structuredEnglishName;

  const separatorIndex = diseaseGroup.name.indexOf(' - ');
  if (separatorIndex < 0) return null;
  const parsedEnglishName = diseaseGroup.name.slice(separatorIndex + 3).trim();
  return parsedEnglishName || null;
}

export default function MedicalKnowledgeResearchPage() {
  const { user } = useAuth();
  const [options, setOptions] = useState<MedicalKnowledgeOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [diseaseGroupId, setDiseaseGroupId] = useState('');
  const [factor, setFactor] = useState<MedicalFactorSelector | null>(null);
  const [pubmedSearchMode, setPubmedSearchMode] = useState<'GUIDED' | 'FREE'>('GUIDED');
  const [freeQuery, setFreeQuery] = useState('');
  const [diseaseTerms, setDiseaseTerms] = useState<string[]>([]);
  const [maxResults, setMaxResults] = useState<10 | 15 | 25>(10);
  const [yearFrom, setYearFrom] = useState<number | null>(null);
  const [yearTo, setYearTo] = useState<number | null>(null);
  const [searchResult, setSearchResult] = useState<PubMedSearchResponse | null>(null);
  const [resultMode, setResultMode] = useState<'keyword' | 'pmid'>('keyword');
  const [pmid, setPmid] = useState('');
  const [selectedImportPmids, setSelectedImportPmids] = useState<Set<string>>(new Set());
  const [topicLibrary, setTopicLibrary] = useState<TopicSourceLibrary | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [selectedDraftSourceIds, setSelectedDraftSourceIds] = useState<Set<number>>(new Set());
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [pmidSearching, setPmidSearching] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [knowledgeView, setKnowledgeView] = useState<KnowledgeView>(() => resolveKnowledgeView(window.location.search));
  const [sourceView, setSourceView] = useState<ReviewedSourceView>('search');
  const currentTopicKey = factorTopicKey(diseaseGroupId, factor);
  const currentTopicKeyRef = useRef(currentTopicKey);
  currentTopicKeyRef.current = currentTopicKey;

  const authorized = canResearchMedicalKnowledge(user?.role);

  useEffect(() => {
    const syncKnowledgeView = () => setKnowledgeView(resolveKnowledgeView(window.location.search));
    window.addEventListener('popstate', syncKnowledgeView);
    return () => window.removeEventListener('popstate', syncKnowledgeView);
  }, []);

  const navigateKnowledgeView = useCallback((view: KnowledgeView) => {
    const url = new URL(window.location.href);
    url.searchParams.set(KNOWLEDGE_VIEW_QUERY_KEY, view);
    window.history.pushState(window.history.state, '', url);
    setKnowledgeView(view);
  }, []);

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

  useEffect(() => {
    setTopicLibrary(null);
    setSelectedDraftSourceIds(new Set());
    setSelectionNotice(null);
    if (!authorized || !diseaseGroupId || !factorIsComplete(factor)) return;
    let cancelled = false;
    setLibraryLoading(true);
    getMedicalKnowledgeTopicSources(diseaseGroupId, factor)
      .then((library) => {
        if (!cancelled) setTopicLibrary(library);
      })
      .catch((reason) => {
        if (!cancelled) setError(medicalKnowledgeErrorMessage(reason));
      })
      .finally(() => {
        if (!cancelled) setLibraryLoading(false);
      });
    return () => { cancelled = true; };
  }, [authorized, diseaseGroupId, factor?.factor_type, factor?.factor_key, factor?.factor_value]);

  async function refreshTopicLibrary(expectedTopicKey = currentTopicKey) {
    if (!factorIsComplete(factor)) return;
    const library = await getMedicalKnowledgeTopicSources(diseaseGroupId, factor);
    if (currentTopicKeyRef.current !== expectedTopicKey) return;
    setTopicLibrary(library);
    setSelectedDraftSourceIds((current) => {
      const usableIds = new Set(
        library.sources.filter(isTopicSourceAiReadable).map((source) => source.source_id),
      );
      const next = new Set([...current].filter((sourceId) => usableIds.has(sourceId)));
      const removed = current.size - next.size;
      if (removed > 0) {
        setSelectionNotice(
          `${removed} nguồn đã được bỏ khỏi bản nháp vì AI không còn nội dung khả dụng để đọc.`,
        );
      }
      return next;
    });
  }

  function clearResearchResult() {
    setSearchResult(null);
    setSelectedImportPmids(new Set());
    setError(null);
    setSuccess(null);
  }

  function changeDiseaseGroup(value: string) {
    currentTopicKeyRef.current = factorTopicKey(value, factor);
    setDiseaseGroupId(value);
    const defaultKeyword = getDefaultPubMedDiseaseKeyword(
      options?.disease_groups.find((group) => group.id === value),
    );
    setDiseaseTerms(defaultKeyword ? [defaultKeyword] : []);
    setSelectedDraftSourceIds(new Set());
    setSelectionNotice(null);
    clearResearchResult();
  }

  function changeFactor(value: MedicalFactorSelector | null) {
    currentTopicKeyRef.current = factorTopicKey(diseaseGroupId, value);
    setFactor(value);
    setSelectedDraftSourceIds(new Set());
    setSelectionNotice(null);
    clearResearchResult();
  }

  async function runSearch() {
    if (!factorIsComplete(factor)) return;
    const requestTopicKey = currentTopicKey;
    setSearching(true);
    setError(null);
    setSuccess(null);
    setSearchResult(null);
    setSelectedImportPmids(new Set());
    try {
      const response = await searchPubMed({
        disease_group_id: diseaseGroupId,
        ...factor,
        search_mode: pubmedSearchMode,
        disease_terms: pubmedSearchMode === 'GUIDED' ? diseaseTerms : [],
        free_query: pubmedSearchMode === 'FREE' ? freeQuery : null,
        max_results: maxResults,
        year_from: yearFrom,
        year_to: yearTo,
      });
      if (currentTopicKeyRef.current !== requestTopicKey) return;
      setResultMode('keyword');
      setSearchResult(response);
    } catch (reason) {
      setError(medicalKnowledgeErrorMessage(reason));
    } finally {
      setSearching(false);
    }
  }

  async function runPmidLookup() {
    if (!factorIsComplete(factor)) return;
    const normalized = pmid.trim();
    const requestTopicKey = currentTopicKey;
    setPmidSearching(true);
    setError(null);
    setSuccess(null);
    setSearchResult(null);
    setSelectedImportPmids(new Set());
    try {
      const response = await lookupPubMedByPmid(normalized, diseaseGroupId, factor);
      if (currentTopicKeyRef.current !== requestTopicKey) return;
      setPmid(normalized);
      setResultMode('pmid');
      setSearchResult({
        disease_group_id: diseaseGroupId,
        ...factor,
        search_mode: 'GUIDED',
        query: `PMID: ${response.pmid}`,
        count: 1,
        results: [response.result],
      });
    } catch (reason) {
      setError(directPmidErrorMessage(reason));
    } finally {
      setPmidSearching(false);
    }
  }

  function togglePmid(pmid: string) {
    setSelectedImportPmids((current) => {
      const next = new Set(current);
      if (next.has(pmid)) next.delete(pmid);
      else next.add(pmid);
      return next;
    });
  }

  function toggleAll() {
    if (!searchResult) return;
    const importable = searchResult.results.filter((paper) => !paper.in_topic_library);
    const allSelected = importable.length > 0 && importable.every((paper) => selectedImportPmids.has(paper.pmid));
    setSelectedImportPmids(allSelected ? new Set() : new Set(importable.map((paper) => paper.pmid)));
  }

  async function importSelected() {
    if (!factorIsComplete(factor)) return;
    const pmids = Array.from(selectedImportPmids);
    if (pmids.length === 0) return;
    const requestTopicKey = currentTopicKey;
    setImporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await importPubMedSources(diseaseGroupId, factor, pmids);
      if (currentTopicKeyRef.current !== requestTopicKey) return;
      const byPmid = new Map(response.sources.map((source) => [source.pmid, source]));
      setSearchResult((current) => current ? {
        ...current,
        results: current.results.map((paper) => {
          const imported = byPmid.get(paper.pmid);
          return imported ? {
            ...paper,
            source_id: imported.id,
            stored_globally: true,
            in_topic_library: true,
            content_kind: imported.content_kind,
            pmcid: imported.pmcid ?? paper.pmcid,
          } : paper;
        }),
      } : current);
      setSelectedImportPmids(new Set());
      await refreshTopicLibrary(requestTopicKey);
      const parts = [`Đã thêm ${response.count} tài liệu vào kho chủ đề.`];
      if (response.created_count > 0) parts.push(`${response.created_count} tài liệu mới đã được lưu.`);
      if (response.reused_count > 0) parts.push(`${response.reused_count} tài liệu đã có sẵn nên được sử dụng lại.`);
      parts.push('Hãy chọn nguồn ở phần "Kho nguồn của chủ đề" nếu muốn AI sử dụng.');
      setSuccess(parts.join(' '));
    } catch (reason) {
      setError(medicalKnowledgeErrorMessage(reason));
    } finally {
      setImporting(false);
    }
  }

  function toggleDraftSource(sourceId: number) {
    const source = topicLibrary?.sources.find((item) => item.source_id === sourceId);
    if (!source || !isTopicSourceAiReadable(source)) return;
    setSelectedDraftSourceIds((current) => {
      const next = new Set(current);
      if (next.has(sourceId)) {
        next.delete(sourceId);
        setSelectionNotice(null);
      } else if (next.size >= MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES) {
        setSelectionNotice('Một bản nháp hiện hỗ trợ tối đa 10 nguồn.');
      } else {
        next.add(sourceId);
        setSelectionNotice(null);
      }
      return next;
    });
  }

  function selectAllUsableDraftSources() {
    const usableSources = (topicLibrary?.sources ?? []).filter(isTopicSourceAiReadable);
    setSelectedDraftSourceIds(new Set(
      usableSources
        .slice(0, MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES)
        .map((source) => source.source_id),
    ));
    setSelectionNotice(
      usableSources.length > MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES
        ? `Đã chọn 10 nguồn đầu tiên theo thứ tự trong kho. Có ${usableSources.length} nguồn AI đọc được; hãy bỏ chọn để thay nguồn nếu cần.`
        : null,
    );
  }

  const selectedDraftSources = (topicLibrary?.sources ?? []).filter((source) => (
    isTopicSourceAiReadable(source) && selectedDraftSourceIds.has(source.source_id)
  ));

  function SelectedDraftSources({ sources }: { sources: TopicSourceLibraryItem[] }) {
    return (
      <section aria-labelledby="selected-draft-sources-heading" className="rounded-2xl border border-violet-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="selected-draft-sources-heading" className="flex items-center gap-2 font-bold text-slate-950"><Sparkles size={18} className="text-violet-700" /> Nguồn AI sẽ đọc</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">Chỉ các nguồn được chọn ở đây được gửi vào lần tạo bản nháp tiếp theo.</p>
          </div>
          <span className="shrink-0 rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-800">{sources.length} / {MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES}</span>
        </div>
        {sources.length ? (
          <ul className="mt-4 space-y-2">
            {sources.map((source) => (
              <li key={source.source_id} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                <div className="min-w-0">
                  <p className="line-clamp-2 text-sm font-semibold text-slate-900">{source.title}</p>
                  <p className="mt-1 text-xs text-slate-500">{source.pmid ? `PMID ${source.pmid}` : `Source #${source.source_id}`} · {evidenceContentLabel(source.content_kind)}</p>
                </div>
                <button type="button" onClick={() => toggleDraftSource(source.source_id)} aria-label={`Bỏ nguồn ${source.pmid ?? source.title}`} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:border-red-200 hover:text-red-700"><X size={13} /> Bỏ</button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center">
            <Library size={22} className="mx-auto text-slate-400" />
            <p className="mt-2 text-sm font-semibold text-slate-700">Chưa chọn nguồn cho AI</p>
            <p className="mt-1 text-xs text-slate-500">Mở tab “Kho nguồn” và chọn từ 1 đến 10 tài liệu AI đọc được.</p>
          </div>
        )}
      </section>
    );
  }

  if (!authorized) {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        Bạn không có quyền sử dụng chức năng này.
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-5">
      <header className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-5 bg-gradient-to-r from-slate-950 via-blue-950 to-slate-900 p-5 text-white sm:p-7 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl bg-white/10 p-3 ring-1 ring-white/15"><BookOpenText size={25} /></div>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-200">Medical Knowledge Admin</p>
              <h1 className="mt-1 text-2xl font-bold sm:text-3xl">Kho kiến thức y khoa</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Hai luồng nội dung được tách rõ: kiến thức do nhân viên kiểm duyệt và kiến thức tự động chưa qua kiểm duyệt y khoa.</p>
            </div>
          </div>
          {knowledgeView === 'reviewed' && (
            <div className="grid grid-cols-2 gap-2 text-center text-xs sm:min-w-64">
              <div className="rounded-xl bg-white/10 px-3 py-2 ring-1 ring-white/10"><strong className="block text-lg text-white">{topicLibrary?.sources.length ?? 0}</strong><span className="text-slate-300">nguồn trong chủ đề</span></div>
              <div className="rounded-xl bg-white/10 px-3 py-2 ring-1 ring-white/10"><strong className="block text-lg text-white">{selectedDraftSourceIds.size}</strong><span className="text-slate-300">nguồn AI đọc</span></div>
            </div>
          )}
        </div>
        <nav aria-label="Không gian quản trị kiến thức" className="grid grid-cols-2 gap-1 border-t border-slate-200 bg-slate-50 p-1.5 sm:flex">
          {([
            ['reviewed', 'Kiến thức đã kiểm duyệt', BookCheck, 'Nghiên cứu và quản lý revision'],
            ['auto', 'Kiến thức tự động', Bot, 'Hàng đợi và nội dung chưa kiểm duyệt'],
          ] as const).map(([value, label, Icon, description]) => (
            <button key={value} type="button" aria-current={knowledgeView === value ? 'page' : undefined} onClick={() => navigateKnowledgeView(value)} className={`flex min-w-0 items-center gap-2 rounded-xl px-3 py-3 text-left transition sm:px-4 ${knowledgeView === value ? 'bg-white text-blue-800 shadow-sm ring-1 ring-slate-200' : 'text-slate-600 hover:bg-white/70 hover:text-slate-900'}`}>
              <Icon size={18} className="shrink-0" />
              <span className="min-w-0"><strong className="block truncate text-sm">{label}</strong><span className="hidden text-xs text-slate-500 md:block">{description}</span></span>
            </button>
          ))}
        </nav>
      </header>

      <details className="group rounded-2xl border border-slate-200 bg-white shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3.5 sm:px-5">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Settings2 size={17} /> Cấu hình dịch vụ <span className="hidden font-normal text-slate-500 sm:inline">· PubMed và AI draft provider</span></span>
          <ChevronDown size={17} className="text-slate-500 transition group-open:rotate-180" />
        </summary>
        <div className="border-t border-slate-200 p-3 sm:p-4"><ServiceConfigurationPanel /></div>
      </details>

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

      {knowledgeView === 'auto' ? (
        <AutoMedicalKnowledgePanel canManage={user?.role === 'admin'} />
      ) : optionsLoading ? (
        <div role="status" className="flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white p-10 text-sm text-slate-500">
          <Loader2 size={18} className="animate-spin" /> Đang tải danh mục nghiên cứu…
        </div>
      ) : options ? (
        <div className="space-y-5">
          <MedicalTopicSelector diseaseGroups={options.disease_groups} factorOptions={options.explanation_factors} diseaseGroupId={diseaseGroupId} factor={factor} onDiseaseGroupChange={changeDiseaseGroup} onFactorChange={changeFactor} />

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(420px,0.92fr)] xl:items-start">
            <section aria-labelledby="reviewed-source-workspace-heading" className="min-w-0 space-y-4">
              <div className="rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
                <div className="px-2 pb-2 pt-1">
                  <h2 id="reviewed-source-workspace-heading" className="font-bold text-slate-950">Không gian nguồn bằng chứng</h2>
                  <p className="mt-1 text-sm text-slate-500">Tìm, lưu và chủ động chọn nguồn theo từng bước.</p>
                </div>
                <div role="tablist" aria-label="Các bước quản lý nguồn" className="grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1">
                  {([
                    ['search', 'Tìm tài liệu', FileSearch],
                    ['library', 'Kho nguồn', Library],
                    ['selection', 'Nguồn AI sẽ đọc', Sparkles],
                  ] as const).map(([value, label, Icon]) => (
                    <button key={value} id={`source-tab-${value}`} type="button" role="tab" aria-selected={sourceView === value} aria-controls={`source-panel-${value}`} onClick={() => setSourceView(value)} className={`inline-flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-2 py-2.5 text-xs font-semibold transition sm:text-sm ${sourceView === value ? 'bg-white text-blue-800 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>
                      <Icon size={15} className="hidden shrink-0 sm:block" /><span className="truncate">{label}</span>{value === 'selection' && selectedDraftSourceIds.size > 0 ? <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-800">{selectedDraftSourceIds.size}</span> : null}
                    </button>
                  ))}
                </div>
              </div>

              <div className="relative">
                <div id="source-panel-search" role="tabpanel" aria-labelledby="source-tab-search" className={sourceView === 'search' ? 'space-y-4' : 'pointer-events-none absolute inset-x-0 top-0 max-h-0 overflow-hidden opacity-0'}>
                    <PubMedSearchForm
                      showTopicSelector={false}
                      diseaseGroups={options.disease_groups}
                      factorOptions={options.explanation_factors}
                      diseaseGroupId={diseaseGroupId}
                      factor={factor}
                      searchMode={pubmedSearchMode}
                      freeQuery={freeQuery}
                      diseaseTerms={diseaseTerms}
                      defaultDiseaseTerm={getDefaultPubMedDiseaseKeyword(options.disease_groups.find((group) => group.id === diseaseGroupId))}
                      maxResults={maxResults}
                      yearFrom={yearFrom}
                      yearTo={yearTo}
                      loading={searching}
                      pmid={pmid}
                      pmidLoading={pmidSearching}
                      onDiseaseGroupChange={changeDiseaseGroup}
                      onFactorChange={changeFactor}
                      onSearchModeChange={(value) => { setPubmedSearchMode(value); clearResearchResult(); }}
                      onFreeQueryChange={setFreeQuery}
                      onDiseaseTermsChange={setDiseaseTerms}
                      onMaxResultsChange={setMaxResults}
                      onYearFromChange={setYearFrom}
                      onYearToChange={setYearTo}
                      onSubmit={runSearch}
                      onPmidChange={setPmid}
                      onPmidLookup={runPmidLookup}
                    />
                    {searchResult && <PubMedResults response={searchResult} mode={resultMode} selectedPmids={selectedImportPmids} importing={importing} onToggle={togglePmid} onToggleAll={toggleAll} onImport={importSelected} />}
                </div>
                <div id="source-panel-library" role="tabpanel" aria-labelledby="source-tab-library" className={sourceView === 'library' ? '' : 'pointer-events-none absolute inset-x-0 top-0 max-h-0 overflow-hidden opacity-0'}>
                {diseaseGroupId && factorIsComplete(factor) && (
                  <MedicalTopicSourceLibrary diseaseName={options.disease_groups.find((group) => group.id === diseaseGroupId)?.name ?? diseaseGroupId} factorLabel={factorLabel(factor)} library={topicLibrary} loading={libraryLoading} selectedSourceIds={selectedDraftSourceIds} onToggle={toggleDraftSource} onSelectAllUsable={selectAllUsableDraftSources} selectionNotice={selectionNotice} />
                )}
                {(!diseaseGroupId || !factorIsComplete(factor)) && (
                  <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-12 text-center text-sm text-slate-500">Chọn đầy đủ nhóm bệnh và yếu tố để mở không gian nguồn.</div>
                )}
                </div>
                <div id="source-panel-selection" role="tabpanel" aria-labelledby="source-tab-selection" className={sourceView === 'selection' ? '' : 'pointer-events-none absolute inset-x-0 top-0 max-h-0 overflow-hidden opacity-0'}>
                  <SelectedDraftSources sources={selectedDraftSources} />
                </div>
              </div>
            </section>

            <aside aria-label="Không gian revision y khoa" className="min-w-0 xl:sticky xl:top-4">
              <div className="mb-3 flex items-center justify-between gap-3 px-1">
                <div><h2 className="font-bold text-slate-950">Revision & kiểm duyệt</h2><p className="mt-1 text-sm text-slate-500">Tạo, biên tập và quản lý vòng đời nội dung.</p></div>
                <BookCheck size={20} className="text-blue-700" />
              </div>
              {diseaseGroupId && factorIsComplete(factor) ? (
                <MedicalDraftWorkspace diseaseGroupId={diseaseGroupId} factor={factor} selectedSources={selectedDraftSources} onRemoveSelectedSource={toggleDraftSource} onInvalidSelection={() => { setSelectedDraftSourceIds(new Set()); setSelectionNotice(null); }} llmAvailable={options.llm_draft_generation_available} canApprove={user?.role === 'staff' || user?.role === 'admin'} canPublish={user?.role === 'staff' || user?.role === 'admin'} canUnpublish={user?.role === 'staff' || user?.role === 'admin'} compactSourceSummary />
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-14 text-center"><BookCheck size={25} className="mx-auto text-slate-400" /><p className="mt-3 font-semibold text-slate-700">Chưa có chủ đề để review</p><p className="mt-1 text-sm text-slate-500">Chọn nhóm bệnh và yếu tố ở phía trên để xem revision.</p></div>
              )}
            </aside>
          </div>
        </div>
      ) : null}
    </div>
  );
}
