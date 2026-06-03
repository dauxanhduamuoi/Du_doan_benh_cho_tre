import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CloudSun, Loader2, RefreshCcw, Thermometer, Droplets, CloudRain, Wind } from 'lucide-react';
import * as api from '@/lib/api';

const RISK_BADGE: Record<string, string> = {
  Cao: 'bg-red-100 text-red-700 border-red-200',
  'Trung bình': 'bg-amber-100 text-amber-700 border-amber-200',
  Thấp: 'bg-emerald-100 text-emerald-700 border-emerald-200',
};

function num(v: unknown, digits = 2): string {
  if (typeof v !== 'number' || Number.isNaN(v)) return '-';
  return v.toFixed(digits).replace(/\.00$/, '');
}

export default function WeatherRisk() {
  const [status, setStatus] = useState<api.WeatherAIStatus | null>(null);
  const [options, setOptions] = useState<api.WeatherAIOptions | null>(null);
  const [provinces, setProvinces] = useState<api.AreaOption[]>([]);
  const [provinceCode, setProvinceCode] = useState('');
  const [ageGroup, setAgeGroup] = useState('');
  const [gender, setGender] = useState('');
  const [topK, setTopK] = useState(5);
  const [manualMode, setManualMode] = useState(false);
  const [manualWeather, setManualWeather] = useState({
    temperature: '',
    humidity: '',
    rain: '',
    weather_code: '',
    wind_speed: '',
    wind_gusts: '',
  });
  const [loading, setLoading] = useState(false);
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
          api.listAreaProvinces(),
        ]);
        if (!alive) return;
        setStatus(st);
        setOptions(opt);
        setProvinces(provinceRows);
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

  const canRun = Boolean(ageGroup && gender && !loading);

  const weatherCards = useMemo(() => {
    const f = result?.weather?.features ?? {};
    return [
      { label: 'Nhiệt độ TB hôm nay', value: `${num(f.temp_mean_today)}°C`, icon: Thermometer },
      { label: 'Độ ẩm TB hôm nay', value: `${num(f.humidity_mean_today)}%`, icon: Droplets },
      { label: 'Mưa hôm nay', value: `${num(f.rain_sum_today)} mm`, icon: CloudRain },
      { label: 'Gió lớn nhất', value: `${num(f.wind_speed_max_today)} km/h`, icon: Wind },
    ];
  }, [result]);

  const runPredict = async () => {
    if (!canRun) return;
    setLoading(true);
    setError(null);
    try {
      const payload: Parameters<typeof api.predictWeatherAIRisk>[0] = {
        age_group: ageGroup,
        gender,
        top_k: topK,
      };
      if (manualMode) {
        const requiredFields: Array<keyof typeof manualWeather> = ['temperature', 'humidity'];
        const missingFields = requiredFields.filter((key) => manualWeather[key].trim() === '');
        if (missingFields.length > 0) {
          throw new Error('Vui lòng nhập nhiệt độ và độ ẩm khi test thời tiết thủ công.');
        }
        const toNumber = (value: string, fallback = 0) => {
          const trimmed = value.trim();
          if (!trimmed) return fallback;
          const parsed = Number(trimmed);
          if (!Number.isFinite(parsed)) {
            throw new Error('Thông tin thời tiết thủ công phải là số hợp lệ.');
          }
          return parsed;
        };
        payload.weather = {
          temperature: toNumber(manualWeather.temperature),
          humidity: toNumber(manualWeather.humidity),
          rain: toNumber(manualWeather.rain),
          weather_code: toNumber(manualWeather.weather_code),
          wind_speed: toNumber(manualWeather.wind_speed),
          wind_gusts: toNumber(manualWeather.wind_gusts),
        };
      } else {
        const selectedProvince = provinces.find((item) => item.code === provinceCode);
        if (!selectedProvince) {
          throw new Error('Vui lòng chọn tỉnh/thành phố để lấy thời tiết realtime.');
        }
        if (typeof selectedProvince.latitude !== 'number' || typeof selectedProvince.longitude !== 'number') {
          throw new Error('Tỉnh/thành phố đã chọn chưa có tọa độ để lấy thời tiết realtime.');
        }
        payload.latitude = selectedProvince.latitude;
        payload.longitude = selectedProvince.longitude;
        payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Bangkok';
      }
      const res = await api.predictWeatherAIRisk(payload);
      setResult(res);
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
          <div>
            <div className="flex items-center gap-2">
              <div className="rounded-xl bg-blue-50 p-2 text-blue-600">
                <CloudSun size={22} />
              </div>
              <div>
                <h2 className="text-xl font-semibold text-slate-800">Dự đoán nguy cơ bệnh theo thời tiết</h2>
                <p className="text-sm text-slate-500">
                  Nhập nhóm tuổi, giới tính và tỉnh/thành phố để backend lấy thời tiết realtime từ Open-Meteo rồi trả về top nhóm bệnh nguy cơ cao.
                </p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 max-w-md">
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
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[380px_1fr]">
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
              <h3 className="font-semibold text-slate-800">Input dự đoán</h3>
              <p className="text-xs text-slate-500">Khi không test thủ công, hệ thống cần tỉnh/thành phố để lấy đúng thời tiết tại khu vực.</p>
            </div>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Nhóm tuổi</span>
              <select
                value={ageGroup}
                onChange={(e) => setAgeGroup(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {(options?.age_groups ?? []).map((x) => (
                  <option key={x} value={x}>{x}</option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Giới tính</span>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {(options?.genders ?? []).map((x) => (
                  <option key={x} value={x}>{x}</option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Số nhóm bệnh hiển thị</span>
              <input
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value || 5))}
                className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>

            <label className="flex items-center gap-2 rounded-xl border border-slate-200 p-3 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={manualMode}
                onChange={(e) => {
                  setManualMode(e.target.checked);
                  setResult(null);
                }}
              />
              Test bằng weather thủ công, không gọi internet
            </label>

            {!manualMode && (
              <label className="block space-y-1">
                <span className="text-sm font-medium text-slate-700">Tỉnh/thành phố lấy thời tiết</span>
                <select
                  value={provinceCode}
                  onChange={(e) => {
                    setProvinceCode(e.target.value);
                    setResult(null);
                  }}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Chọn tỉnh/thành phố</option>
                  {provinces.map((item) => (
                    <option key={item.code} value={item.code}>{item.name}</option>
                  ))}
                </select>
              </label>
            )}

            {manualMode && (
              <div className="grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3">
                {Object.entries(manualWeather).map(([key, value]) => (
                  <label key={key} className="block space-y-1">
                    <span className="text-xs text-slate-500">{key}</span>
                    <input
                      value={value}
                      onChange={(e) => setManualWeather((cur) => ({ ...cur, [key]: e.target.value }))}
                      className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                ))}
              </div>
            )}

            {error && (
              <div className="flex gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <AlertTriangle size={18} className="shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              onClick={runPredict}
              disabled={!canRun}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? <Loader2 className="animate-spin" size={16} /> : <RefreshCcw size={16} />}
              {loading ? 'Đang dự đoán...' : 'Dự đoán nguy cơ'}
            </button>

            {status && (
              <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
                <p>Model: {status.ready ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</p>
                <p>Nhóm bệnh model hỗ trợ: {status.disease_groups ?? '-'}</p>
              </div>
            )}
          </div>

          <div className="space-y-4">
            {!result ? (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
                Chưa có kết quả. Chọn nhóm tuổi/giới tính rồi bấm dự đoán.
              </div>
            ) : (
              <>
                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-800">Thời tiết dùng cho dự đoán</h3>
                      <p className="text-xs text-slate-500">
                        {result.weather?.meta?.source === 'open_meteo' ? 'Nguồn: Open-Meteo realtime' : 'Nguồn: nhập thủ công'} · Tháng {result.weather.month} · {result.weather.season}
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    {weatherCards.map((card) => {
                      const Icon = card.icon;
                      return (
                        <div key={card.label} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                          <Icon size={17} className="mb-2 text-blue-600" />
                          <p className="text-xs text-slate-500">{card.label}</p>
                          <p className="text-lg font-semibold text-slate-800">{card.value}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h3 className="mb-4 font-semibold text-slate-800">Top nhóm bệnh nguy cơ cao</h3>
                  <div className="space-y-3">
                    {result.top_risks.map((row, idx) => (
                      <div key={`${row.disease_group_id}-${idx}`} className="rounded-xl border border-slate-100 p-4 hover:bg-slate-50">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-700">{idx + 1}</span>
                              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${RISK_BADGE[row.risk_level] ?? 'bg-slate-100 text-slate-700 border-slate-200'}`}>{row.risk_level}</span>
                            </div>
                            <p className="mt-2 font-semibold text-slate-800">{row.disease_group_name}</p>
                            <p className="mt-1 text-xs text-slate-500">ID nhóm: {row.disease_group_id} · Mã báo cáo: {row.report_group_code || '-'}</p>
                          </div>
                          <div className="grid grid-cols-3 gap-2 text-center md:w-[320px]">
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
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
