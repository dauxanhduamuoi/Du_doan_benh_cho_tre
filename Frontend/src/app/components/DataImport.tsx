import { useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Loader2, Upload, X } from 'lucide-react';
import * as api from '@/lib/api';
import { addNotification } from '@/lib/notifications';
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
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const pushToast = (type: Toast['type'], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const handleImport = async (kind: 'patient' | 'disease-codes', file: File) => {
    const label = kind === 'patient' ? 'DS-BenhNhan' : 'DS-MaBenh';
    setBusyAction(`import-${kind}`);
    try {
      if (kind === 'patient') {
        await api.importPatientData(file);
      } else {
        await api.importDiseaseCodes(file);
      }
      pushToast('success', `Import ${label} thành công: ${file.name}`);
      addNotification({
        type: 'import',
        severity: 'info',
        title: `Import ${label} thành công`,
        description: file.name,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      pushToast('error', msg);
      addNotification({
        type: 'import',
        severity: 'critical',
        title: `Import ${label} thất bại`,
        description: `${file.name} - ${msg}`,
      });
    } finally {
      setBusyAction(null);
    }
  };

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
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== toast.id))}
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
            busy={busyAction === 'import-patient'}
            onClick={() => patientFileRef.current?.click()}
          />
          <ImportCard
            title="Import DS-MaBenh"
            description="Bảng mã bệnh dùng để map ICD sang nhóm bệnh. Nên import trước DS-BenhNhan."
            buttonLabel="Chọn file DS-MaBenh"
            busy={busyAction === 'import-disease-codes'}
            onClick={() => diseaseCodesFileRef.current?.click()}
          />
        </div>

        <input
          ref={patientFileRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = '';
            if (f) handleImport('patient', f);
          }}
        />
        <input
          ref={diseaseCodesFileRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = '';
            if (f) handleImport('disease-codes', f);
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
  busy,
  onClick,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h3 className="font-semibold text-slate-800">{title}</h3>
      <p className="mt-1 min-h-[44px] text-sm leading-6 text-slate-500">{description}</p>
      <button
        onClick={onClick}
        disabled={busy}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
        {buttonLabel}
      </button>
    </div>
  );
}
