import { useTranslation } from 'react-i18next';

function useVietnameseT() {
  const { i18n } = useTranslation();
  return i18n.getFixedT('vi');
}

const DECORATIVE_ANIMALS = [
  { icon: '🐻', className: 'left-[2%] top-[6%] text-7xl sm:text-8xl rotate-[-10deg] opacity-[0.52]' },
  { icon: '🐰', className: 'right-[3%] top-[7%] text-7xl sm:text-9xl rotate-[9deg] opacity-[0.52]' },
  { icon: '🦁', className: 'left-[1%] top-[28%] text-7xl sm:text-9xl rotate-[12deg] opacity-[0.50]' },
  { icon: '🐼', className: 'right-[2%] top-[31%] text-7xl sm:text-9xl rotate-[-11deg] opacity-[0.50]' },
  { icon: '🦊', className: 'left-[4%] bottom-[8%] text-7xl sm:text-9xl rotate-[8deg] opacity-[0.52]' },
  { icon: '🐨', className: 'right-[6%] bottom-[9%] text-7xl sm:text-9xl rotate-[-9deg] opacity-[0.52]' },
  { icon: '🐯', className: 'left-[15%] top-[2%] text-5xl sm:text-7xl rotate-[13deg] opacity-[0.45]' },
  { icon: '🐶', className: 'right-[17%] top-[3%] text-5xl sm:text-7xl rotate-[-13deg] opacity-[0.45]' },
  { icon: '🐱', className: 'left-[29%] top-[11%] text-5xl sm:text-7xl rotate-[-8deg] opacity-[0.43]' },
  { icon: '🐵', className: 'right-[29%] top-[12%] text-5xl sm:text-7xl rotate-[8deg] opacity-[0.43]' },
  { icon: '🐥', className: 'left-[45%] top-[4%] text-5xl sm:text-7xl rotate-[11deg] opacity-[0.44]' },
  { icon: '🐧', className: 'right-[44%] bottom-[3%] text-5xl sm:text-7xl rotate-[-11deg] opacity-[0.44]' },
  { icon: '🦄', className: 'left-[13%] top-[43%] text-5xl sm:text-7xl rotate-[-10deg] opacity-[0.40]' },
  { icon: '🐙', className: 'right-[13%] top-[47%] text-5xl sm:text-7xl rotate-[10deg] opacity-[0.40]' },
  { icon: '🐳', className: 'left-[18%] bottom-[25%] text-5xl sm:text-7xl rotate-[8deg] opacity-[0.41]' },
  { icon: '🐢', className: 'right-[19%] bottom-[24%] text-5xl sm:text-7xl rotate-[-8deg] opacity-[0.41]' },
  { icon: '🦒', className: 'left-[33%] top-[32%] text-5xl sm:text-6xl rotate-[12deg] opacity-[0.38]' },
  { icon: '🐘', className: 'right-[34%] top-[34%] text-5xl sm:text-6xl rotate-[-12deg] opacity-[0.38]' },
  { icon: '🦓', className: 'left-[30%] bottom-[13%] text-5xl sm:text-6xl rotate-[-9deg] opacity-[0.38]' },
  { icon: '🦋', className: 'right-[30%] bottom-[14%] text-5xl sm:text-6xl rotate-[9deg] opacity-[0.38]' },
  { icon: '🐹', className: 'left-[8%] top-[18%] text-4xl sm:text-6xl rotate-[12deg] opacity-[0.38]' },
  { icon: '🐸', className: 'right-[9%] top-[20%] text-4xl sm:text-6xl rotate-[-12deg] opacity-[0.38]' },
  { icon: '🐬', className: 'left-[7%] bottom-[33%] text-4xl sm:text-6xl rotate-[-7deg] opacity-[0.39]' },
  { icon: '🐞', className: 'right-[8%] bottom-[34%] text-4xl sm:text-6xl rotate-[7deg] opacity-[0.39]' },
  { icon: '🐝', className: 'left-[54%] top-[18%] text-4xl sm:text-6xl rotate-[-10deg] opacity-[0.36]' },
  { icon: '🐿️', className: 'left-[52%] bottom-[22%] text-4xl sm:text-6xl rotate-[10deg] opacity-[0.36]' },
  { icon: '🦉', className: 'left-[23%] top-[50%] text-4xl sm:text-6xl rotate-[8deg] opacity-[0.36]' },
  { icon: '🦔', className: 'right-[24%] top-[58%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.36]' },
  { icon: '🦜', className: 'left-[60%] top-[42%] text-4xl sm:text-6xl rotate-[14deg] opacity-[0.36]' },
  { icon: '🐴', className: 'right-[58%] bottom-[41%] text-4xl sm:text-6xl rotate-[-14deg] opacity-[0.36]' },
  { icon: '🦭', className: 'left-[40%] bottom-[49%] text-4xl sm:text-6xl rotate-[9deg] opacity-[0.34]' },
  { icon: '🐠', className: 'right-[41%] top-[72%] text-4xl sm:text-6xl rotate-[-9deg] opacity-[0.34]' },
  { icon: '🐛', className: 'left-[70%] bottom-[18%] text-3xl sm:text-5xl rotate-[13deg] opacity-[0.34]' },
  { icon: '🦀', className: 'left-[68%] top-[24%] text-3xl sm:text-5xl rotate-[-13deg] opacity-[0.34]' },
  { icon: '🐮', className: 'left-[6%] top-[58%] text-5xl sm:text-7xl rotate-[10deg] opacity-[0.43]' },
  { icon: '🐷', className: 'right-[7%] top-[61%] text-5xl sm:text-7xl rotate-[-10deg] opacity-[0.43]' },
  { icon: '🐭', className: 'left-[16%] top-[68%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.40]' },
  { icon: '🐺', className: 'right-[17%] top-[70%] text-4xl sm:text-6xl rotate-[8deg] opacity-[0.40]' },
  { icon: '🐗', className: 'left-[26%] top-[78%] text-4xl sm:text-6xl rotate-[12deg] opacity-[0.38]' },
  { icon: '🦌', className: 'right-[27%] top-[80%] text-4xl sm:text-6xl rotate-[-12deg] opacity-[0.38]' },
  { icon: '🦥', className: 'left-[48%] top-[84%] text-4xl sm:text-6xl rotate-[7deg] opacity-[0.37]' },
  { icon: '🦦', className: 'right-[48%] top-[83%] text-4xl sm:text-6xl rotate-[-7deg] opacity-[0.37]' },
  { icon: '🦩', className: 'left-[76%] top-[49%] text-4xl sm:text-6xl rotate-[12deg] opacity-[0.38]' },
  { icon: '🦚', className: 'right-[75%] top-[39%] text-4xl sm:text-6xl rotate-[-12deg] opacity-[0.38]' },
  { icon: '🐊', className: 'left-[78%] bottom-[7%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.38]' },
  { icon: '🦎', className: 'right-[78%] bottom-[17%] text-4xl sm:text-6xl rotate-[8deg] opacity-[0.38]' },
  { icon: '🐟', className: 'left-[57%] bottom-[9%] text-3xl sm:text-5xl rotate-[14deg] opacity-[0.36]' },
  { icon: '🦆', className: 'right-[56%] top-[9%] text-3xl sm:text-5xl rotate-[-14deg] opacity-[0.36]' },
  { icon: '🐌', className: 'left-[12%] bottom-[45%] text-3xl sm:text-5xl rotate-[9deg] opacity-[0.36]' },
  { icon: '🦇', className: 'right-[12%] bottom-[47%] text-3xl sm:text-5xl rotate-[-9deg] opacity-[0.34]' },
] as const;

