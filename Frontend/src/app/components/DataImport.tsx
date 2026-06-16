import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Loader2, Upload, X } from 'lucide-react';
import {
  getActiveImportJob,
  runImportJob,
  subscribeImportJob,
  syncImportJobStatus,
  type ActiveImportJob,
  type ImportKind,
} from '@/lib/importJobs';
import * as api from '@/lib/api';
import DiseaseCodesManager from './DiseaseCodesManager';
import ParentGuideManager from './ParentGuideManager';
import ProvinceRegionsManager from './ProvinceRegionsManager';

interface Toast {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

export default function DataImport() {
  const patientFileRef = useRef<HTMLInputElement>(null);
  const diseaseCodesFileRef = useRef<HTMLInputElement>(null);
  const [activeImport, setActiveImport] = useState<ActiveImportJob | null>(() => getActiveImportJob());
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [patientStatus, setPatientStatus] = useState<api.PatientDataStatus | null>(null);
  const [diseaseCodesStatus, setDiseaseCodesStatus] = useState<api.DiseaseCodesStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  const loadImportStatuses = useCallback(async () => {
    setStatusLoading(true);
    try {
      const [patient, diseaseCodes] = await Promise.all([
        api.getPatientDataStatus(),
        api.getDiseaseCodesStatus(),
      ]);
      setPatientStatus(patient);
      setDiseaseCodesStatus(diseaseCodes);
    } catch (error) {
      console.error('Không tải được trạng thái import', error);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeImportJob(() => setActiveImport(getActiveImportJob()));
    void syncImportJobStatus();
    void loadImportStatuses();
    const intervalId = window.setInterval(() => {
      void syncImportJobStatus();
    }, 3000);

    return () => {
      unsubscribe();
      window.clearInterval(intervalId);
    };
  }, [loadImportStatuses]);

  const pushToast = (type: Toast['type'], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 4000);
  };

  const handleImport = async (kind: ImportKind, file: File) => {
    const label = kind === 'patient' ? 'DS-BenhNhan' : 'DS-MaBenh';
    try {
      await runImportJob(kind, file);
      await loadImportStatuses();
      pushToast('success', `Import ${label} thành công: ${file.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushToast('error', message);
    }
  };

  const importing = activeImport !== null;

  return (
    <div className="relative space-y-6">
      <div className="fixed right-4 top-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex min-w-[280px] max-w-sm items-start gap-2 rounded-xl border px-4 py-3 shadow-lg ${
              toast.type === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : toast.type === 'error'
                  ? 'border-red-200 bg-red-50 text-red-800'
                  : 'border-slate-200 bg-slate-50 text-slate-700'
            }`}
          >
            {toast.type === 'success' ? (
              <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
            ) : toast.type === 'error' ? (
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            ) : null}
            <span className="flex-1 break-words text-sm">{toast.message}</span>
            <button
              onClick={() => setToasts((prev) => prev.filter((item) => item.id !== toast.id))}
              className="text-slate-400 hover:text-slate-600"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-600 ring-1 ring-blue-100">
              <Database size={22} />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-slate-800">Import dữ liệu</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                Tập trung các thao tác nạp dữ liệu: danh sách bệnh nhân, mã bệnh, phân miền khu vực và hướng dẫn phụ huynh.
                Hãy kiểm tra đúng file trước khi import để tránh ghi đè dữ liệu hiện tại.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <ImportCard
            title="Import DS-BenhNhan"
            description="Danh sách bệnh nhân dùng cho dashboard, phân tích khu vực, độ tuổi, giới tính và dự báo."
            buttonLabel="Chọn file DS-BenhNhan"
            busyLabel="Đang import DS-BenhNhan"
            busy={activeImport?.kind === 'patient'}
            disabled={importing}
            status={{
              loading: statusLoading && !patientStatus,
              imported: patientStatus?.has_patient_data ?? false,
              detail: patientStatus
                ? [
                    patientStatus.uploaded_file ? `File: ${patientStatus.uploaded_file}` : null,
                    `${patientStatus.patient_rows.toLocaleString('vi-VN')} dòng bệnh nhân`,
                  ]
                    .filter(Boolean)
                    .join(' - ')
                : undefined,
            }}
            onClick={() => patientFileRef.current?.click()}
          />
          <ImportCard
            title="Import DS-MaBenh"
            description="Bảng mã bệnh dùng để map ICD sang nhóm bệnh. Nên import trước DS-BenhNhan."
            buttonLabel="Chọn file DS-MaBenh"
            busyLabel="Đang import DS-MaBenh"
            busy={activeImport?.kind === 'disease-codes'}
            disabled={importing}
            status={{
              loading: statusLoading && !diseaseCodesStatus,
              imported: diseaseCodesStatus?.has_disease_codes ?? false,
              detail: diseaseCodesStatus
                ? `${diseaseCodesStatus.total_codes.toLocaleString('vi-VN')} mã bệnh`
                : undefined,
            }}
            onClick={() => diseaseCodesFileRef.current?.click()}
          />
        </div>

        {activeImport && (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            <div className="flex items-start gap-2">
              <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin" />
              <div>
                <div className="font-semibold">Đang import {activeImport.label}</div>
                <div className="mt-0.5 break-words text-blue-700">
                  File: {activeImport.fileName}. Bạn có thể chuyển sang mục khác hoặc reload trang, tiến trình vẫn được theo dõi từ backend.
                </div>
              </div>
            </div>
          </div>
        )}

        <input
          ref={patientFileRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void handleImport('patient', file);
          }}
        />
        <input
          ref={diseaseCodesFileRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void handleImport('disease-codes', file);
          }}
        />
      </section>

      <DiseaseCodesManager />
      <ProvinceRegionsManager />
      <ParentGuideManager />
    </div>
  );
}

function ImportCard({
  title,
  description,
  buttonLabel,
  busyLabel,
  busy,
  disabled,
  status,
  onClick,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  busyLabel: string;
  busy: boolean;
  disabled: boolean;
  status: {
    loading: boolean;
    imported: boolean;
    detail?: string;
  };
  onClick: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-800">{title}</h3>
        <ImportStatusBadge status={status} />
      </div>
      <p className="mt-1 min-h-[44px] text-sm leading-6 text-slate-500">{description}</p>
      <button
        onClick={onClick}
        disabled={disabled}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
        {busy ? busyLabel : buttonLabel}
      </button>
    </div>
  );
}

function ImportStatusBadge({
  status,
}: {
  status: {
    loading: boolean;
    imported: boolean;
    detail?: string;
  };
}) {
  if (status.loading) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-500">
        <Loader2 size={14} className="animate-spin" />
        Đang kiểm tra
      </span>
    );
  }

  if (status.imported) {
    return (
      <span
        title={status.detail}
        className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700"
      >
        <CheckCircle2 size={14} />
        Đã import
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">
      <AlertTriangle size={14} />
      Chưa import
    </span>
  );
}
