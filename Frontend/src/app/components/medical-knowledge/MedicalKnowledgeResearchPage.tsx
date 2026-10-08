import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/app/contexts/AuthContext';
import {
  getMedicalKnowledgeOptions,
  getMedicalEvidenceProviderSettings,
  getMedicalKnowledgeTopicSources,
  importPubMedSources,
  importMedicalEvidenceProviderSources,
  lookupPubMedByPmid,
  directPmidErrorMessage,
  medicalEvidenceImportErrorMessage,
  medicalKnowledgeErrorMessage,
  searchPubMed,
  searchMedicalEvidenceProviders,
  type MedicalKnowledgeOptions,
  type DiseaseGroupOption,
  type PubMedSearchResponse,
  type MedicalEvidenceProviderSetting,
  type ReviewedProviderSearchResponse,
  type TopicSourceLibrary,
} from '@/lib/medicalKnowledgeApi';
import {
  factorIsComplete,
  factorTopicKey,
  type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeFactors';
import PubMedResults from './PubMedResults';
import PubMedSearchForm from './PubMedSearchForm';
import WhoExactLookup from './WhoExactLookup';
import MedicalTopicSelector from './MedicalTopicSelector';
import ParentReferenceCurationPanel from './ParentReferenceCurationPanel';

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

export function omitRejectedReviewedResults(
  response: ReviewedProviderSearchResponse,
): ReviewedProviderSearchResponse {
  return {
    ...response,
    results: response.results.filter((item) => item.relevance !== 'REJECT'),
    providers: response.providers.map((group) => ({
      ...group,
      results: group.results.filter((item) => item.relevance !== 'REJECT'),
    })),
  };
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
  const [maxResults, setMaxResults] = useState<10 | 15 | 20 | 25>(10);
  const [yearFrom, setYearFrom] = useState<number | null>(null);
  const [yearTo, setYearTo] = useState<number | null>(null);
  const [searchResult, setSearchResult] = useState<PubMedSearchResponse | null>(null);
  const [providerSettings, setProviderSettings] = useState<MedicalEvidenceProviderSetting[]>([]);
  const [selectedProviders, setSelectedProviders] = useState<Set<string>>(new Set(['PUBMED']));
  const [providerSearchResult, setProviderSearchResult] = useState<ReviewedProviderSearchResponse | null>(null);
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null);
  const [selectedProviderSources, setSelectedProviderSources] = useState<Set<string>>(new Set());
  const [resultMode, setResultMode] = useState<'keyword' | 'pmid'>('keyword');
  const [pmid, setPmid] = useState('');
  const [selectedImportPmids, setSelectedImportPmids] = useState<Set<string>>(new Set());
  const [topicLibrary, setTopicLibrary] = useState<TopicSourceLibrary | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [pmidSearching, setPmidSearching] = useState(false);
  const [whoExactBusy, setWhoExactBusy] = useState(false);
  const [exactLookupEpoch, setExactLookupEpoch] = useState(0);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const currentTopicKey = factorTopicKey(diseaseGroupId, factor);
  const currentTopicKeyRef = useRef(currentTopicKey);
  currentTopicKeyRef.current = currentTopicKey;

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

  useEffect(() => {
    if (!authorized) return;
    let cancelled = false;
    getMedicalEvidenceProviderSettings()
      .then((response) => {
        if (cancelled) return;
        const enabled = response.providers.filter((item) => item.workflow === 'REVIEWED' && item.enabled);
        setProviderSettings(enabled);
        setSelectedProviders((current) => {
          const available = new Set(enabled.map((item) => item.provider_id));
          const next = new Set([...current].filter((item) => available.has(item)));
          if (next.size === 0 && available.has('PUBMED')) next.add('PUBMED');
          return next;
        });
      })
      .catch(() => setProviderSettings([]));
    return () => { cancelled = true; };
  }, [authorized]);

  useEffect(() => {
    setTopicLibrary(null);
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

  }

  function clearResearchResult() {
    setExactLookupEpoch(value => value + 1);
    setSearchResult(null);
    setProviderSearchResult(null);
    setActiveProviderId(null);
    setSelectedImportPmids(new Set());
    setSelectedProviderSources(new Set());
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
    clearResearchResult();
  }

  function changeFactor(value: MedicalFactorSelector | null) {
    currentTopicKeyRef.current = factorTopicKey(diseaseGroupId, value);
    setFactor(value);
    clearResearchResult();
  }

  async function runSearch() {
    if (!factorIsComplete(factor)) return;
    setExactLookupEpoch(value => value + 1);
    const requestTopicKey = currentTopicKey;
    setSearching(true);
    setError(null);
    setSuccess(null);
    setSearchResult(null);
    setProviderSearchResult(null);
    setSelectedImportPmids(new Set());
    try {
      // Guided search always uses the provider-neutral Reviewed orchestration,
      // including a PubMed-only selection. Only PubMed FREE syntax remains on
      // the legacy endpoint because it is not a Reviewed relevance workflow.
      const useLegacyPubMed = pubmedSearchMode === 'FREE';
      if (!useLegacyPubMed) {
        const response = await searchMedicalEvidenceProviders({
          disease_group_id: diseaseGroupId,
          ...factor,
          disease_terms: diseaseTerms,
          provider_ids: [...selectedProviders],
          max_results: maxResults,
          year_from: yearFrom,
          year_to: yearTo,
        });
        if (currentTopicKeyRef.current !== requestTopicKey) return;
        setProviderSearchResult(omitRejectedReviewedResults(response));
        setSelectedProviderSources(new Set());
        setActiveProviderId(
          response.providers.find((group) => group.status !== 'PROVIDER_ERROR')?.provider_id
          ?? response.providers[0]?.provider_id
          ?? null,
        );
        return;
      }
      const response = await searchPubMed({
        disease_group_id: diseaseGroupId,
        ...factor,
        search_mode: 'FREE',
        disease_terms: [],
        free_query: freeQuery,
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

  function providerSourceKey(providerId: string, externalId: string) {
    return `${providerId}:${externalId}`;
  }

  async function importSelectedProviderSources() {
    if (!factorIsComplete(factor) || !providerSearchResult) return;
    const sources = providerSearchResult.providers.flatMap((group) => group.results)
      .filter((item) => selectedProviderSources.has(providerSourceKey(item.provider_id, item.external_id)))
      .map((item) => ({
        provider_id: item.provider_id,
        external_id: item.external_id,
        canonical_url: item.url,
        source_kind: item.source_kind,
        title: item.title,
        authors: item.authors,
        publisher_or_journal: item.publisher_or_journal,
        publication_date: item.publication_date,
        publication_year: item.publication_year,
        doi: item.doi,
      }));
    if (!sources.length) return;
    const requestTopicKey = currentTopicKey;
    setImporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await importMedicalEvidenceProviderSources(diseaseGroupId, factor, sources);
      if (currentTopicKeyRef.current !== requestTopicKey) return;
      const successful = new Map(
        response.sources
          .filter((item) => item.outcome !== 'REJECTED_INVALID' && item.outcome !== 'PROVIDER_ERROR')
          .map((item) => [providerSourceKey(item.provider_id, item.external_id), item]),
      );
      setSelectedProviderSources((current) => new Set(
        [...current].filter((key) => !successful.has(key)),
      ));
      setProviderSearchResult((current) => current ? {
        ...current,
        results: current.results.map((item) => {
          const imported = successful.get(providerSourceKey(item.provider_id, item.external_id));
          return imported ? {
            ...item,
            source_id: imported.source_id,
            in_topic_library: true,
            usable_for_draft: imported.usable_for_draft,
            usability: imported.usable_for_draft ? 'USABLE_FOR_DRAFT' : 'METADATA_ONLY',
          } : item;
        }),
        providers: current.providers.map((group) => ({
          ...group,
          results: group.results.map((item) => {
            const imported = successful.get(providerSourceKey(item.provider_id, item.external_id));
            return imported ? {
              ...item,
              source_id: imported.source_id,
              in_topic_library: true,
              usable_for_draft: imported.usable_for_draft,
              usability: imported.usable_for_draft ? 'USABLE_FOR_DRAFT' : 'METADATA_ONLY',
            } : item;
          }),
        })),
      } : current);
      if (response.count > 0) await refreshTopicLibrary(requestTopicKey);
      if (response.failed_count > 0) {
        if (response.count > 0) {
          setSuccess(`Đã thêm ${response.added_count}/${response.requested_count} tài liệu. ${response.failed_count} tài liệu không thể thêm.`);
        } else {
          setError('Không thể thêm các tài liệu đã chọn. Nguồn không hợp lệ hoặc nhà cung cấp tạm thời không khả dụng.');
        }
      } else if (response.reference_only_count > 0) {
        setSuccess(`Đã thêm ${response.added_count} tài liệu; ${response.reference_only_count} nguồn được lưu để tham khảo, chờ xem xét cho phụ huynh.`);
      } else if (response.added_count > 0) {
        setSuccess(`Đã thêm ${response.added_count} tài liệu vào kho nguồn của chủ đề.`);
      } else {
        setSuccess(`${response.already_exists_count} tài liệu đã có trong kho nguồn của chủ đề.`);
      }
    } catch (reason) {
      setError(medicalEvidenceImportErrorMessage(reason));
    } finally {
      setImporting(false);
    }
  }

  async function runPmidLookup() {
    if (!factorIsComplete(factor)) return;
    setExactLookupEpoch(value => value + 1);
    const normalized = pmid.trim();
    const requestTopicKey = currentTopicKey;
    setPmidSearching(true);
    setError(null);
    setSuccess(null);
    setSearchResult(null);
    setProviderSearchResult(null);
    setSelectedProviderSources(new Set());
    setSelectedImportPmids(new Set());
    try {
      const response = await lookupPubMedByPmid(normalized, diseaseGroupId, factor);
      if (currentTopicKeyRef.current !== requestTopicKey) return;
      if (response.pmid !== normalized || response.result.pmid !== normalized) {
        throw new Error('Exact PMID identity mismatch');
      }
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
      if (currentTopicKeyRef.current === requestTopicKey) setError(directPmidErrorMessage(reason));
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

  function toggleAllProviderGroup(providerId: string) {
    const group = providerSearchResult?.providers.find((item) => item.provider_id === providerId);
    if (!group) return;
    const importableKeys = group.results
      .filter((item) => !item.in_topic_library)
      .map((item) => providerSourceKey(item.provider_id, item.external_id));
    const allSelected = importableKeys.length > 0
      && importableKeys.every((key) => selectedProviderSources.has(key));
    setSelectedProviderSources((current) => {
      const next = new Set(current);
      for (const key of importableKeys) {
        if (allSelected) next.delete(key);
        else next.add(key);
      }
      return next;
    });
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
      parts.push('Hãy xem xét bằng chứng và điều kiện nguồn trước khi duyệt cho phụ huynh.');
      setSuccess(parts.join(' '));
    } catch (reason) {
      setError(medicalKnowledgeErrorMessage(reason));
    } finally {
      setImporting(false);
    }
  }

  const activeProviderGroup = providerSearchResult?.providers.find(
    (group) => group.provider_id === activeProviderId,
  ) ?? providerSearchResult?.providers[0] ?? null;

  if (!authorized) {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        Bạn không có quyền sử dụng chức năng này.
      </div>
    );
  }

  const searchWorkspace = options ? <section aria-label="Tìm và thêm nguồn" className="space-y-4">
    <h2 className="text-lg font-semibold text-slate-900">Tìm và thêm nguồn</h2>
    <p className="text-sm leading-6 text-slate-600">PubMed / PMC hỗ trợ nghiên cứu nội bộ Staff, không mặc định hiển thị cho phụ huynh. Chính sách nguồn được xác minh theo từng bằng chứng ở phần duyệt.</p>
    <section aria-labelledby="reviewed-provider-selector" className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 id="reviewed-provider-selector" className="text-sm font-bold text-slate-900">Nguồn tìm kiếm</h3>
      <p className="mt-1 text-xs text-slate-500">Chọn nguồn tìm kiếm đang được bật. Tài liệu tìm thấy cần được xem xét riêng trước khi hiển thị cho phụ huynh.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {providerSettings.map((setting) => {
          const checked = selectedProviders.has(setting.provider_id);
          const disabled = pubmedSearchMode === 'FREE' && setting.provider_id !== 'PUBMED';
          return (
            <label key={setting.provider_id} className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-semibold ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'} ${checked ? 'border-blue-300 bg-blue-50 text-blue-900' : 'border-slate-200 text-slate-600'}`}>
              <input type="checkbox" checked={checked && !disabled} disabled={disabled} onChange={() => {
                setSelectedProviders((current) => {
                  const next = new Set(current);
                  if (next.has(setting.provider_id)) {
                    if (next.size > 1) next.delete(setting.provider_id);
                  } else next.add(setting.provider_id);
                  return next;
                });
                clearResearchResult();
              }} />
              {setting.display_name}
            </label>
          );
        })}
      </div>
      {pubmedSearchMode === 'FREE' && <p className="mt-2 text-xs text-amber-700">Truy vấn tự do dùng cú pháp PubMed nên chỉ chạy trên PubMed.</p>}
    </section>
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
      selectedProviderCount={pubmedSearchMode === 'FREE' ? 1 : selectedProviders.size}
      yearFrom={yearFrom}
      yearTo={yearTo}
      loading={searching || whoExactBusy}
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
    {factorIsComplete(factor) && providerSettings.some(item => item.provider_id === 'WHO' && item.workflow === 'REVIEWED' && item.enabled) && (
      <WhoExactLookup key={`${currentTopicKey}:${exactLookupEpoch}`}
        diseaseGroupId={diseaseGroupId} factor={factor}
        disabled={searching || pmidSearching || importing}
        onBusyChange={setWhoExactBusy}
        onStart={() => { setSearchResult(null); setProviderSearchResult(null); setSelectedImportPmids(new Set()); setSelectedProviderSources(new Set()); setError(null); setSuccess(null); }}
        onImported={() => refreshTopicLibrary()}
      />
    )}
    {searchResult && <PubMedResults response={searchResult} mode={resultMode} selectedPmids={selectedImportPmids} importing={importing} onToggle={togglePmid} onToggleAll={toggleAll} onImport={importSelected} />}
    {providerSearchResult && (
      <section aria-labelledby="provider-search-results" className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h3 id="provider-search-results" className="font-bold text-slate-900">Kết quả theo nguồn</h3><p className="mt-1 text-xs text-slate-500">{providerSearchResult.count} kết quả · {providerSearchResult.unique_count} bằng chứng duy nhất</p></div>
          <span className="rounded-md bg-blue-50 px-3 py-1 text-sm font-semibold text-blue-800">Đã chọn {selectedProviderSources.size} tài liệu</span>
        </div>
        <div role="tablist" aria-label="Kết quả theo nguồn" className="mt-4 flex gap-2 overflow-x-auto border-b border-slate-200 pb-2">
          {providerSearchResult.providers.map((group) => {
            const selectedInGroup = group.results.filter((item) => selectedProviderSources.has(providerSourceKey(item.provider_id, item.external_id))).length;
            const statusLabel = group.status === 'PROVIDER_ERROR'
              ? 'Tạm thời không khả dụng'
              : `${group.returned_count} kết quả phù hợp${group.warning ? ' · một lượt tìm bị lỗi' : ''}`;
            return (
              <button key={group.provider_id} type="button" role="tab" aria-selected={activeProviderGroup?.provider_id === group.provider_id} onClick={() => setActiveProviderId(group.provider_id)} className={`min-w-fit rounded-lg px-3 py-2 text-left text-sm transition ${activeProviderGroup?.provider_id === group.provider_id ? 'bg-blue-700 text-white ' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
                <span className="block font-bold">{group.display_name}</span>
                <span className={`block text-xs ${activeProviderGroup?.provider_id === group.provider_id ? 'text-blue-100' : group.status === 'PROVIDER_ERROR' ? 'text-amber-700' : 'text-slate-500'}`}>{statusLabel}{selectedInGroup > 0 ? ` · ${selectedInGroup} đã chọn` : ''}</span>
              </button>
            );
          })}
        </div>
        {activeProviderGroup && (
          <div role="tabpanel" aria-label={activeProviderGroup.display_name} className="mt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
              <span>Yêu cầu {activeProviderGroup.requested_count} · {activeProviderGroup.direct_count} trực tiếp · {activeProviderGroup.related_count} liên quan</span>
              {activeProviderGroup.status === 'SUCCESS' && activeProviderGroup.results.some((item) => !item.in_topic_library) && (
                <button type="button" onClick={() => toggleAllProviderGroup(activeProviderGroup.provider_id)} className="font-semibold text-blue-700">Chọn tất cả trong {activeProviderGroup.display_name}</button>
              )}
            </div>
            {activeProviderGroup.status === 'PROVIDER_ERROR' && (
              <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-5 text-sm text-amber-900"><strong>{activeProviderGroup.display_name}</strong> — Tạm thời không khả dụng; kết quả từ nguồn khác vẫn được giữ.</p>
            )}
            {activeProviderGroup.status === 'NO_RESULTS' && (
              <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-600">
                {activeProviderGroup.provider_id === 'WHO'
                  ? `Đã kiểm tra ${activeProviderGroup.raw_candidates_examined} kết quả WHO nhưng chưa tìm thấy tài liệu đồng thời phù hợp với bệnh và yếu tố.`
                  : 'Không tìm thấy tài liệu phù hợp từ nguồn này.'}
              </p>
            )}
            {activeProviderGroup.warning && activeProviderGroup.status !== 'PROVIDER_ERROR' && (
              <p role="status" className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Một lượt tìm mở rộng tạm thời không khả dụng; các kết quả đã tìm thấy vẫn được giữ.</p>
            )}
            {activeProviderGroup.status === 'SUCCESS' && <div className="space-y-3">
          {activeProviderGroup.results.map((item) => {
            const key = providerSourceKey(item.provider_id, item.external_id);
            const savedLabel = item.in_topic_library
              ? item.usable_for_draft
                ? 'Đã có trong kho chủ đề'
                : 'Đã lưu để tham khảo'
              : item.usable_for_draft
                ? 'Có nội dung tham khảo'
                : 'Chỉ metadata · lưu để tham khảo';
            return (
              <label key={key} className={`flex items-start gap-3 rounded-xl border border-slate-200 p-3 ${item.in_topic_library ? 'cursor-default bg-slate-50' : 'cursor-pointer hover:border-blue-300'}`}>
                <input type="checkbox" className="mt-1" disabled={item.in_topic_library} checked={item.in_topic_library || selectedProviderSources.has(key)} onChange={() => setSelectedProviderSources((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; })} />
                <span className="min-w-0"><span className="block font-semibold text-slate-900 [overflow-wrap:anywhere]">{item.title}</span><span className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500"><span>{item.source_kind}</span>{item.publisher_or_journal && <span>{item.publisher_or_journal}</span>}{item.publication_year && <span>Năm {item.publication_year}</span>}</span><span className="mt-2 flex flex-wrap gap-2"><span className="inline-flex rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{item.relevance === 'DIRECT_TOPIC' ? 'Bằng chứng trực tiếp' : 'Tài liệu liên quan'}</span><span className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${item.in_topic_library ? 'bg-blue-100 text-blue-800' : 'bg-slate-100 text-slate-700'}`}>{savedLabel}</span></span><a href={item.url} aria-label={`Xem nguồn: ${item.title} (mở tab mới)`} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm text-blue-700 underline">Xem nguồn</a></span>
              </label>
            );
          })}
            </div>}
            <details className="mt-4 rounded-lg border border-slate-200 bg-slate-50 text-xs text-slate-600">
              <summary className="cursor-pointer px-3 py-2 font-semibold text-slate-700">Chi tiết kỹ thuật tìm kiếm</summary>
              <div className="space-y-2 border-t border-slate-200 px-3 py-3">
                <p>Provider: {activeProviderGroup.display_name} · Đã gọi: {activeProviderGroup.provider_invoked ? 'có' : 'không'} · Trạng thái provider: {activeProviderGroup.provider_status}</p>
                <p>Mục tiêu phù hợp {activeProviderGroup.requested_relevant_count} · tổng từ nhà cung cấp {activeProviderGroup.provider_total_available ?? 'không rõ'} · số trang {activeProviderGroup.pages_fetched} · đã kiểm tra {activeProviderGroup.raw_candidates_examined} · chuẩn hóa {activeProviderGroup.normalized_candidates} · trực tiếp {activeProviderGroup.direct_count} · liên quan {activeProviderGroup.related_count} · loại {activeProviderGroup.rejected_count} · trả về {activeProviderGroup.returned_count}</p>
                <p>Lý do dừng: <code>{activeProviderGroup.stop_reason}</code> · hết dữ liệu nhà cung cấp: {activeProviderGroup.provider_exhausted ? 'có' : 'không'} · hết ngân sách: {activeProviderGroup.budget_exhausted ? 'có' : 'không'}</p>
                {activeProviderGroup.budget_exhausted && <p>Đã dừng khi đạt ngân sách ứng viên an toàn.</p>}
                {activeProviderGroup.warning && <p>Mã lỗi an toàn: <code>{activeProviderGroup.warning.code}</code></p>}
                <ol className="space-y-2">
                  {activeProviderGroup.query_attempts.map((attempt) => (
                    <li key={`${attempt.level}:${attempt.query}`}><strong>{attempt.level}</strong> · {attempt.status} · trang {attempt.pages_fetched} · tìm thấy {attempt.provider_match_count} · lấy {attempt.fetched_count} · chuẩn hóa {attempt.normalized_count} · trực tiếp {attempt.direct_count} · liên quan {attempt.related_count} · loại {attempt.rejected_count} · dừng <code>{attempt.stop_reason}</code>{attempt.warning && <> · lỗi <code>{attempt.warning.code}</code></>}<details className="mt-1"><summary className="cursor-pointer">Xem truy vấn</summary><code className="mt-1 block whitespace-pre-wrap break-words rounded bg-white p-2">{attempt.query}</code></details></li>
                  ))}
                </ol>
              </div>
            </details>
          </div>
        )}
        <button type="button" disabled={importing || selectedProviderSources.size === 0} onClick={() => void importSelectedProviderSources()} className="mt-4 rounded-lg bg-blue-800 px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-50">{importing ? 'Đang thêm…' : `Thêm ${selectedProviderSources.size} nguồn vào danh sách xem xét`}</button>
      </section>
    )}
  </section> : null;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 text-slate-900">
      <header className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-semibold">Nguồn tham khảo tin cậy</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Quản lý tài liệu đọc thêm dành cho phụ huynh. Các nguồn này độc lập với kết quả và giải thích của mô hình.</p>
      </header>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 [overflow-wrap:anywhere]">{error}</p>}
      {success && <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">{success}</p>}
      {optionsLoading ? <p role="status" className="flex items-center gap-2 text-sm text-slate-600"><Loader2 size={16} className="animate-spin" /> Đang tải danh mục tham khảo…</p> : options ? <>
        <MedicalTopicSelector referenceMode diseaseGroups={options.disease_groups} factorOptions={options.explanation_factors} diseaseGroupId={diseaseGroupId} factor={factor} onDiseaseGroupChange={changeDiseaseGroup} onFactorChange={changeFactor} />
        {diseaseGroupId && factorIsComplete(factor) ? (
          <ParentReferenceCurationPanel diseaseGroupId={diseaseGroupId} factor={factor} library={topicLibrary} loading={libraryLoading}>{searchWorkspace}</ParentReferenceCurationPanel>
        ) : <>
          <section aria-label="Nguồn đang hiển thị cho phụ huynh" className="border-b border-slate-200 pb-5"><h2 className="text-lg font-semibold">Nguồn đang hiển thị cho phụ huynh</h2><p className="mt-2 text-sm text-slate-600">Chọn đầy đủ ngữ cảnh để xem các nguồn đã duyệt.</p></section>
          {searchWorkspace}
          <section aria-label="Nguồn chờ duyệt / quản lý curation"><h2 className="text-lg font-semibold">Nguồn chờ duyệt / quản lý curation</h2><p className="mt-2 text-sm text-slate-600">Chọn đầy đủ nhóm bệnh và yếu tố để quản lý nguồn.</p></section>
        </>}
      </> : null}
    </div>
  );
}