const DECORATIVE_PLAYFUL = [
  { icon: '🧸', className: 'left-[22%] top-[23%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.36]' },
  { icon: '🌈', className: 'right-[22%] top-[26%] text-4xl sm:text-6xl rotate-[8deg] opacity-[0.38]' },
  { icon: '🎈', className: 'left-[42%] top-[21%] text-4xl sm:text-6xl rotate-[9deg] opacity-[0.36]' },
  { icon: '🎈', className: 'left-[5%] top-[42%] text-5xl sm:text-7xl rotate-[-13deg] opacity-[0.42]' },
  { icon: '🎈', className: 'right-[5%] top-[44%] text-5xl sm:text-7xl rotate-[13deg] opacity-[0.42]' },
  { icon: '🎈', className: 'left-[55%] top-[58%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.38]' },
  { icon: '⭐', className: 'right-[44%] top-[51%] text-4xl sm:text-6xl rotate-[-9deg] opacity-[0.36]' },
  { icon: '☁️', className: 'left-[24%] bottom-[5%] text-4xl sm:text-6xl rotate-[6deg] opacity-[0.38]' },
  { icon: '🌤️', className: 'right-[23%] bottom-[5%] text-4xl sm:text-6xl rotate-[-6deg] opacity-[0.38]' },
  { icon: '💛', className: 'left-[40%] bottom-[34%] text-3xl sm:text-5xl rotate-[12deg] opacity-[0.34]' },
  { icon: '💙', className: 'right-[40%] bottom-[34%] text-3xl sm:text-5xl rotate-[-12deg] opacity-[0.34]' },
  { icon: '🎨', className: 'left-[63%] top-[8%] text-3xl sm:text-5xl rotate-[12deg] opacity-[0.33]' },
  { icon: '🧩', className: 'left-[37%] top-[7%] text-3xl sm:text-5xl rotate-[-12deg] opacity-[0.33]' },
  { icon: '🧩', className: 'right-[33%] top-[43%] text-4xl sm:text-6xl rotate-[10deg] opacity-[0.36]' },
  { icon: '🎲', className: 'left-[34%] bottom-[27%] text-4xl sm:text-6xl rotate-[-11deg] opacity-[0.38]' },
  { icon: '🪅', className: 'right-[36%] bottom-[27%] text-4xl sm:text-6xl rotate-[11deg] opacity-[0.38]' },
  { icon: '🪄', className: 'left-[31%] top-[61%] text-3xl sm:text-5xl rotate-[22deg] opacity-[0.35]' },
  { icon: '🪆', className: 'right-[31%] top-[62%] text-3xl sm:text-5xl rotate-[-12deg] opacity-[0.35]' },
  { icon: '🚂', className: 'left-[9%] bottom-[20%] text-4xl sm:text-6xl rotate-[8deg] opacity-[0.43]' },
  { icon: '🚗', className: 'right-[10%] bottom-[21%] text-4xl sm:text-6xl rotate-[-8deg] opacity-[0.43]' },
  { icon: '🧃', className: 'left-[59%] bottom-[31%] text-3xl sm:text-5xl rotate-[9deg] opacity-[0.34]' },
  { icon: '⚽', className: 'right-[60%] top-[24%] text-3xl sm:text-5xl rotate-[-9deg] opacity-[0.35]' },
  { icon: '🎁', className: 'left-[80%] top-[26%] text-4xl sm:text-6xl rotate-[9deg] opacity-[0.36]' },
  { icon: '🎮', className: 'right-[81%] top-[30%] text-4xl sm:text-6xl rotate-[-9deg] opacity-[0.34]' },
  { icon: '🍭', className: 'left-[44%] bottom-[7%] text-3xl sm:text-5xl rotate-[8deg] opacity-[0.33]' },
  { icon: '🍼', className: 'right-[37%] bottom-[8%] text-3xl sm:text-5xl rotate-[-8deg] opacity-[0.33]' },
  { icon: '🪁', className: 'left-[72%] top-[12%] text-3xl sm:text-5xl rotate-[16deg] opacity-[0.32]' },
  { icon: '🎠', className: 'left-[72%] bottom-[36%] text-3xl sm:text-5xl rotate-[-12deg] opacity-[0.32]' },
  { icon: '🪀', className: 'right-[70%] top-[67%] text-3xl sm:text-5xl rotate-[12deg] opacity-[0.32]' },
  { icon: '🛝', className: 'right-[67%] bottom-[7%] text-3xl sm:text-5xl rotate-[-10deg] opacity-[0.32]' },
  { icon: '🎀', className: 'left-[9%] top-[10%] text-4xl sm:text-6xl rotate-[-14deg] opacity-[0.46]' },
  { icon: '🎀', className: 'right-[11%] top-[13%] text-4xl sm:text-6xl rotate-[14deg] opacity-[0.46]' },
  { icon: '🎀', className: 'left-[20%] bottom-[38%] text-3xl sm:text-5xl rotate-[10deg] opacity-[0.42]' },
  { icon: '🎀', className: 'right-[21%] bottom-[37%] text-3xl sm:text-5xl rotate-[-10deg] opacity-[0.42]' },
  { icon: '🎀', className: 'left-[49%] top-[15%] text-3xl sm:text-5xl rotate-[7deg] opacity-[0.38]' },
  { icon: '🎀', className: 'right-[50%] bottom-[16%] text-3xl sm:text-5xl rotate-[-7deg] opacity-[0.38]' },
] as const;

