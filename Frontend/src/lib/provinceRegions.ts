export type ProvinceRegionCode = 'north' | 'central' | 'south';

export interface ProvinceRegionRecord {
  province_code: string;
  province_name: string;
  mien_code: ProvinceRegionCode;
  mien: string;
  aliases?: string[];
}

export async function loadProvinceRegions(): Promise<ProvinceRegionRecord[]> {
  const response = await fetch('/api/areas/province-regions', { cache: 'no-cache' });
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(`Không đọc được file phân miền tỉnh/thành: ${response.status}`);
  }

  const rows = (await response.json()) as ProvinceRegionRecord[];
  return rows.map((row) => ({
    province_code: String(row.province_code ?? '').trim(),
    province_name: String(row.province_name ?? '').trim(),
    mien_code: row.mien_code,
    mien: String(row.mien ?? '').trim(),
    aliases: Array.isArray(row.aliases) ? row.aliases.map((alias) => String(alias).trim()).filter(Boolean) : [],
  }));
}
