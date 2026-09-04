import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  Baby,
  CheckCircle2,
  ChevronDown,
  Droplets,
  HeartPulse,
  Loader2,
  LocateFixed,
  MapPin,
  Search,
  ShieldCheck,
  Sparkles,
  Thermometer,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import {
  DecorativeBackground,
  HospitalBrandBadge,
  ParentBrandFooter,
  PersonalBrandBadge,
} from './ParentPortalDecor';
import * as api from '@/lib/api';
import { fuzzyMatch } from '@/lib/disease';
import {
  WeatherAIDisclaimer,
  WeatherAILoadingNotice,
} from './weather-ai/WeatherAIResults';
import { buildPublishedMedicalKnowledgeSelectors } from './weather-ai/publishedMedicalKnowledge';
import { ParentDiseaseCard } from './parent/ParentDiseaseCard';

function normalize(text: string) {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd');
}
function splitText(value?: string | null): string[] {
  if (!value) return [];
  return value
    .split(/\n|;|•|-/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function findKnowledge(diseaseName: string, rows: api.DiseaseKnowledgeRow[], t: TFunction) {
  const direct = rows.find((row) => fuzzyMatch(`${row.disease_group} ${row.title}`, diseaseName));
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
  const [publishedMedicalKnowledge, setPublishedMedicalKnowledge] = useState<api.PublishedMedicalKnowledgeItem[]>([]);
  const [tier2Loading, setTier2Loading] = useState(false);
  const [tier2LoadingDiseaseIds, setTier2LoadingDiseaseIds] = useState<string[]>([]);
  const tier2RequestId = useRef(0);

  const clearResults = useCallback(() => {
    tier2RequestId.current += 1;
    setAiResult(null);
    setLocalRisks([]);
    setRecommendations([]);
    setPublishedMedicalKnowledge([]);
    setTier2Loading(false);
    setTier2LoadingDiseaseIds([]);
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

    setLoading(true);
    setError(null);
    tier2RequestId.current += 1;
    setPublishedMedicalKnowledge([]);
    setTier2Loading(false);
    setTier2LoadingDiseaseIds([]);
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

      const [risks, rec] = await Promise.all([
        api.getAreaLocalRisks({ provinceCode: activeProvinceCode || undefined, limit: topK }),
        api.getAreaRecommendations({ provinceCode: activeProvinceCode || undefined }).catch(() => null),
      ]);
      setAiResult(weatherRows);
      setLocalRisks(risks);
      setRecommendations(rec?.recommendations ?? []);

      const selectors = buildPublishedMedicalKnowledgeSelectors(weatherRows);
      if (selectors.length > 0) {
        const requestId = ++tier2RequestId.current;
        const requestedPairs = new Set(
          selectors.map((item) => `${item.disease_group_id}\u0000${item.weather_factor}`),
        );
        setTier2Loading(true);
        setTier2LoadingDiseaseIds([...new Set(selectors.map((item) => item.disease_group_id))]);
        void api.getPublicPublishedMedicalKnowledge(selectors)
          .then((response) => {
            if (tier2RequestId.current === requestId) {
              setPublishedMedicalKnowledge(response.items.filter((item) =>
                requestedPairs.has(`${item.disease_group_id}\u0000${item.weather_factor}`),
              ));
            }
          })
          .catch(() => {
            if (tier2RequestId.current === requestId) {
              setPublishedMedicalKnowledge([]);
            }
          })
          .finally(() => {
            if (tier2RequestId.current === requestId) {
              setTier2Loading(false);
              setTier2LoadingDiseaseIds([]);
            }
          });
      }
    } catch (e) {
      setError(api.weatherAIErrorMessage(e));
    } finally {
      setLoading(false);
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
        publishedMedicalKnowledge: publishedMedicalKnowledge.filter(
          (item) => item.disease_group_id === row.disease_group_id,
        ),
      };
    });
  }, [aiResult, localRisks, knowledge, publishedMedicalKnowledge, t]);

  const mainRisk = combinedRisks[0] ?? null;
  const otherRisks = combinedRisks.slice(1);

  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-sky-50 via-slate-50 to-amber-50 text-slate-800">
      <DecorativeBackground />
      <main className="relative z-10 mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <HospitalBrandBadge />
          <PersonalBrandBadge />
        </div>
        <section className="overflow-hidden rounded-[34px] border border-white/90 bg-white/90 shadow-xl shadow-sky-100/70 backdrop-blur">
          <div className="relative bg-gradient-to-br from-sky-100/90 via-white to-amber-100/90 px-5 pb-6 pt-5 sm:px-7 sm:pt-7">
            <div className="pointer-events-none absolute right-8 top-8 h-24 w-24 rounded-full bg-amber-200/70" />
            <div className="pointer-events-none absolute right-28 top-20 h-12 w-12 rounded-full bg-teal-200/70" />
            <div className="pointer-events-none absolute bottom-8 left-8 h-16 w-16 rounded-full bg-sky-200/80" />
            <div className="pointer-events-none absolute left-1/2 top-8 h-10 w-10 rounded-full bg-rose-200/70" />

            <div className="relative grid gap-6 lg:grid-cols-[1fr_270px]">
              <div>
                <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-white px-3 py-1.5 text-sm font-black text-sky-700 shadow-md shadow-sky-100">
                  <Baby size={16} />
                  {t('parent.hero.badge')}
                </div>
                <h1 className="max-w-3xl bg-gradient-to-r from-sky-700 via-fuchsia-600 to-amber-500 bg-clip-text text-3xl font-black leading-tight text-transparent sm:text-4xl lg:text-5xl">
                  {t('parent.hero.title')}
                </h1>
                <p className="mt-4 max-w-2xl text-sm font-medium leading-6 text-slate-600 sm:text-base">
                  {t('parent.hero.subtitle')}
                </p>
                <div className="mt-5 flex flex-wrap gap-2 text-sm font-black">
                  <span className="rounded-full bg-sky-100 px-3 py-1.5 text-sky-700 shadow-sm">🐣 {t('parent.hero.easy')}</span>
                  <span className="rounded-full bg-rose-100 px-3 py-1.5 text-rose-700 shadow-sm">🧸 {t('parent.hero.friendly')}</span>
                  <span className="rounded-full bg-teal-100 px-3 py-1.5 text-teal-700 shadow-sm">🐳 {t('parent.hero.early')}</span>
                  <span className="rounded-full bg-amber-100 px-3 py-1.5 text-amber-700 shadow-sm">🦁 {t('parent.hero.childCentered')}</span>
                </div>
              </div>

              <div className="relative min-h-[270px] overflow-hidden rounded-[28px] border border-white bg-white/90 p-4 shadow-lg shadow-teal-100/70">
                <div className="pointer-events-none absolute -right-5 -top-4 text-7xl opacity-25">🐳</div>
                <div className="relative z-10 flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-3xl bg-gradient-to-br from-teal-100 to-sky-100 text-teal-700 shadow-sm">
                    <HeartPulse size={24} />
                  </div>
                  <div>
                    <p className="font-black text-teal-900">{t('parent.weather.title')}</p>
                    <p className="text-xs font-semibold text-slate-500">{t('parent.weather.subtitle')}</p>
                  </div>
                </div>
                <div className="relative z-10 mt-4 grid grid-cols-2 gap-3">
                  <WeatherTile icon={Thermometer} label={t('parent.weather.temperature')} value={`${formatNum(aiResult?.weather?.features?.temp_mean_today)}°C`} />
                  <WeatherTile icon={Droplets} label={t('parent.weather.humidity')} value={`${formatNum(aiResult?.weather?.features?.humidity_mean_today)}%`} />
                </div>
                <div className="pointer-events-none absolute bottom-24 left-5 h-4 w-4 rounded-full bg-sky-200/80 shadow-sm" />
                <div className="pointer-events-none absolute bottom-14 left-10 h-2.5 w-2.5 rounded-full bg-rose-200/90" />
                <div className="pointer-events-none absolute bottom-32 left-12 text-xl font-black text-amber-300/80">✦</div>
                <div className="pointer-events-none absolute bottom-16 right-5 h-4 w-4 rounded-full bg-amber-200/90 shadow-sm" />
                <div className="pointer-events-none absolute bottom-28 right-10 h-2.5 w-2.5 rounded-full bg-teal-200/90" />
                <div className="pointer-events-none absolute bottom-40 right-5 text-lg font-black text-rose-300/80">✦</div>
                <div className="pointer-events-none absolute bottom-3 left-1/2 h-12 w-52 -translate-x-1/2 rounded-[50%] bg-gradient-to-r from-sky-100/30 via-amber-100/70 to-rose-100/30 blur-sm" />
                <div className="pointer-events-none absolute inset-x-0 bottom-[-18px] z-[1] flex justify-center">
                  <img
                    src="/parent-weather-fox.png"
                    alt=""
                    aria-hidden="true"
                    className="h-[165px] w-auto max-w-[80%] object-contain drop-shadow-[0_18px_18px_rgba(14,116,144,0.14)]"
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="border-t border-amber-100 bg-gradient-to-r from-white via-sky-50/70 to-rose-50/70 px-5 py-5 sm:px-7">
            <div className="grid gap-3 lg:grid-cols-[1.2fr_0.8fr_0.55fr_auto]">
              <div className="space-y-3">
                <Field label={t('parent.location.chooseMode')}>
                  <div className="grid grid-cols-2 gap-2 rounded-2xl border border-sky-100 bg-white p-1 shadow-inner shadow-sky-50">
                    <button
                      type="button"
                      onClick={() => {
                        clearResults();
                        setLocationMode('gps');
                        if (!coords) requestLocation();
                      }}
                      className={`inline-flex h-10 items-center justify-center gap-2 rounded-xl px-3 text-sm font-bold transition ${
                        locationMode === 'gps' ? 'bg-gradient-to-r from-teal-500 to-sky-500 text-white shadow-sm' : 'text-slate-600 hover:bg-sky-50'
                      }`}
                    >
                      <LocateFixed size={16} />
                      {t('parent.location.useGps')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        clearResults();
                        setLocationMode('manual');
                        setProvinceOpen(true);
                      }}
                      className={`inline-flex h-10 items-center justify-center gap-2 rounded-xl px-3 text-sm font-bold transition ${
                        locationMode === 'manual' ? 'bg-gradient-to-r from-sky-500 to-fuchsia-500 text-white shadow-sm' : 'text-slate-600 hover:bg-rose-50'
                      }`}
                    >
                      <MapPin size={16} />
                      {t('parent.location.manual')}
                    </button>
                  </div>
                </Field>

                {locationMode === 'manual' ? (
                  <Field label={t('parent.location.province')}>
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
                  <div className="rounded-2xl border border-teal-200 bg-gradient-to-br from-teal-50 to-sky-50 p-3 text-sm text-teal-800 shadow-sm">
                    <div className="flex items-start gap-2">
                      {coords ? <CheckCircle2 size={17} className="mt-0.5 shrink-0" /> : <LocateFixed size={17} className="mt-0.5 shrink-0" />}
                      <div className="min-w-0 flex-1">
                        <p className="font-bold">
                          {locating ? t('parent.location.loading') : locationMessage ?? t('parent.location.prompt')}
                        </p>
                        {coords && (
                          <p className="mt-1 text-xs text-teal-700">
                            {t('parent.location.coords', { latitude: coords.latitude.toFixed(4), longitude: coords.longitude.toFixed(4) })}
                          </p>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={requestLocation}
                      disabled={locating}
                      className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-white px-3 text-sm font-black text-teal-700 shadow-sm hover:bg-teal-100 disabled:opacity-60"
                    >
                      {locating ? <Loader2 className="animate-spin" size={16} /> : <LocateFixed size={16} />}
                      {coords ? t('parent.location.retryGps') : t('parent.location.getGps')}
                    </button>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Field label={t('parent.child.age')}>
                  <select
                    value={ageGroup}
                    onChange={(e) => setAgeGroup(e.target.value)}
                    className="h-12 w-full rounded-2xl border border-sky-100 bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm outline-none focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                  >
                    {(options?.age_groups ?? []).map((item) => (
                      <option key={item} value={item}>{displayOption(item, t)}</option>
                    ))}
                  </select>
                </Field>
                <Field label={t('parent.child.gender')}>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="h-12 w-full rounded-2xl border border-rose-100 bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm outline-none focus:border-rose-400 focus:ring-4 focus:ring-rose-100"
                  >
                    {(options?.genders ?? []).map((item) => (
                      <option key={item} value={item}>{displayOption(item, t)}</option>
                    ))}
                  </select>
                </Field>
              </div>

              <Field label={t('parent.display.label')}>
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="h-12 w-full rounded-2xl border border-amber-100 bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm outline-none focus:border-amber-400 focus:ring-4 focus:ring-amber-100"
                >
                  {[3, 5, 10, 15, 20].map((n) => (
                    <option key={n} value={n}>{t('parent.display.top', { count: n })}</option>
                  ))}
                </select>
              </Field>

              <div className="flex flex-col justify-end gap-2 sm:flex-row lg:flex-col">
                <button
                  data-testid="parent-predict-submit"
                  onClick={run}
                  disabled={loading || initialLoading}
                  className="inline-flex h-12 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-sky-500 via-cyan-500 to-teal-500 px-5 text-sm font-black text-white shadow-lg shadow-sky-200 hover:from-sky-600 hover:to-teal-600 disabled:opacity-60"
                >
                  {loading || initialLoading ? <Loader2 className="animate-spin" size={17} /> : <HeartPulse size={17} />}
                  {t('parent.actions.viewResults')}
                </button>
              </div>
            </div>

            {error && (
              <div className="mt-4 flex gap-2 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                <AlertTriangle size={18} className="shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {loading && <WeatherAILoadingNotice />}
          </div>
        </section>

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="space-y-5">
            <section className="rounded-[30px] border border-white bg-white/95 p-5 shadow-xl shadow-sky-100/60 sm:p-6">
              <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-sky-100 px-3 py-1 text-sm font-black text-sky-700">
                    <MapPin size={15} />
                    {selectedProvince?.name ?? t('parent.location.notSelected')}
                  </div>
                  <h2 className="bg-gradient-to-r from-sky-700 to-fuchsia-600 bg-clip-text text-2xl font-black text-transparent">
                    {t('parent.results.title')}
                  </h2>
                </div>
                <div className="flex flex-wrap gap-2 text-xs font-bold">
                  <span className="rounded-full bg-sky-100 px-3 py-1 text-sky-700">{t('parent.results.weatherAi')}</span>
                  <span className="rounded-full bg-teal-100 px-3 py-1 text-teal-700">{t('parent.results.areaData')}</span>
                  {Boolean(aiResult?.weather?.features?.season) && (
                    <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-700">
                      {String(aiResult?.weather?.features?.season)}
                    </span>
                  )}
                </div>
              </div>

              {!mainRisk ? (
                <EmptyState loading={loading || initialLoading} />
              ) : (
                <div className="space-y-4">
                  <ParentDiseaseCard row={mainRisk} index={0} featured tier2Loading={tier2Loading && tier2LoadingDiseaseIds.includes(mainRisk.disease_group_id)} />
                  {otherRisks.length > 0 && (
                    <div className="space-y-4">
                      {otherRisks.map((row, index) => (
                        <ParentDiseaseCard key={row.disease_id} row={row} index={index + 1} tier2Loading={tier2Loading && tier2LoadingDiseaseIds.includes(row.disease_group_id)} />
                      ))}
                    </div>
                  )}
                  <WeatherAIDisclaimer disclaimer={aiResult?.disclaimer} />
                </div>
              )}
            </section>
          </div>

          <aside className="space-y-5 self-start xl:sticky xl:top-5">
            <section className="rounded-[26px] border border-white bg-white/95 p-4 shadow-lg shadow-teal-100/50">
              <div className="mb-3 flex items-center gap-2">
                <ShieldCheck className="text-teal-600" size={20} />
                <h2 className="text-lg font-black text-teal-900">{t('parent.recommendations.title')}</h2>
              </div>
              <div>
                {recommendations.length ? (
                  <ol className="divide-y divide-teal-100 rounded-2xl border border-teal-100 bg-gradient-to-br from-teal-50/80 to-sky-50/80 px-3">
                    {recommendations.map((item, index) => (
                      <li key={`${item}-${index}`} className="flex gap-2.5 py-3 text-sm font-medium leading-5 text-slate-700">
                        <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white text-xs font-black text-teal-700 shadow-sm">
                          {index + 1}
                        </span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="rounded-2xl border border-dashed border-teal-200 bg-teal-50/60 p-4 text-sm font-medium leading-6 text-teal-800">
                    {t('parent.recommendations.empty')}
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-[26px] border border-amber-200 bg-gradient-to-br from-amber-50 to-rose-50 p-4 shadow-md shadow-amber-100/50">
              <div className="mb-2 flex items-center gap-2 text-amber-700">
                <Sparkles size={18} />
                <h2 className="font-black">{t('parent.note.title')}</h2>
              </div>
              <p className="text-sm font-medium leading-6 text-slate-700">
                {t('parent.note.body')}
              </p>
            </section>
          </aside>
        </section>
        <ParentBrandFooter />
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-black uppercase tracking-wide text-sky-700">{label}</span>
      {children}
    </label>
  );
}

function WeatherTile({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-sky-50 bg-white p-3 shadow-md shadow-sky-100/70">
      <Icon size={17} className="mb-1 text-teal-700" />
      <p className="text-[11px] font-black text-sky-500">{label}</p>
      <p className="text-base font-black text-slate-900">{value}</p>
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
        data-testid="province-combobox-trigger"
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex h-12 w-full items-center justify-between gap-3 rounded-2xl border bg-white px-4 text-left text-sm shadow-sm outline-none transition ${
          value ? 'border-sky-100 text-slate-900' : 'border-amber-200 text-slate-400'
        } focus:border-sky-400 focus:ring-4 focus:ring-sky-100`}
      >
        <span className="truncate font-semibold">{selectedName ?? t('parent.location.selectProvince')}</span>
        <ChevronDown size={17} className={`shrink-0 text-slate-500 transition ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="mt-2 rounded-2xl border border-sky-100 bg-white p-2 shadow-xl shadow-sky-100/70">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              placeholder={t('parent.location.searchProvince')}
              className="h-10 w-full rounded-xl border border-sky-100 bg-sky-50/70 py-2 pl-9 pr-3 text-sm outline-none focus:border-sky-400 focus:bg-white focus:ring-4 focus:ring-sky-100"
            />
          </div>
          <div className="mt-2 max-h-56 overflow-auto">
            {provinces.length === 0 ? (
              <p className="px-3 py-4 text-center text-sm text-slate-400">{t('parent.location.noProvinceMatch')}</p>
            ) : (
              provinces.map((item) => (
                <button
                  key={item.code}
                  type="button"
                  onClick={() => {
                    onSelect(item.code);
                    setSearch('');
                  }}
                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm hover:bg-sky-50 ${
                    item.code === value ? 'bg-sky-100 font-black text-sky-700' : 'font-medium text-slate-700'
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
    <div className="flex h-64 items-center justify-center rounded-[26px] border border-dashed border-sky-200 bg-gradient-to-br from-sky-50 to-rose-50 text-sm font-medium text-slate-500">
      {loading ? (
        <span className="inline-flex items-center gap-2">
          <Loader2 className="animate-spin" size={17} />
          {t('parent.results.loading')}
        </span>
      ) : (
        t('parent.results.empty')
      )}
    </div>
  );
}