const DECORATIVE_ITEMS = [
  { icon: DECORATIVE_ANIMALS[0].icon, className: 'left-[1.5%] top-[7%] text-5xl rotate-[-10deg] opacity-[0.44]' },
  { icon: DECORATIVE_PLAYFUL[19].icon, className: 'right-[1.5%] top-[8%] text-5xl rotate-[12deg] opacity-[0.42]' },
  { icon: DECORATIVE_PLAYFUL[3].icon, className: 'left-[7%] top-[17%] text-5xl rotate-[8deg] opacity-[0.42]' },
  { icon: DECORATIVE_ANIMALS[3].icon, className: 'right-[7%] top-[18%] text-5xl rotate-[-10deg] opacity-[0.43]' },
  { icon: DECORATIVE_PLAYFUL[22].icon, className: 'left-[1.8%] top-[29%] text-5xl rotate-[-8deg] opacity-[0.40]' },
  { icon: DECORATIVE_PLAYFUL[23].icon, className: 'right-[2%] top-[30%] text-5xl rotate-[8deg] opacity-[0.40]' },
  { icon: DECORATIVE_ANIMALS[4].icon, className: 'left-[7%] top-[42%] text-5xl rotate-[10deg] opacity-[0.43]' },
  { icon: DECORATIVE_PLAYFUL[15].icon, className: 'right-[7%] top-[43%] text-5xl rotate-[-9deg] opacity-[0.40]' },
  { icon: DECORATIVE_PLAYFUL[12].icon, className: 'left-[1.8%] top-[55%] text-5xl rotate-[11deg] opacity-[0.38]' },
  { icon: DECORATIVE_ANIMALS[5].icon, className: 'right-[1.8%] top-[56%] text-5xl rotate-[-9deg] opacity-[0.42]' },
  { icon: DECORATIVE_PLAYFUL[25].icon, className: 'left-[7%] top-[68%] text-4xl rotate-[-12deg] opacity-[0.38]' },
  { icon: DECORATIVE_PLAYFUL[29].icon, className: 'right-[7%] top-[69%] text-4xl rotate-[12deg] opacity-[0.38]' },
  { icon: DECORATIVE_PLAYFUL[18].icon, className: 'left-[2%] top-[82%] text-5xl rotate-[7deg] opacity-[0.40]' },
  { icon: DECORATIVE_PLAYFUL[17].icon, className: 'right-[2%] top-[83%] text-5xl rotate-[-7deg] opacity-[0.40]' },
] as const;

