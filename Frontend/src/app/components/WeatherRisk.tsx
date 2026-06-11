import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CloudRain,
  CloudSun,
  Droplets,
  Loader2,
  LocateFixed,
  MapPin,
  RefreshCcw,
  Search,
  Thermometer,
  Wind,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import * as api from '@/lib/api';
import { useMinimalTheme } from '@/lib/useMinimalTheme';

type LocationMode = 'geo' | 'manual';
type ProvinceOption = api.AreaOption & {
  latitude: number;
  longitude: number;
};

type RiskChartRow = api.WeatherAIRiskItem & {
  shortName: string;
};

const RISK_BADGE: Record<string, string> = {
  Cao: 'bg-red-100 text-red-700 border-red-200',
  'Trung bình': 'bg-amber-100 text-amber-700 border-amber-200',
  Thấp: 'bg-emerald-100 text-emerald-700 border-emerald-200',
};

const RISK_BAR_COLOR: Record<string, string> = {
  Cao: '#ef4444',
  'Trung bình': '#f59e0b',
  Thấp: '#10b981',
};

const VIETNAM_PROVINCES: ProvinceOption[] = [
  { code: 'VN-AG', name: 'An Giang', latitude: 10.5216, longitude: 105.1259, is_active: true },
  { code: 'VN-BRVT', name: 'Bà Rịa - Vũng Tàu', latitude: 10.5417, longitude: 107.2429, is_active: true },
  { code: 'VN-BG', name: 'Bắc Giang', latitude: 21.2731, longitude: 106.1946, is_active: true },
  { code: 'VN-BK', name: 'Bắc Kạn', latitude: 22.147, longitude: 105.8348, is_active: true },
  { code: 'VN-BL', name: 'Bạc Liêu', latitude: 9.294, longitude: 105.7216, is_active: true },
  { code: 'VN-BN', name: 'Bắc Ninh', latitude: 21.1861, longitude: 106.0763, is_active: true },
  { code: 'VN-BTE', name: 'Bến Tre', latitude: 10.2434, longitude: 106.3756, is_active: true },
  { code: 'VN-BD', name: 'Bình Định', latitude: 13.782, longitude: 109.219, is_active: true },
  { code: 'VN-BDU', name: 'Bình Dương', latitude: 11.3254, longitude: 106.477, is_active: true },
  { code: 'VN-BP', name: 'Bình Phước', latitude: 11.7512, longitude: 106.7235, is_active: true },
  { code: 'VN-BTH', name: 'Bình Thuận', latitude: 10.9333, longitude: 108.1, is_active: true },
  { code: 'VN-CM', name: 'Cà Mau', latitude: 9.1768, longitude: 105.1524, is_active: true },
  { code: 'VN-CT', name: 'Cần Thơ', latitude: 10.0452, longitude: 105.7469, is_active: true },
  { code: 'VN-CB', name: 'Cao Bằng', latitude: 22.6666, longitude: 106.2639, is_active: true },
  { code: 'VN-DN', name: 'Đà Nẵng', latitude: 16.0544, longitude: 108.2022, is_active: true },
  { code: 'VN-DL', name: 'Đắk Lắk', latitude: 12.71, longitude: 108.2378, is_active: true },
  { code: 'VN-DNO', name: 'Đắk Nông', latitude: 12.0042, longitude: 107.6907, is_active: true },
  { code: 'VN-DB', name: 'Điện Biên', latitude: 21.386, longitude: 103.023, is_active: true },
  { code: 'VN-DNA', name: 'Đồng Nai', latitude: 10.9453, longitude: 106.8246, is_active: true },
  { code: 'VN-DT', name: 'Đồng Tháp', latitude: 10.4938, longitude: 105.6882, is_active: true },
  { code: 'VN-GL', name: 'Gia Lai', latitude: 13.9833, longitude: 108, is_active: true },
  { code: 'VN-HG', name: 'Hà Giang', latitude: 22.8233, longitude: 104.9836, is_active: true },
  { code: 'VN-HNA', name: 'Hà Nam', latitude: 20.5835, longitude: 105.9229, is_active: true },
  { code: 'VN-HN', name: 'Hà Nội', latitude: 21.0278, longitude: 105.8342, is_active: true },
  { code: 'VN-HT', name: 'Hà Tĩnh', latitude: 18.3428, longitude: 105.9057, is_active: true },
  { code: 'VN-HD', name: 'Hải Dương', latitude: 20.9373, longitude: 106.3145, is_active: true },
  { code: 'VN-HP', name: 'Hải Phòng', latitude: 20.8449, longitude: 106.6881, is_active: true },
  { code: 'VN-HGI', name: 'Hậu Giang', latitude: 9.7579, longitude: 105.6413, is_active: true },
  { code: 'VN-HCM', name: 'Thành phố Hồ Chí Minh', latitude: 10.7769, longitude: 106.7009, is_active: true },
  { code: 'VN-HB', name: 'Hòa Bình', latitude: 20.8172, longitude: 105.3376, is_active: true },
  { code: 'VN-HY', name: 'Hưng Yên', latitude: 20.6464, longitude: 106.0511, is_active: true },
  { code: 'VN-KH', name: 'Khánh Hòa', latitude: 12.2388, longitude: 109.1967, is_active: true },
  { code: 'VN-KG', name: 'Kiên Giang', latitude: 10.0125, longitude: 105.0809, is_active: true },
  { code: 'VN-KT', name: 'Kon Tum', latitude: 14.3497, longitude: 108.0005, is_active: true },
  { code: 'VN-LC', name: 'Lai Châu', latitude: 22.3862, longitude: 103.4703, is_active: true },
  { code: 'VN-LD', name: 'Lâm Đồng', latitude: 11.5753, longitude: 108.1429, is_active: true },
  { code: 'VN-LS', name: 'Lạng Sơn', latitude: 21.8537, longitude: 106.7615, is_active: true },
  { code: 'VN-LCA', name: 'Lào Cai', latitude: 22.4856, longitude: 103.9707, is_active: true },
  { code: 'VN-LA', name: 'Long An', latitude: 10.6956, longitude: 106.2431, is_active: true },
  { code: 'VN-ND', name: 'Nam Định', latitude: 20.4388, longitude: 106.1621, is_active: true },
  { code: 'VN-NA', name: 'Nghệ An', latitude: 18.6796, longitude: 105.6813, is_active: true },
  { code: 'VN-NB', name: 'Ninh Bình', latitude: 20.2506, longitude: 105.9745, is_active: true },
  { code: 'VN-NT', name: 'Ninh Thuận', latitude: 11.6739, longitude: 108.862, is_active: true },
  { code: 'VN-PT', name: 'Phú Thọ', latitude: 21.2684, longitude: 105.2046, is_active: true },
  { code: 'VN-PY', name: 'Phú Yên', latitude: 13.0882, longitude: 109.0929, is_active: true },
  { code: 'VN-QB', name: 'Quảng Bình', latitude: 17.4689, longitude: 106.6223, is_active: true },
  { code: 'VN-QNA', name: 'Quảng Nam', latitude: 15.5394, longitude: 108.0191, is_active: true },
  { code: 'VN-QNG', name: 'Quảng Ngãi', latitude: 15.1205, longitude: 108.7923, is_active: true },
  { code: 'VN-QN', name: 'Quảng Ninh', latitude: 20.9712, longitude: 107.0448, is_active: true },
  { code: 'VN-QT', name: 'Quảng Trị', latitude: 16.7403, longitude: 107.1855, is_active: true },
  { code: 'VN-ST', name: 'Sóc Trăng', latitude: 9.6025, longitude: 105.9739, is_active: true },
  { code: 'VN-SL', name: 'Sơn La', latitude: 21.327, longitude: 103.9141, is_active: true },
  { code: 'VN-TN', name: 'Tây Ninh', latitude: 11.3352, longitude: 106.1099, is_active: true },
  { code: 'VN-TB', name: 'Thái Bình', latitude: 20.4463, longitude: 106.3366, is_active: true },
  { code: 'VN-TNG', name: 'Thái Nguyên', latitude: 21.5942, longitude: 105.8482, is_active: true },
  { code: 'VN-TH', name: 'Thanh Hóa', latitude: 19.8067, longitude: 105.7852, is_active: true },
  { code: 'VN-TTH', name: 'Thừa Thiên Huế', latitude: 16.4637, longitude: 107.5909, is_active: true },
  { code: 'VN-TG', name: 'Tiền Giang', latitude: 10.4493, longitude: 106.3421, is_active: true },
  { code: 'VN-TV', name: 'Trà Vinh', latitude: 9.9347, longitude: 106.3453, is_active: true },
  { code: 'VN-TQ', name: 'Tuyên Quang', latitude: 21.8236, longitude: 105.2142, is_active: true },
  { code: 'VN-VL', name: 'Vĩnh Long', latitude: 10.2396, longitude: 105.9572, is_active: true },
  { code: 'VN-VP', name: 'Vĩnh Phúc', latitude: 21.3089, longitude: 105.6049, is_active: true },
  { code: 'VN-YB', name: 'Yên Bái', latitude: 21.7229, longitude: 104.9113, is_active: true },
];

