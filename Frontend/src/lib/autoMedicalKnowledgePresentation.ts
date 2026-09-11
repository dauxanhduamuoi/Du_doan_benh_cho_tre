import type {
  AutoMedicalKnowledgeJobStatus,
  AutoMedicalKnowledgeRevision,
} from './medicalKnowledgeApi';

export type AutoStatusTone = 'success' | 'warning' | 'danger' | 'processing' | 'neutral';

export interface AutoStatusPresentation {
  label: string;
  description: string;
  tone: AutoStatusTone;
}

export const AUTO_STATUS_PRESENTATIONS: Record<
  AutoMedicalKnowledgeJobStatus,
  AutoStatusPresentation
> = {
  QUEUED: {
    label: 'Đang chờ',
    description: 'Chủ đề đang chờ đến lượt xử lý.',
    tone: 'processing',
  },
  SEARCHING: {
    label: 'Đang tìm tài liệu',
    description: 'Hệ thống đang tìm nguồn y khoa phù hợp.',
    tone: 'processing',
  },
  GENERATING: {
    label: 'Đang tạo giải thích',
    description: 'Hệ thống đang tổng hợp giải thích từ nguồn đã chọn.',
    tone: 'processing',
  },
  READY: {
    label: 'Hoàn thành',
    description: 'Nội dung Auto đã hoàn thành các bước kiểm tra hiện hành.',
    tone: 'success',
  },
  INSUFFICIENT: {
    label: 'Chưa đủ bằng chứng',
    description: 'Chưa có đủ nguồn phù hợp để tạo nội dung an toàn.',
    tone: 'warning',
  },
  FAILED: {
    label: 'Có lỗi',
    description: 'Quá trình tạo giải thích chưa hoàn thành.',
    tone: 'danger',
  },
  CANCELLED: {
    label: 'Đã dừng',
    description: 'Lần xử lý này đã dừng.',
    tone: 'neutral',
  },
};

export const AUTO_STATUS_TONE_CLASSES: Record<AutoStatusTone, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  danger: 'border-red-200 bg-red-50 text-red-800',
  processing: 'border-blue-200 bg-blue-50 text-blue-800',
  neutral: 'border-slate-200 bg-slate-100 text-slate-700',
};

export function getAutoTierPresentation(
  revision: AutoMedicalKnowledgeRevision,
): { label: string; method: string } | null {
  if (revision.generation_status !== 'READY') return null;
  const tier = revision.auto_tier
    ?? (revision.generation_mode === 'SAFE_FALLBACK' ? 'BASIC' : 'STRICT');
  return {
    label: tier === 'BASIC'
      ? 'Tự động – Giải thích cơ bản'
      : 'Tự động – Kiểm tra nâng cao',
    method: revision.generation_method === 'SAFE_TEMPLATE'
      || revision.generation_mode === 'SAFE_FALLBACK'
      ? 'Bản rút gọn an toàn'
      : 'AI',
  };
}

export function normalizeAutoSearch(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\u2010-\u2015]/g, '-')
    .toLocaleLowerCase('vi')
    .trim();
}