const DECORATIVE_BUBBLES = [
  'left-[1.5%] top-[13%] h-10 w-10 border-sky-200/70 bg-sky-100/35',
  'left-[8.5%] top-[25%] h-7 w-7 border-rose-200/70 bg-rose-100/35',
  'left-[2%] top-[39%] h-12 w-12 border-teal-200/70 bg-teal-100/35',
  'left-[8%] top-[52%] h-8 w-8 border-amber-200/70 bg-amber-100/35',
  'left-[2%] top-[66%] h-9 w-9 border-fuchsia-200/60 bg-fuchsia-100/30',
  'left-[8%] top-[78%] h-6 w-6 border-sky-200/60 bg-white/35',
  'right-[1.5%] top-[14%] h-11 w-11 border-rose-200/70 bg-rose-100/35',
  'right-[8.5%] top-[27%] h-8 w-8 border-teal-200/70 bg-teal-100/35',
  'right-[2%] top-[41%] h-12 w-12 border-amber-200/70 bg-white/40',
  'right-[8%] top-[54%] h-7 w-7 border-sky-200/70 bg-sky-100/35',
  'right-[2%] top-[68%] h-10 w-10 border-fuchsia-200/65 bg-fuchsia-100/30',
  'right-[8%] top-[80%] h-6 w-6 border-sky-200/70 bg-sky-100/35',
] as const;

