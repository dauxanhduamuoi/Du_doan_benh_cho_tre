import { Activity, SlidersHorizontal } from 'lucide-react';
import type { DiseaseGroupOption } from '@/lib/medicalKnowledgeApi';
import {
  factorOptionId,
  makeFactorSelector,
  type ExplanationFactorOption,
  type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeFactors';

interface Props {
  diseaseGroups: DiseaseGroupOption[];
  factorOptions: ExplanationFactorOption[];
  diseaseGroupId: string;
  factor: MedicalFactorSelector | null;
  onDiseaseGroupChange: (value: string) => void;
  onFactorChange: (value: MedicalFactorSelector | null) => void;
  compact?: boolean;
}

export default function MedicalTopicSelector({
  diseaseGroups,
  factorOptions,
  diseaseGroupId,
  factor,
  onDiseaseGroupChange,
  onFactorChange,
  compact = false,
}: Props) {
  const selectedOption = factorOptions.find(
    (item) => item.type === factor?.factor_type && item.key === factor?.factor_key,
  );

  return (
    <section
      aria-labelledby="medical-topic-selector-heading"
      className={compact ? '' : 'rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5'}
    >
      {!compact && (
        <div className="mb-4 flex items-start gap-3">
          <span className="rounded-xl bg-blue-50 p-2 text-blue-700"><SlidersHorizontal size={18} /></span>
          <div>
            <h2 id="medical-topic-selector-heading" className="font-bold text-slate-950">Chủ đề đang làm việc</h2>
            <p className="mt-1 text-sm text-slate-600">Chọn nhóm bệnh và yếu tố một lần; toàn bộ kho nguồn và revision bên dưới sẽ theo chủ đề này.</p>
          </div>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <label htmlFor="medical-disease-group" className="mb-1.5 block text-sm font-semibold text-slate-800">1. Nhóm bệnh</label>
          <select
            id="medical-disease-group"
            value={diseaseGroupId}
            onChange={(event) => onDiseaseGroupChange(event.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Chọn nhóm bệnh</option>
            {diseaseGroups.map((group) => <option key={group.id} value={group.id}>{group.id} — {group.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="medical-explanation-factor" className="mb-1.5 block text-sm font-semibold text-slate-800">2. Yếu tố cần giải thích</label>
          <select
            id="medical-explanation-factor"
            value={factor ? `${factor.factor_type}:${factor.factor_key}` : ''}
            onChange={(event) => {
              const option = factorOptions.find((item) => factorOptionId(item) === event.target.value);
              onFactorChange(option ? makeFactorSelector(option) : null);
            }}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Chọn yếu tố cần giải thích</option>
            <optgroup label="Đặc điểm trẻ">
              {factorOptions.filter((item) => item.type === 'AGE' || item.type === 'SEX').map((item) => <option key={factorOptionId(item)} value={factorOptionId(item)}>{item.label_vi}</option>)}
            </optgroup>
            <optgroup label="Thời gian">
              {factorOptions.filter((item) => item.type === 'SEASONALITY').map((item) => <option key={factorOptionId(item)} value={factorOptionId(item)}>{item.label_vi}</option>)}
            </optgroup>
            <optgroup label="Thời tiết">
              {factorOptions.filter((item) => item.type === 'WEATHER').map((item) => <option key={factorOptionId(item)} value={factorOptionId(item)}>{item.label_vi}</option>)}
            </optgroup>
          </select>
          {selectedOption && (selectedOption.type === 'AGE' || selectedOption.type === 'SEX') && (
            <div className="mt-3">
              <label htmlFor="medical-factor-value" className="mb-1.5 block text-sm font-semibold text-slate-800">
                {selectedOption.type === 'AGE' ? 'Nhóm tuổi cần giải thích' : 'Giới tính cần giải thích'}
              </label>
              <select
                id="medical-factor-value"
                value={factor?.factor_value ?? ''}
                onChange={(event) => onFactorChange({ ...factor!, factor_value: event.target.value || null })}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                <option value="">{selectedOption.type === 'AGE' ? 'Chọn nhóm tuổi' : 'Chọn giới tính'}</option>
                {selectedOption.values.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </div>
          )}
        </div>
      </div>
      {!diseaseGroupId && !compact && (
        <p className="mt-4 flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">
          <Activity size={15} /> Bắt đầu bằng cách chọn một nhóm bệnh.
        </p>
      )}
    </section>
  );
}
