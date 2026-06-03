import { Loader2 } from 'lucide-react';
import { useT } from '@/lib/i18n';

export default function LoadingFallback({ fullPage = false }: { fullPage?: boolean }) {
  const t = useT();

  return (
    <div className={`${fullPage ? 'min-h-screen' : 'min-h-[320px]'} flex items-center justify-center bg-slate-50`}>
      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
        <Loader2 className="animate-spin" size={18} />
        <span>{t('common.loading')}</span>
      </div>
    </div>
  );
}