export function HospitalBrandBadge() {
  const t = useVietnameseT();

  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-white bg-white/90 py-2 pl-2 pr-4 shadow-md shadow-sky-100 backdrop-blur">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 via-cyan-400 to-teal-400 text-xl shadow-sm ring-2 ring-white">
        <span aria-hidden="true">🏥</span>
      </div>
      <div>
        <p className="text-xs font-black uppercase tracking-wide text-sky-600">{t('parent.brand.portal')}</p>
        <p className="bg-gradient-to-r from-sky-700 via-teal-600 to-amber-500 bg-clip-text text-base font-black text-transparent">
          {t('brand.name')}
        </p>
      </div>
    </div>
  );
}

export function PersonalBrandBadge() {
  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-white bg-white/90 py-2 pl-2 pr-4 shadow-md shadow-fuchsia-100 backdrop-blur">
      <div className="relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-fuchsia-100 via-white to-sky-100 text-xl shadow-sm ring-2 ring-white">
        <span aria-hidden="true">🦊</span>
        <img
          src="/parent-brand-logo-round.png"
          alt="Lightning Fox SD"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.display = 'none';
          }}
        />
      </div>
      <div>
        <p className="text-xs font-black uppercase tracking-wide text-fuchsia-600">Phát triển bởi</p>
        <p className="bg-gradient-to-r from-fuchsia-700 via-sky-600 to-teal-500 bg-clip-text text-base font-black text-transparent">
          Lightning Fox SD
        </p>
      </div>
    </div>
  );
}

export function ParentBrandFooter() {
  return (
    <footer className="mt-6 overflow-hidden rounded-[28px] border border-white/90 bg-white/88 shadow-lg shadow-sky-100/60 backdrop-blur">
      <div className="grid items-center gap-6 px-5 py-5 md:grid-cols-[96px_1fr_460px] lg:px-7">
        <div className="relative flex h-[88px] w-[88px] items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-sky-50 via-white to-amber-50 shadow-md ring-1 ring-sky-100">
          <span className="text-2xl" aria-hidden="true">🦊</span>
          <img
            src="/parent-brand-logo-round.png"
            alt="Logo Lightning Fox SD"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(event) => {
              event.currentTarget.style.display = 'none';
            }}
          />
        </div>

        <div className="min-w-0">
          <p className="text-xl font-black text-sky-950">Lightning Fox SD</p>
          <p className="mt-1 text-sm font-black text-orange-500">
            Theo dõi sớm · Chăm sóc nhẹ nhàng · Đồng hành cùng bé
          </p>
          <p className="mt-2 text-sm font-semibold leading-6 text-slate-600">
            Dự án thực tập tốt nghiệp tại <strong className="text-sky-800">Bệnh viện Nhi Đồng 2</strong>
          </p>
        </div>

        <div className="relative flex h-40 items-center justify-center overflow-hidden rounded-2xl border border-sky-100 bg-white/80 px-2 py-2">
          <span className="text-center text-xs font-bold text-slate-400">
            Lightning Fox SD
          </span>
          <img
            src="/parent-brand-logo-wide.png"
            alt="Lightning Fox SD - Fast, Optimized, eXcellence"
            className="absolute inset-0 h-full w-full object-contain p-1"
            onError={(event) => {
              event.currentTarget.style.display = 'none';
            }}
          />
        </div>
      </div>
      <div className="border-t border-sky-100 bg-gradient-to-r from-sky-50 via-white to-amber-50 px-5 py-2.5 text-center text-xs font-semibold text-slate-500">
        Theo dõi sớm · Chăm sóc nhẹ nhàng · Đồng hành cùng bé
      </div>
    </footer>
  );
}

