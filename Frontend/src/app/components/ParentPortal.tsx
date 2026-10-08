import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Droplets,
  Loader2,
  LocateFixed,
  MapPin,
  Search,
  Thermometer,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import {
  HospitalBrandBadge,
  ParentBrandFooter,
} from './ParentPortalDecor';
import * as api from '@/lib/api';
import { fuzzyMatch, splitDiseaseLabel } from '@/lib/disease';
import {
  WeatherAIDisclaimer,
  WeatherAILoadingNotice,
} from './weather-ai/WeatherAIResults';
import { ParentResultNavigator } from './parent/ParentResultNavigator';
import { buildTrustedReferenceSelectors, matchTrustedReferenceItems } from './weather-ai/trustedReferences';

function normalize(text: string) {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd');
}
function splitText(value?: string | null): string[] {
  if (typeof value !== 'string' || !value.trim()) return [];
  return value
    .split(/\n|;|•|-/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function findKnowledge(diseaseName: string, rows: api.DiseaseKnowledgeRow[], t: TFunction) {
  // The model can return bilingual names while care guidance stores the Vietnamese group.
  const groupLabel = normalize(splitDiseaseLabel(diseaseName).vi);
  const direct = rows.find((row) => normalize(splitDiseaseLabel(row.disease_group).vi) === groupLabel)
    ?? rows.find((row) => fuzzyMatch(`${row.disease_group} ${row.title}`, diseaseName));
  if (direct) {
    return {
      symptoms: splitText(direct.symptoms),
      warning: direct.warning_signs || t('parent.knowledge.defaultWarning'),
      prevention: splitText(direct.prevention),
      source: direct.source || t('parent.knowledge.internalSource'),
    };
  }
  return {
    symptoms: [],
    warning: t('parent.knowledge.noWarning'),
    prevention: [],
    source: t('parent.knowledge.noSource'),
  };
}

function formatNum(v: unknown, digits = 1) {
  if (typeof v !== 'number' || Number.isNaN(v)) return '-';
  return v.toFixed(digits).replace(/\.0$/, '');
}

function displayOption(value: string, t: TFunction) {
  if (value === 'Nam') return t('parent.gender.male');
  if (value === 'Nữ' || value === 'Nu') return t('parent.gender.female');
  if (value === 'Khác') return t('parent.gender.other');
  if (value === 'Không rõ') return t('common.unknown');
  return value
    .replace(/Dưới 1 tuổi/gi, t('parent.age.underOne'))
    .replace(/Trên 15 tuổi/gi, t('parent.age.overFifteen'))
    .replace(/tuổi/gi, t('parent.age.yearSuffix'));
}

type LocationMode = 'gps' | 'manual';

function useVietnameseT(): TFunction {
  const { i18n } = useTranslation();
  return useMemo(() => i18n.getFixedT('vi'), [i18n]) as TFunction;
}

function distanceKm(a: { latitude: number; longitude: number }, b: { latitude: number; longitude: number }) {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const earthRadiusKm = 6371;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusKm * Math.asin(Math.sqrt(h));
}

function nearestProvince(
  point: { latitude: number; longitude: number },
  provinces: api.AreaOption[],
) {
  return provinces
    .filter((item) => typeof item.latitude === 'number' && typeof item.longitude === 'number')
    .map((item) => ({
      item,
      distance: distanceKm(point, {
        latitude: item.latitude as number,
        longitude: item.longitude as number,
      }),
    }))
    .sort((a, b) => a.distance - b.distance)[0] ?? null;
}

export default function ParentPortal() {
  const t = useVietnameseT();
  const [provinces, setProvinces] = useState<api.AreaOption[]>([]);
  const [knowledge, setKnowledge] = useState<api.DiseaseKnowledgeRow[]>([]);
  const [options, setOptions] = useState<api.WeatherAIOptions | null>(null);
  const [provinceCode, setProvinceCode] = useState('');
  const [provinceSearch, setProvinceSearch] = useState('');
  const [provinceOpen, setProvinceOpen] = useState(false);
  const [locationMode, setLocationMode] = useState<LocationMode>('manual');
  const [locatedProvinceCode, setLocatedProvinceCode] = useState('');
  const [locationMessage, setLocationMessage] = useState<string | null>(null);
  const [ageGroup, setAgeGroup] = useState('');
  const [gender, setGender] = useState('');
  const [topK, setTopK] = useState(5);
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiResult, setAiResult] = useState<api.WeatherAIPredictResponse | null>(null);
  const [localRisks, setLocalRisks] = useState<api.AreaLocalRisk[]>([]);
  const [recommendations, setRecommendations] = useState<string[]>([]);
  const [trustedReferences, setTrustedReferences] = useState<api.TrustedReferenceItem[]>([]);
  const predictionRequestId = useRef(0);
  const referenceRequestId = useRef(0);
  const locationModeRef = useRef(locationMode);

  useLayoutEffect(() => { locationModeRef.current = locationMode; }, [locationMode]);

  useEffect(() => () => {
    predictionRequestId.current += 1;
    referenceRequestId.current += 1;
  }, []);

  const clearResults = useCallback(() => {
    // Context changes retire the whole prediction, including its error/loading updates.
    predictionRequestId.current += 1;
    referenceRequestId.current += 1;
    setLoading(false);
    setError(null);
    setTrustedReferences([]);
    setAiResult(null);
    setLocalRisks([]);
    setRecommendations([]);
  }, []);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const previousTheme = root.dataset.theme;
    const hadDarkClass = root.classList.contains('dark');

    root.classList.remove('dark');
    root.dataset.theme = 'parent';

    return () => {
      if (hadDarkClass) root.classList.add('dark');
      else root.classList.remove('dark');

      if (previousTheme) root.dataset.theme = previousTheme;
      else delete root.dataset.theme;
    };
  }, []);

  useEffect(() => {
    const previousLang = document.documentElement.lang;
    document.documentElement.lang = 'vi';
    return () => {
      document.documentElement.lang = previousLang;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setInitialLoading(true);
    Promise.all([
      api.listAreaProvinces(),
      api.getPublicWeatherAIOptions(),
      api.getPublicDiseaseKnowledge().catch(() => [] as api.DiseaseKnowledgeRow[]),
    ])
      .then(([provinceRows, optionRows, knowledgeRows]) => {
        if (!alive) return;
        setProvinces(provinceRows);
        setOptions(optionRows);
        setKnowledge(knowledgeRows);
        setAgeGroup(optionRows.age_groups?.[0] ?? '');
        setGender(optionRows.genders?.includes('Nam') ? 'Nam' : optionRows.genders?.[0] ?? '');
      })
      .catch((e) => setError(api.weatherAIErrorMessage(e)))
      .finally(() => {
        if (alive) setInitialLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const activeProvinceCode = locationMode === 'gps' ? locatedProvinceCode : provinceCode;

  const selectedProvince = useMemo(
    () => provinces.find((item) => item.code === activeProvinceCode) ?? null,
    [provinces, activeProvinceCode],
  );

  const filteredProvinces = useMemo(() => {
    const q = provinceSearch.trim();
    if (!q) return provinces;
    return provinces.filter((item) => fuzzyMatch(item.name, q));
  }, [provinces, provinceSearch]);

  const requestLocation = useCallback(() => {
    clearResults();
    setLocationMode('gps');
    setLocationMessage(null);
    if (!navigator.geolocation) {
      setError(t('parent.error.geolocationUnsupported'));
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (locationModeRef.current === 'gps') clearResults();
        const nextCoords = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
        };
        const nearest = nearestProvince(nextCoords, provinces);
        setCoords(nextCoords);
        if (nearest) {
          setLocatedProvinceCode(nearest.item.code);
          setLocationMessage(t('parent.location.nearest', { area: nearest.item.name }));
        } else {
          setLocatedProvinceCode('');
          setLocationMessage(
            t('parent.location.coordsOnly', {
              latitude: nextCoords.latitude.toFixed(4),
              longitude: nextCoords.longitude.toFixed(4),
            }),
          );
        }
        setLocating(false);
      },
      () => {
        if (locationModeRef.current === 'gps') clearResults();
        setCoords(null);
        setLocatedProvinceCode('');
        setLocationMessage(t('parent.location.deniedMessage'));
        setError(t('parent.error.locationDenied'));
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 600000 },
    );
  }, [clearResults, provinces, t]);

  const run = useCallback(async () => {
    if (!ageGroup || !gender) {
      setError(t('parent.error.missingChildInfo'));
      return;
    }

    if (locationMode === 'manual' && !provinceCode) {
      setError(t('parent.error.missingProvince'));
      return;
    }
    if (locationMode === 'gps' && !coords) {
      setError(t('parent.error.missingGps'));
      return;
    }

    const requestId = ++predictionRequestId.current;
    setLoading(true);
    setError(null);
    const referenceId = ++referenceRequestId.current;
    setTrustedReferences([]);
    const weatherLatitude =
      locationMode === 'gps'
        ? coords?.latitude
        : typeof selectedProvince?.latitude === 'number'
          ? selectedProvince.latitude
          : undefined;
    const weatherLongitude =
      locationMode === 'gps'
        ? coords?.longitude
        : typeof selectedProvince?.longitude === 'number'
          ? selectedProvince.longitude
          : undefined;

    if (weatherLatitude === undefined || weatherLongitude === undefined) {
      setLoading(false);
      setError(
        locationMode === 'manual'
          ? t('parent.error.provinceNoCoords')
          : t('parent.error.noRealtimeCoords'),
      );
      return;
    }

    try {
      const weatherRows = await api.predictPublicParentRisk({
        age_group: ageGroup,
        gender,
        top_k: topK,
        latitude: weatherLatitude,
        longitude: weatherLongitude,
        timezone: 'Asia/Ho_Chi_Minh',
      });
      if (predictionRequestId.current !== requestId) return;

      const [risks, rec] = await Promise.all([
        api.getAreaLocalRisks({ provinceCode: activeProvinceCode || undefined, limit: topK }),
        api.getAreaRecommendations({ provinceCode: activeProvinceCode || undefined }).catch(() => null),
      ]);
      if (predictionRequestId.current !== requestId) return;
      setAiResult(weatherRows);
      setLocalRisks(risks);
      setRecommendations(rec?.recommendations ?? []);

      const referenceSelectors = buildTrustedReferenceSelectors(weatherRows);
      if (referenceSelectors.length > 0 && referenceRequestId.current === referenceId) {
        void api.getPublicTrustedReferences(referenceSelectors)
          .then((response) => {
            if (referenceRequestId.current === referenceId) {
              setTrustedReferences(matchTrustedReferenceItems(response.items, referenceSelectors));
            }
          })
          .catch(() => {
            if (referenceRequestId.current === referenceId) setTrustedReferences([]);
          });
      }

    } catch (e) {
      if (predictionRequestId.current === requestId) setError(api.weatherAIErrorMessage(e));
    } finally {
      if (predictionRequestId.current === requestId) setLoading(false);
    }
  }, [activeProvinceCode, ageGroup, gender, topK, coords, locationMode, provinceCode, selectedProvince, t]);

  const combinedRisks = useMemo(() => {
    const areaMap = new Map(localRisks.map((row) => [normalize(row.disease_group), row]));
    return (aiResult?.predictions ?? aiResult?.top_risks ?? []).map((row) => {
      const area = areaMap.get(normalize(row.disease_name));
      return {
        ...row,
        localCases: area?.recent_cases ?? null,
        localRisk: area?.['risk_level'] ?? null,
        localPeriodFrom: area?.period_from ?? null,
        localPeriodTo: area?.period_to ?? null,
        knowledge: findKnowledge(row.disease_name, knowledge, t),
        trustedReferences: matchTrustedReferenceItems(trustedReferences, buildTrustedReferenceSelectors({
          ...aiResult!, predictions: [row], top_risks: [row],
        })),
      };
    });
  }, [aiResult, localRisks, knowledge, trustedReferences, t]);

  const hasResults = combinedRisks.length > 0;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <header className="mb-8">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
            <HospitalBrandBadge />
          </div>
          <h1 className="mt-6 text-2xl font-semibold leading-tight sm:text-3xl">Đánh giá nguy cơ bệnh theo thời tiết</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Kết quả tham khảo dựa trên mô hình và điều kiện thời tiết hiện tại.</p>
        </header>

        <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6" aria-label="Thông tin đầu vào">
          <h2 className="mb-5 text-base font-semibold">Thông tin trẻ và vị trí</h2>
          <div className="grid gap-6 md:grid-cols-2 md:gap-8">
            <section className="min-w-0 space-y-4" aria-labelledby="parent-child-heading">
              <h3 id="parent-child-heading" className="text-base font-semibold">Thông tin của trẻ</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t('parent.child.age')} htmlFor="parent-age">
                  <select
                    id="parent-age"
                    value={ageGroup}
                    onChange={(e) => { clearResults(); setAgeGroup(e.target.value); }}
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                  >
                    {(options?.age_groups ?? []).map((item) => (
                      <option key={item} value={item}>{displayOption(item, t)}</option>
                    ))}
                  </select>
                </Field>
                <Field label={t('parent.child.gender')} htmlFor="parent-gender">
                  <select
                    id="parent-gender"
                    value={gender}
                    onChange={(e) => { clearResults(); setGender(e.target.value); }}
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                  >
                    {(options?.genders ?? []).map((item) => (
                      <option key={item} value={item}>{displayOption(item, t)}</option>
                    ))}
                  </select>
                </Field>
              </div>

              <Field label={t('parent.display.label')} htmlFor="parent-top-k">
                <select
                  id="parent-top-k"
                  value={topK}
                  onChange={(e) => { clearResults(); setTopK(Number(e.target.value)); }}
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                >
                  {[5, 10, 20].map((n) => (
                    <option key={n} value={n}>{t('parent.display.top', { count: n })}</option>
                  ))}
                </select>
              </Field>
            </section>
            <section className="min-w-0 space-y-4 border-t border-slate-200 pt-5 md:border-l md:border-t-0 md:pl-8 md:pt-0" aria-labelledby="parent-location-heading">
              <h3 id="parent-location-heading" className="text-base font-semibold">Khu vực / vị trí</h3>
              <div className="space-y-3">
                <fieldset className="min-w-0 space-y-2">
                  <legend className="text-sm font-medium text-slate-700">{t('parent.location.chooseMode')}</legend>
                  <div className="grid grid-cols-2 gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
                    <button
                      type="button"
                      aria-pressed={locationMode === 'gps'}
                      onClick={() => {
                        clearResults();
                        setLocationMode('gps');
                        if (!coords) requestLocation();
                      }}
                      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors ${
                        locationMode === 'gps' ? 'bg-white text-teal-800 ring-1 ring-slate-200' : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      <LocateFixed size={16} />
                      {t('parent.location.useGps')}
                    </button>
                    <button
                      type="button"
                      aria-pressed={locationMode === 'manual'}
                      onClick={() => {
                        clearResults();
                        setLocationMode('manual');
                        setProvinceOpen(true);
                      }}
                      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors ${
                        locationMode === 'manual' ? 'bg-white text-teal-800 ring-1 ring-slate-200' : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      <MapPin size={16} />
                      {t('parent.location.manual')}
                    </button>
                  </div>
                </fieldset>

                {locationMode === 'manual' ? (
                  <Field label={t('parent.location.province')} htmlFor="parent-province">
                    <ProvinceCombobox
                      open={provinceOpen}
                      setOpen={setProvinceOpen}
                      search={provinceSearch}
                      setSearch={setProvinceSearch}
                      value={provinceCode}
                      provinces={filteredProvinces}
                      selectedName={selectedProvince?.name}
                      onSelect={(code) => {
                        clearResults();
                        setProvinceCode(code);
                        setProvinceOpen(false);
                      }}
                    />
                  </Field>
                ) : (
                  <div className="border-l-2 border-slate-200 pl-3 text-sm text-slate-700">
                    <div className="flex items-start gap-2">
                      {coords ? <CheckCircle2 size={17} className="mt-0.5 shrink-0" /> : <LocateFixed size={17} className="mt-0.5 shrink-0" />}
                      <div className="min-w-0 flex-1">
                        <p className="font-bold">
                          {locating ? t('parent.location.loading') : locationMessage ?? t('parent.location.prompt')}
                        </p>
                        {coords && (
                          <p className="mt-1 text-sm text-slate-500">
                            {t('parent.location.coords', { latitude: coords.latitude.toFixed(4), longitude: coords.longitude.toFixed(4) })}
                          </p>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={requestLocation}
                      disabled={locating}
                      className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-teal-800 hover:bg-slate-50 disabled:opacity-60"
                    >
                      {locating ? <Loader2 className="animate-spin" size={16} /> : <LocateFixed size={16} />}
                      {coords ? t('parent.location.retryGps') : t('parent.location.getGps')}
                    </button>
                  </div>
                )}
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-slate-100 pt-4">
                <p className="text-sm text-slate-600">{t('parent.weather.title')}</p>
                <WeatherTile icon={Thermometer} label={t('parent.weather.temperature')} value={`${formatNum(aiResult?.weather?.features?.temperature_mean_current)}°C`} />
                <WeatherTile icon={Droplets} label={t('parent.weather.humidity')} value={`${formatNum(aiResult?.weather?.features?.humidity_mean_current)}%`} />
              </div>
            </section>
          </div>
          <div className="mt-6 border-t border-slate-200 pt-5">
            <div className="flex flex-col justify-end gap-2 sm:flex-row">
              <button
                data-testid="parent-predict-submit"
                onClick={run}
                disabled={loading || initialLoading}
                className="inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-teal-700 px-6 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:opacity-60"
              >
                {loading || initialLoading ? <Loader2 className="animate-spin" size={17} /> : null}
                {t('parent.actions.viewResults')}
              </button>
            </div>
          </div>

          {error && (
            <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              <AlertTriangle size={18} className="shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{error}</span>
            </div>
          )}
          {loading && <WeatherAILoadingNotice variant="parent" />}
        </section>

        <section className="mt-8" aria-label="Kết quả phân tích">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xl font-semibold">Kết quả phân tích</h2>
            <p className="text-sm text-slate-500">{selectedProvince?.name ?? t('parent.location.notSelected')}</p>
          </div>
          <p className="mb-4 text-sm text-slate-500">
            {t('parent.results.weatherAi')} · {t('parent.results.areaData')}
            {Boolean(aiResult?.weather?.features?.season) && <> · {String(aiResult?.weather?.features?.season)}</>}
          </p>
          {!hasResults ? (
            <EmptyState loading={loading || initialLoading} />
          ) : (
            <ParentResultNavigator rows={combinedRisks} result={aiResult!} />
          )}
        </section>

        <aside className="mt-8 grid gap-6 border-t border-slate-200 pt-6 sm:grid-cols-2">
          <section>
            <h2 className="text-base font-semibold">{t('parent.recommendations.title')}</h2>
            {recommendations.length ? (
              <ol className="mt-3 list-decimal space-y-3 pl-5 text-sm leading-6 text-slate-700">
                {recommendations.map((item, index) => <li key={`${item}-${index}`} className="pl-1">{item}</li>)}
              </ol>
            ) : <p className="mt-3 text-sm leading-6 text-slate-500">{t('parent.recommendations.empty')}</p>}
          </section>
          <section>
            <h2 className="text-base font-semibold">{t('parent.note.title')}</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">{t('parent.note.body')}</p>
          </section>
        </aside>
        {hasResults && <WeatherAIDisclaimer disclaimer={aiResult?.disclaimer} variant="parent" />}
        <ParentBrandFooter />
      </main>
    </div>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">{label}</label>
      {children}
    </div>
  );
}

function WeatherTile({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon size={16} aria-hidden="true" className="shrink-0 text-slate-400" />
      <span className="text-slate-600">{label}</span>
      <span className="font-medium tabular-nums text-slate-900">{value}</span>
    </div>
  );
}

function ProvinceCombobox({
  open,
  setOpen,
  search,
  setSearch,
  value,
  provinces,
  selectedName,
  onSelect,
}: {
  open: boolean;
  setOpen: (value: boolean) => void;
  search: string;
  setSearch: (value: string) => void;
  value: string;
  provinces: api.AreaOption[];
  selectedName?: string;
  onSelect: (code: string) => void;
}) {
  const t = useVietnameseT();

  return (
    <div className="relative">
      <button
        id="parent-province"
        data-testid="province-combobox-trigger"
        type="button"
        aria-expanded={open}
        aria-controls={open ? 'parent-province-panel' : undefined}
        onClick={() => setOpen(!open)}
        className={`flex h-12 w-full items-center justify-between gap-3 rounded-lg border bg-white px-3 text-left text-sm outline-none transition-colors ${
          value ? 'border-slate-300 text-slate-900' : 'border-slate-300 text-slate-500'
        } focus:border-teal-600 focus:ring-2 focus:ring-teal-100`}
      >
        <span className="truncate font-semibold">{selectedName ?? t('parent.location.selectProvince')}</span>
        <ChevronDown size={17} className={`shrink-0 text-slate-500 transition ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div id="parent-province-panel" className="mt-2 rounded-lg border border-slate-200 bg-white p-2">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <label htmlFor="parent-province-search" className="sr-only">{t('parent.location.searchProvince')}</label>
            <input
              id="parent-province-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              placeholder={t('parent.location.searchProvince')}
              className="h-12 w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            />
          </div>
          <div className="mt-2 max-h-56 overflow-auto">
            {provinces.length === 0 ? (
              <p className="px-3 py-4 text-center text-sm text-slate-500">{t('parent.location.noProvinceMatch')}</p>
            ) : (
              provinces.map((item) => (
                <button
                  key={item.code}
                  type="button"
                  aria-pressed={item.code === value}
                  onClick={() => {
                    onSelect(item.code);
                    setSearch('');
                  }}
                  className={`flex w-full items-center justify-between min-h-11 rounded-md px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                    item.code === value ? 'bg-teal-50 font-semibold text-teal-800' : 'font-medium text-slate-700'
                  }`}
                >
                  <span>{item.name}</span>
                  {item.code === value && <CheckCircle2 size={15} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
function EmptyState({ loading }: { loading: boolean }) {
  const t = useVietnameseT();

  return (
    <div className="flex min-h-32 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm leading-6 text-slate-500">
      {loading ? (
        <span className="inline-flex items-center gap-2">
          {t('parent.results.loading')}
        </span>
      ) : (
        t('parent.results.empty')
      )}
    </div>
  );
}
