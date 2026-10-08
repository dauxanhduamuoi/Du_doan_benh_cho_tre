import { useTranslation } from 'react-i18next';

export function HospitalBrandBadge() {
  const { i18n } = useTranslation();
  const t = i18n.getFixedT('vi');
  return (
    <div>
      <p className="text-sm font-medium text-teal-800">{t('brand.name')}</p>
      <p className="mt-1 text-sm text-slate-500">{t('parent.brand.portal')}</p>
    </div>
  );
}

export function ParentBrandFooter() {
  return (
    <footer className="mt-8 flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-4 text-sm leading-6 text-slate-500">
      <p>Bệnh viện Nhi Đồng 2 · Cổng sức khỏe phụ huynh</p>
    </footer>
  );
}