export function DecorativeBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
      <div className="absolute -left-16 top-20 h-72 w-72 rounded-full bg-sky-200/70 blur-3xl" />
      <div className="absolute right-0 top-8 h-80 w-80 rounded-full bg-amber-200/70 blur-3xl" />
      <div className="absolute bottom-0 left-1/3 h-96 w-96 rounded-full bg-teal-200/65 blur-3xl" />
      <div className="absolute bottom-1/4 right-1/4 h-72 w-72 rounded-full bg-rose-200/55 blur-3xl" />
      <div className="absolute left-1/2 top-1/3 h-80 w-80 -translate-x-1/2 rounded-full bg-fuchsia-100/50 blur-3xl" />

      {DECORATIVE_ITEMS.map((item, index) => (
        <div
          key={`${item.icon}-${index}`}
          className={`absolute hidden select-none drop-shadow-[0_16px_26px_rgba(15,23,42,0.20)] 2xl:block ${item.className}`}
        >
          <span className="rounded-[2rem] bg-white/55 px-2.5 py-1.5 backdrop-blur-[1px] ring-1 ring-white/75">
            {item.icon}
          </span>
        </div>
      ))}

      {DECORATIVE_BUBBLES.map((className, index) => (
        <div
          key={`bubble-${index}`}
          className={`absolute hidden rounded-full border-2 shadow-[inset_10px_10px_18px_rgba(255,255,255,0.75),0_16px_28px_rgba(14,116,144,0.12)] backdrop-blur-[1px] 2xl:block ${className}`}
        >
          <span className="absolute left-2 top-2 h-2 w-2 rounded-full bg-white/80" />
        </div>
      ))}

      <div className="absolute left-[1.5%] top-[5%] hidden h-10 w-10 rounded-full border-4 border-sky-200/45 2xl:block" />
      <div className="absolute right-[1.5%] top-[6%] hidden h-7 w-7 rounded-full border-4 border-teal-200/45 2xl:block" />
      <div className="absolute bottom-[24%] right-[4%] hidden h-12 w-12 rounded-full border-4 border-amber-200/50 2xl:block" />
      <div className="absolute bottom-[16%] left-[4%] hidden h-5 w-16 rotate-[-18deg] rounded-full bg-rose-100/50 2xl:block" />
      <div className="absolute left-[7%] top-[36%] hidden h-8 w-8 rounded-full border-4 border-rose-200/35 2xl:block" />
      <div className="absolute right-[7%] top-[48%] hidden h-9 w-9 rounded-full border-4 border-sky-200/35 2xl:block" />
      <div className="absolute left-[2%] top-[72%] hidden h-4 w-14 rotate-[16deg] rounded-full bg-teal-100/45 2xl:block" />
      <div className="absolute right-[2%] top-[72%] hidden h-4 w-14 rotate-[-16deg] rounded-full bg-amber-100/50 2xl:block" />
    </div>
  );
}