function normalizeText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase()
    .trim();
}

function num(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return value.toFixed(digits).replace(/\.00$/, '');
}

function shortDiseaseName(value: string, maxLength = 34): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trim()}…`;
}

function clampInt(value: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function mergeProvinceOptions(rows: api.AreaOption[]): ProvinceOption[] {
  const byName = new Map<string, ProvinceOption>();
  VIETNAM_PROVINCES.forEach((item) => byName.set(normalizeText(item.name), item));

  rows.forEach((row) => {
    const key = normalizeText(row.name);
    const fallback = byName.get(key);
    const latitude = typeof row.latitude === 'number' ? row.latitude : fallback?.latitude;
    const longitude = typeof row.longitude === 'number' ? row.longitude : fallback?.longitude;
    if (typeof latitude !== 'number' || typeof longitude !== 'number') return;
    byName.set(key, {
      ...row,
      code: row.code || fallback?.code || key,
      name: row.name,
      latitude,
      longitude,
      is_active: row.is_active ?? true,
    });
  });

  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name, 'vi'));
}

function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const radius = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function nearestProvince(lat: number, lon: number, provinces: ProvinceOption[]): ProvinceOption | null {
  let best: ProvinceOption | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  provinces.forEach((province) => {
    const distance = distanceKm(lat, lon, province.latitude, province.longitude);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = province;
    }
  });
  return best;
}

function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

export default function WeatherRisk() {
  const isMinimalTheme = useMinimalTheme();
  const [status, setStatus] = useState<api.WeatherAIStatus | null>(null);
  const [options, setOptions] = useState<api.WeatherAIOptions | null>(null);
  const [provinces, setProvinces] = useState<ProvinceOption[]>(VIETNAM_PROVINCES);
  const [locationMode, setLocationMode] = useState<LocationMode>('manual');
  const [provinceCode, setProvinceCode] = useState('');
  const [provinceSearch, setProvinceSearch] = useState('');
  const [provinceOpen, setProvinceOpen] = useState(false);
  const [geoPoint, setGeoPoint] = useState<{ latitude: number; longitude: number; province: ProvinceOption | null } | null>(null);
  const [geoStatus, setGeoStatus] = useState('Chưa lấy vị trí hiện tại.');
  const [ageGroup, setAgeGroup] = useState('');
  const [gender, setGender] = useState('');
  const [topKInput, setTopKInput] = useState('10');
  const [pageSizeInput, setPageSizeInput] = useState('5');
  const [riskPage, setRiskPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<api.WeatherAIPredictResponse | null>(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      setInitialLoading(true);
      setError(null);
      try {
        const [st, opt, provinceRows] = await Promise.all([
          api.getWeatherAIStatus(),
          api.getWeatherAIOptions(),
          api.listAreaProvinces().catch(() => [] as api.AreaOption[]),
        ]);
        if (!alive) return;
        setStatus(st);
        setOptions(opt);
        setProvinces(mergeProvinceOptions(provinceRows));
        setAgeGroup(opt.age_groups?.includes('1-5 tuổi') ? '1-5 tuổi' : (opt.age_groups?.[0] ?? ''));
        setGender(opt.genders?.includes('Nam') ? 'Nam' : (opt.genders?.[0] ?? ''));
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setInitialLoading(false);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  const topK = clampInt(topKInput, 1, 20, 10);
  const riskPageSize = clampInt(pageSizeInput, 1, 20, 5);
  const selectedProvince = useMemo(
    () => provinces.find((item) => item.code === provinceCode) ?? null,
    [provinceCode, provinces],
  );
  const filteredProvinces = useMemo(() => {
    const query = normalizeText(provinceSearch);
    if (!query) return provinces;
    return provinces.filter((item) => normalizeText(item.name).includes(query));
  }, [provinceSearch, provinces]);

  const weatherCards = useMemo(() => {
    const f = result?.weather?.features ?? {};
    return [
      { label: 'Nhiệt độ TB hôm nay', value: `${num(f.temp_mean_today)}°C`, icon: Thermometer },
      { label: 'Độ ẩm TB hôm nay', value: `${num(f.humidity_mean_today)}%`, icon: Droplets },
      { label: 'Mưa hôm nay', value: `${num(f.rain_sum_today)} mm`, icon: CloudRain },
      { label: 'Gió lớn nhất', value: `${num(f.wind_speed_max_today)} km/h`, icon: Wind },
    ];
  }, [result]);

  const totalRiskPages = pageCount(result?.top_risks.length ?? 0, riskPageSize);
  const visibleRisks = useMemo(() => {
    const rows = result?.top_risks ?? [];
    const safePage = Math.min(riskPage, pageCount(rows.length, riskPageSize));
    const start = (safePage - 1) * riskPageSize;
    return rows.slice(start, start + riskPageSize);
  }, [result, riskPage, riskPageSize]);

  const riskChartData = useMemo<RiskChartRow[]>(() => {
    if (!result) return [];
    return result.top_risks
      .map((row) => ({
        ...row,
        shortName: shortDiseaseName(row.disease_group_name),
      }))
      .reverse();
  }, [result]);

  const resetResult = () => {
    setResult(null);
    setRiskPage(1);
    setError(null);
  };

  const handleLocationModeChange = (mode: LocationMode) => {
    setLocationMode(mode);
    resetResult();
  };

  const locateCurrentPosition = () => {
    resetResult();
    if (!navigator.geolocation) {
      setGeoPoint(null);
      setGeoStatus('Trình duyệt không hỗ trợ định vị. Vui lòng tự chọn tỉnh/thành phố.');
      return;
    }
    setLocating(true);
    setGeoStatus('Đang xin quyền và lấy vị trí hiện tại...');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const latitude = position.coords.latitude;
        const longitude = position.coords.longitude;
        const province = nearestProvince(latitude, longitude, provinces);
        setGeoPoint({ latitude, longitude, province });
        setGeoStatus(
          province
            ? `Đã định vị gần ${province.name}. Hệ thống sẽ lấy thời tiết theo tọa độ hiện tại.`
            : 'Đã lấy tọa độ hiện tại, nhưng chưa xác định được tỉnh/thành gần nhất.',
        );
        setLocating(false);
      },
      (err) => {
        setGeoPoint(null);
        setGeoStatus(`Không thể định vị: ${err.message || 'người dùng chưa cho phép truy cập vị trí'}.`);
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 5 * 60 * 1000 },
    );
  };

  const runPredict = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const payload: Parameters<typeof api.predictWeatherAIRisk>[0] = {
        age_group: ageGroup,
        gender,
        top_k: topK,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Bangkok',
      };

      if (locationMode === 'geo') {
        if (!geoPoint) {
          throw new Error('Vui lòng bấm lấy vị trí hiện tại trước khi dự đoán, hoặc chuyển sang tự chọn tỉnh/thành phố.');
        }
        payload.latitude = geoPoint.latitude;
        payload.longitude = geoPoint.longitude;
      } else {
        if (!selectedProvince) {
          throw new Error('Vui lòng chọn tỉnh/thành phố để lấy thời tiết realtime.');
        }
        payload.latitude = selectedProvince.latitude;
        payload.longitude = selectedProvince.longitude;
      }

      const res = await api.predictWeatherAIRisk(payload);
      setResult(res);
      setRiskPage(1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-sky-50 p-2 text-sky-600">
              <CloudSun size={24} />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-slate-800">Dự đoán nguy cơ bệnh theo thời tiết</h2>
              <p className="text-sm text-slate-500">
                Chọn vị trí, nhóm tuổi và giới tính. Backend sẽ lấy thời tiết realtime rồi chạy model AI thời tiết.
              </p>
            </div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 md:max-w-md">
            Đây là cảnh báo thống kê theo dữ liệu lịch sử, không phải chẩn đoán y tế cho từng trẻ.
          </div>
        </div>
      </div>

      {initialLoading ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-500">
          <Loader2 className="mx-auto mb-2 animate-spin" size={24} />
          Đang tải model AI thời tiết...
        </div>
      ) : (
        <div className="relative space-y-6">
          <div
            className={`relative overflow-visible rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${
              provinceOpen ? 'z-50' : 'z-10'
            }`}
          >
            <div className="grid gap-4 xl:grid-cols-[1.25fr_1fr_1fr_1fr_auto]">
              <div className="space-y-3">
                <span className="text-sm font-semibold text-slate-700">Vị trí lấy thời tiết</span>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleLocationModeChange('geo')}
                    className={`inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition ${
                      locationMode === 'geo'
                        ? 'border-sky-500 bg-sky-50 text-sky-700'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <LocateFixed size={16} />
                    Dùng định vị
                  </button>
                  <button
                    type="button"
                    onClick={() => handleLocationModeChange('manual')}
                    className={`inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition ${
                      locationMode === 'manual'
                        ? 'border-sky-500 bg-sky-50 text-sky-700'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <MapPin size={16} />
                    Tự chọn
                  </button>
                </div>

                {locationMode === 'geo' ? (
                  <div className="rounded-xl border border-sky-100 bg-sky-50 p-3">
                    <button
                      type="button"
                      onClick={locateCurrentPosition}
                      disabled={locating}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-sky-600 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-60"
                    >
                      {locating ? <Loader2 className="animate-spin" size={16} /> : <LocateFixed size={16} />}
                      {geoPoint ? 'Định vị lại' : 'Lấy vị trí hiện tại'}
                    </button>
                    <p className="mt-2 text-xs text-slate-600">{geoStatus}</p>
                  </div>
                ) : (
                  <div className="relative z-[70]">
                    <button
                      type="button"
                      onClick={() => setProvinceOpen((open) => !open)}
                      className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
                    >
                      <span>{selectedProvince?.name ?? 'Chọn tỉnh/thành phố'}</span>
                      <ChevronDown size={16} />
                    </button>
                    {provinceOpen && (
                      <div className="absolute left-0 right-0 top-[calc(100%+8px)] z-[80] rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
                        <div className="mb-2 flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2">
                          <Search size={16} className="text-slate-400" />
                          <input
                            autoFocus
                            value={provinceSearch}
                            onChange={(e) => setProvinceSearch(e.target.value)}
                            placeholder="Tìm tỉnh/thành phố..."
                            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                          />
                        </div>
                        <div className="max-h-64 overflow-y-auto">
                          {filteredProvinces.map((province) => (
                            <button
                              key={province.code}
                              type="button"
                              onClick={() => {
                                setProvinceCode(province.code);
                                setProvinceSearch('');
                                setProvinceOpen(false);
                                resetResult();
                              }}
                              className={`block w-full rounded-xl px-3 py-2 text-left text-sm ${
                                province.code === provinceCode
                                  ? 'bg-sky-50 font-semibold text-sky-700'
                                  : 'text-slate-700 hover:bg-slate-50'
                              }`}
                            >
                              {province.name}
                            </button>
                          ))}
                          {filteredProvinces.length === 0 && (
                            <p className="px-3 py-4 text-center text-sm text-slate-500">Không tìm thấy tỉnh/thành phố.</p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <label className="block space-y-2">
                <span className="text-sm font-semibold text-slate-700">Nhóm tuổi</span>
                <select
                  value={ageGroup}
                  onChange={(e) => {
                    setAgeGroup(e.target.value);
                    resetResult();
                  }}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                >
                  {(options?.age_groups ?? []).map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-semibold text-slate-700">Giới tính</span>
                <select
                  value={gender}
                  onChange={(e) => {
                    setGender(e.target.value);
                    resetResult();
                  }}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                >
                  {(options?.genders ?? []).map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-semibold text-slate-700">Số nhóm bệnh hiển thị</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={topKInput}
                  onChange={(e) => {
                    setTopKInput(e.target.value);
                    resetResult();
                  }}
                  onBlur={() => setTopKInput(String(topK))}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
                <span className="text-xs text-slate-500">API hiện hỗ trợ tối đa 20 nhóm/lần dự đoán.</span>
              </label>

              <div className="flex items-end">
                <button
                  onClick={runPredict}
                  disabled={loading || !ageGroup || !gender}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? <Loader2 className="animate-spin" size={16} /> : <RefreshCcw size={16} />}
                  {loading ? 'Đang dự đoán...' : 'Dự đoán nguy cơ'}
                </button>
              </div>
            </div>

            {error && (
              <div className="mt-4 flex gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <AlertTriangle size={18} className="shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>

          {!result ? (
            <div className="relative z-0 rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
              Chưa có kết quả. Chọn vị trí, nhóm tuổi, giới tính rồi bấm dự đoán nguy cơ.
            </div>
          ) : (
            <>
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex flex-col justify-between gap-3 md:flex-row md:items-center">
                  <div>
                    <h3 className="font-semibold text-slate-800">Thời tiết dùng cho dự đoán</h3>
                    <p className="text-xs text-slate-500">
                      Nguồn: Open-Meteo realtime · Tháng {result.weather.month} · {result.weather.season}
                    </p>
                  </div>
                  {status && (
                    <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
                      Model: {status.ready ? 'Sẵn sàng' : 'Chưa sẵn sàng'} · {status.disease_groups ?? '-'} nhóm bệnh
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {weatherCards.map((card) => {
                    const Icon = card.icon;
                    return (
                      <div key={card.label} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                        <Icon size={17} className="mb-2 text-sky-600" />
                        <p className="text-xs text-slate-500">{card.label}</p>
                        <p className="text-lg font-semibold text-slate-800">{card.value}</p>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex flex-col justify-between gap-3 md:flex-row md:items-center">
                  <div>
                    <h3 className="font-semibold text-slate-800">Top nhóm bệnh nguy cơ cao</h3>
                    <p className="text-sm text-slate-500">
                      Hiển thị {(riskPage - 1) * riskPageSize + 1}-{Math.min(riskPage * riskPageSize, result.top_risks.length)} / {result.top_risks.length} nhóm.
                    </p>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    Số dòng/trang
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={pageSizeInput}
                      onChange={(e) => {
                        setPageSizeInput(e.target.value);
                        setRiskPage(1);
                      }}
                      onBlur={() => setPageSizeInput(String(riskPageSize))}
                      className="w-20 rounded-xl border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
                    />
                  </label>
                </div>

                <div className="space-y-3">
                  {visibleRisks.map((row, idx) => {
                    const absoluteIndex = (riskPage - 1) * riskPageSize + idx + 1;
                    return (
                      <div key={`${row.disease_group_id}-${idx}`} className="rounded-xl border border-slate-100 p-4 hover:bg-slate-50">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-sky-50 text-sm font-bold text-sky-700">
                                {absoluteIndex}
                              </span>
                              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${RISK_BADGE[row.risk_level] ?? 'bg-slate-100 text-slate-700 border-slate-200'}`}>
                                {row.risk_level}
                              </span>
                            </div>
                            <p className="mt-2 font-semibold text-slate-800">{row.disease_group_name}</p>
                            <p className="mt-1 text-xs text-slate-500">
                              ID nhóm: {row.disease_group_id} · Mã báo cáo: {row.report_group_code || '-'}
                            </p>
                          </div>
                          <div className="grid grid-cols-3 gap-2 text-center md:w-[330px]">
                            <div className="rounded-xl bg-slate-50 p-2">
                              <p className="text-[11px] text-slate-500">Xác suất</p>
                              <p className="font-semibold text-slate-800">{num(row.probability * 100, 1)}%</p>
                            </div>
                            <div className="rounded-xl bg-slate-50 p-2">
                              <p className="text-[11px] text-slate-500">Ước tính ca/ngày</p>
                              <p className="font-semibold text-slate-800">{num(row.predicted_cases, 2)}</p>
                            </div>
                            <div className="rounded-xl bg-slate-50 p-2">
                              <p className="text-[11px] text-slate-500">Điểm nguy cơ</p>
                              <p className="font-semibold text-slate-800">{num(row.risk_score, 3)}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {result.top_risks.length > riskPageSize && (
                  <div className="mt-4 flex flex-col items-center justify-between gap-3 border-t border-slate-100 pt-4 sm:flex-row">
                    <span className="text-sm text-slate-500">Trang {riskPage} / {totalRiskPages}</span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setRiskPage((page) => Math.max(1, page - 1))}
                        disabled={riskPage <= 1}
                        className="inline-flex items-center gap-1 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 disabled:opacity-50"
                      >
                        <ChevronLeft size={16} />
                        Trước
                      </button>
                      <button
                        type="button"
                        onClick={() => setRiskPage((page) => Math.min(totalRiskPages, page + 1))}
                        disabled={riskPage >= totalRiskPages}
                        className="inline-flex items-center gap-1 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 disabled:opacity-50"
                      >
                        Sau
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="font-semibold text-slate-800">Biểu đồ top nhóm bệnh nguy cơ cao</h3>
                    <p className="text-sm text-slate-500">
                      Trực quan hóa số ca ước tính trong ngày cho các nhóm bệnh model xếp nguy cơ cao. Màu cột thể hiện mức nguy cơ.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs font-semibold">
                    <span className="rounded-full border border-red-200 bg-red-50 px-3 py-1 text-red-700">Cao</span>
                    <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-amber-700">Trung bình</span>
                    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-emerald-700">Thấp</span>
                  </div>
                </div>

                <ResponsiveContainer width="100%" height={Math.max(340, riskChartData.length * 54 + 80)}>
                  <BarChart
                    data={riskChartData}
                    layout="vertical"
                    margin={{ top: 12, right: 44, left: 22, bottom: 8 }}
                    barCategoryGap={12}
                  >
                    <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" />
                    <XAxis
                      type="number"
                      tick={{ fill: '#64748b', fontSize: 12 }}
                      label={{ value: 'Số ca ước tính trong ngày', position: 'insideBottom', offset: -4, fill: '#64748b', fontSize: 12 }}
                    />
                    <YAxis
                      dataKey="shortName"
                      type="category"
                      width={230}
                      tick={{ fill: '#64748b', fontSize: 12 }}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, borderColor: '#e2e8f0' }}
                      formatter={(value) => {
                        return [`khoảng ${num(value, 2)} ca/ngày`, 'Số ca ước tính'];
                      }}
                      labelFormatter={(_, payload) => {
                        const row = payload?.[0]?.payload as RiskChartRow | undefined;
                        return row?.disease_group_name ?? '';
                      }}
                    />
                    <Bar
                      dataKey="predicted_cases"
                      name="Số ca ước tính"
                      radius={[0, 10, 10, 0]}
                      isAnimationActive={!isMinimalTheme}
                    >
                      {riskChartData.map((row) => (
                        <Cell key={row.disease_group_id} fill={RISK_BAR_COLOR[row.risk_level] ?? '#3b82f6'} />
                      ))}
                      <LabelList
                        dataKey="predicted_cases"
                        position="right"
                        formatter={(value: unknown) => `${num(value, 2)} ca/ngày`}
                        style={{ fill: '#334155', fontSize: 12, fontWeight: 700 }}
                      />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <p className="mt-3 text-xs text-slate-500">
                  “Ca/ngày” là số ca model ước tính trong một ngày với thời tiết và thông tin đầu vào hiện tại, không phải mức tăng so với kỳ trước.
                </p>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
