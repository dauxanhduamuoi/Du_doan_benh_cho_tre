import * as api from './api';
import { clearAreaInsightsCache } from './areaInsightsCache';
import { clearChartDataCaches } from './chartDataCache';
import { addNotification } from './notifications';
import { clearWeatherRiskCache } from './weatherRiskCache';

export type ImportKind = 'patient' | 'disease-codes';

export interface ActiveImportJob {
  kind: ImportKind;
  label: string;
  fileName: string;
  startedAt: string;
}

type Listener = () => void;

const STORAGE_KEY = 'sd_active_import_job';
const listeners = new Set<Listener>();

function labelOf(kind: ImportKind) {
  return kind === 'patient' ? 'DS-BenhNhan' : 'DS-MaBenh';
}

function normalizeKind(kind: string): ImportKind {
  return kind === 'disease-codes' ? 'disease-codes' : 'patient';
}

function readStoredJob(): ActiveImportJob | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ActiveImportJob>;
    if (!parsed.kind || !parsed.fileName || !parsed.startedAt) return null;
    const kind = normalizeKind(parsed.kind);
    return {
      kind,
      label: parsed.label || labelOf(kind),
      fileName: parsed.fileName,
      startedAt: parsed.startedAt,
    };
  } catch {
    return null;
  }
}

let activeJob: ActiveImportJob | null = readStoredJob();

export function clearImportedDataCaches() {
  clearWeatherRiskCache();
  clearAreaInsightsCache();
  clearChartDataCaches();
}

function emit() {
  for (const listener of listeners) listener();
}

function persistActiveJob(next: ActiveImportJob | null) {
  if (typeof window === 'undefined') return;

  if (next) {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

function setActiveJob(next: ActiveImportJob | null) {
  activeJob = next;
  persistActiveJob(next);
  emit();
}

export function getActiveImportJob() {
  return activeJob;
}

export function subscribeImportJob(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export async function syncImportJobStatus() {
  const status = await api.getImportJobStatus();

  if (status.active && status.job) {
    const kind = normalizeKind(status.job.kind);
    setActiveJob({
      kind,
      label: status.job.label || labelOf(kind),
      fileName: status.job.file_name,
      startedAt: status.job.started_at,
    });
  } else {
    setActiveJob(null);
  }

  return activeJob;
}

export async function runImportJob(kind: ImportKind, file: File) {
  try {
    await syncImportJobStatus();
  } catch {
    // Keep the local state if the status check fails; the upload request will still validate on backend.
  }

  if (activeJob) {
    throw new Error(`Đang import ${activeJob.label}: ${activeJob.fileName}. Vui lòng chờ import hiện tại hoàn tất.`);
  }

  clearImportedDataCaches();

  const label = labelOf(kind);
  setActiveJob({
    kind,
    label,
    fileName: file.name,
    startedAt: new Date().toISOString(),
  });

  try {
    if (kind === 'patient') {
      await api.importPatientData(file);
    } else {
      await api.importDiseaseCodes(file);
    }

    addNotification({
      type: 'import',
      severity: 'info',
      title: `Import ${label} thành công`,
      description: file.name,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    addNotification({
      type: 'import',
      severity: 'critical',
      title: `Import ${label} thất bại`,
      description: `${file.name} - ${message}`,
    });
    throw error;
  } finally {
    try {
      await syncImportJobStatus();
    } catch {
      setActiveJob(null);
    }
  }
}
