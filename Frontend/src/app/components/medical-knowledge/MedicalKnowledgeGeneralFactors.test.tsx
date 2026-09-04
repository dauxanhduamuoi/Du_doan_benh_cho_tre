import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  factorIsComplete,
  factorLabel,
  factorOptionId,
  factorTopicKey,
  makeFactorSelector,
  type ExplanationFactorOption,
  type MedicalFactorSelector,
} from '@/lib/medicalKnowledgeFactors';
import PubMedSearchForm from './PubMedSearchForm';
import MedicalTopicSourceLibrary from './MedicalTopicSourceLibrary';

const factors: ExplanationFactorOption[] = [
  { type: 'AGE', key: 'age_group', label_vi: 'Độ tuổi', values: ['1-5 tuổi', '6-10 tuổi'] },
  { type: 'SEX', key: 'gender', label_vi: 'Giới tính', values: ['Nam', 'Nữ'] },
  { type: 'SEASONALITY', key: 'time_of_year', label_vi: 'Thời điểm trong năm / tính mùa vụ', values: [] },
  { type: 'WEATHER', key: 'temperature', label_vi: 'Nhiệt độ', values: [] },
  { type: 'WEATHER', key: 'humidity', label_vi: 'Độ ẩm', values: [] },
  { type: 'WEATHER', key: 'precipitation', label_vi: 'Mưa / lượng mưa', values: [] },
  { type: 'WEATHER', key: 'wind', label_vi: 'Gió', values: [] },
  { type: 'WEATHER', key: 'weather_condition', label_vi: 'Điều kiện thời tiết', values: [] },
];

function props(overrides: Record<string, unknown> = {}) {
  return {
    diseaseGroups: [{ id: '5', name: 'Gastroenteritis' }],
    factorOptions: factors,
    diseaseGroupId: '5',
    factor: makeFactorSelector(factors[5]),
    searchMode: 'GUIDED' as const,
    freeQuery: '',
    diseaseTerms: ['gastroenteritis'],
    defaultDiseaseTerm: 'gastroenteritis',
    maxResults: 10 as const,
    yearFrom: null,
    yearTo: null,
    loading: false,
    pmid: '',
    pmidLoading: false,
    onDiseaseGroupChange: vi.fn(),
    onFactorChange: vi.fn(),
    onSearchModeChange: vi.fn(),
    onFreeQueryChange: vi.fn(),
    onDiseaseTermsChange: vi.fn(),
    onMaxResultsChange: vi.fn(),
    onYearFromChange: vi.fn(),
    onYearToChange: vi.fn(),
    onSubmit: vi.fn(),
    onPmidChange: vi.fn(),
    onPmidLookup: vi.fn(),
    ...overrides,
  };
}

describe('general Medical Knowledge factor catalog', () => {
  it.each([
    [{ factor_type: 'AGE', factor_key: 'age_group', factor_value: '1-5 tuổi' }, 'Độ tuổi — 1-5 tuổi'],
    [{ factor_type: 'SEX', factor_key: 'gender', factor_value: 'Nam' }, 'Giới tính — Nam'],
    [{ factor_type: 'SEASONALITY', factor_key: 'time_of_year', factor_value: null }, 'Tính mùa vụ'],
    [{ factor_type: 'WEATHER', factor_key: 'temperature', factor_value: null }, 'Nhiệt độ'],
    [{ factor_type: 'WEATHER', factor_key: 'humidity', factor_value: null }, 'Độ ẩm'],
    [{ factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null }, 'Mưa / lượng mưa'],
    [{ factor_type: 'WEATHER', factor_key: 'wind', factor_value: null }, 'Gió'],
    [{ factor_type: 'WEATHER', factor_key: 'weather_condition', factor_value: null }, 'Điều kiện thời tiết'],
  ] as const)('renders a parent/staff label without raw enum names', (factor, label) => {
    expect(factorLabel(factor as MedicalFactorSelector)).toBe(label);
  });

  it.each(factors)('has a stable canonical option id for $type/$key', (factor) => {
    expect(factorOptionId(factor)).toBe(`${factor.type}:${factor.key}`);
  });

  it.each([
    ['1-5 tuổi', '6-10 tuổi'],
    ['Nam', 'Nữ'],
    [null, '1-5 tuổi'],
    [null, null],
  ])('keeps topic identity value-scoped (%s versus %s)', (left, right) => {
    const type = left === 'Nam' || right === 'Nữ' ? 'SEX' : 'AGE';
    const key = type === 'SEX' ? 'gender' : 'age_group';
    const a = factorTopicKey('5', { factor_type: type, factor_key: key, factor_value: left });
    const b = factorTopicKey(type === 'AGE' && left === null && right === null ? '6' : '5', {
      factor_type: type,
      factor_key: key,
      factor_value: right,
    });
    expect(a).not.toBe(b);
  });

  it('requires an exact value for AGE and SEX but not seasonality/weather', () => {
    expect(factorIsComplete(makeFactorSelector(factors[0]))).toBe(false);
    expect(factorIsComplete(makeFactorSelector(factors[1]))).toBe(false);
    expect(factorIsComplete(makeFactorSelector(factors[2]))).toBe(true);
    expect(factorIsComplete(makeFactorSelector(factors[3]))).toBe(true);
  });
});

describe('general factor PubMed search form', () => {
  it('renders the grouped explanation-factor selector and all required categories', () => {
    render(<PubMedSearchForm {...props()} />);
    expect(screen.getByLabelText('2. Yếu tố cần giải thích')).toBeVisible();
    expect(screen.getByRole('group', { name: 'Đặc điểm trẻ' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Thời gian' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Thời tiết' })).toBeInTheDocument();
  });

  it('shows exact deployed age values for AGE', () => {
    render(<PubMedSearchForm {...props({ factor: makeFactorSelector(factors[0]) })} />);
    expect(screen.getByLabelText('Nhóm tuổi cần giải thích')).toBeVisible();
    expect(screen.getByRole('option', { name: '1-5 tuổi' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '6-10 tuổi' })).toBeInTheDocument();
  });

  it('shows exact deployed sex values for SEX', () => {
    render(<PubMedSearchForm {...props({ factor: makeFactorSelector(factors[1]) })} />);
    expect(screen.getByLabelText('Giới tính cần giải thích')).toBeVisible();
    expect(screen.getByRole('option', { name: 'Nam' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Nữ' })).toBeInTheDocument();
  });

  it('does not invent a value selector for SEASONALITY', () => {
    render(<PubMedSearchForm {...props({ factor: makeFactorSelector(factors[2]) })} />);
    expect(screen.queryByLabelText('Nhóm tuổi cần giải thích')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Giới tính cần giải thích')).not.toBeInTheDocument();
  });

  it('keeps the existing weather UX as one factor selector', () => {
    render(<PubMedSearchForm {...props()} />);
    expect(screen.getByLabelText('2. Yếu tố cần giải thích')).toHaveValue('WEATHER:precipitation');
    expect(screen.queryByText('Giá trị thời tiết')).not.toBeInTheDocument();
  });

  it('clears incompatible values through a fresh selector when factor changes', () => {
    const onFactorChange = vi.fn();
    render(<PubMedSearchForm {...props({
      factor: { ...makeFactorSelector(factors[0]), factor_value: '1-5 tuổi' },
      onFactorChange,
    })} />);
    fireEvent.change(screen.getByLabelText('2. Yếu tố cần giải thích'), { target: { value: 'SEX:gender' } });
    expect(onFactorChange).toHaveBeenCalledWith({
      factor_type: 'SEX', factor_key: 'gender', factor_value: null, weather_factor: null,
    });
  });

  it('switches to Free mode without removing valid PubMed syntax', () => {
    const onSearchModeChange = vi.fn();
    const onFreeQueryChange = vi.fn();
    render(<PubMedSearchForm {...props({ searchMode: 'FREE', onSearchModeChange, onFreeQueryChange })} />);
    const query = '("sex differences"[Title/Abstract]) AND child';
    fireEvent.change(screen.getByLabelText('Truy vấn PubMed tự do'), { target: { value: query } });
    expect(onFreeQueryChange).toHaveBeenCalledWith(query);
    fireEvent.click(screen.getByRole('button', { name: 'Tìm có hướng dẫn' }));
    expect(onSearchModeChange).toHaveBeenCalledWith('GUIDED');
  });

  it('keeps guided pediatric/factor summary visible', () => {
    render(<PubMedSearchForm {...props()} />);
    expect(screen.getByText(/tự thêm phạm vi trẻ em và từ khóa phù hợp với yếu tố/)).toBeVisible();
  });

  it('keeps Direct PMID lookup available for every complete topic', () => {
    render(<PubMedSearchForm {...props()} />);
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    expect(screen.getByLabelText('Tìm trực tiếp bằng PMID')).toBeVisible();
  });

  it('disables search until an AGE value is selected', () => {
    const { rerender } = render(<PubMedSearchForm {...props({ factor: makeFactorSelector(factors[0]) })} />);
    expect(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' })).toBeDisabled();
    rerender(<PubMedSearchForm {...props({ factor: { ...makeFactorSelector(factors[0]), factor_value: '1-5 tuổi' } })} />);
    expect(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' })).toBeEnabled();
  });

  it('shows the generic topic label in the source library', () => {
    render(<MedicalTopicSourceLibrary diseaseName="Gastroenteritis" factorLabel="Độ tuổi — 1-5 tuổi" library={{
      topic_id: null,
      disease_group_id: '5',
      factor_type: 'AGE',
      factor_key: 'age_group',
      factor_value: '1-5 tuổi',
      weather_factor: null,
      sources: [],
    }} loading={false} selectedSourceIds={new Set()} onToggle={vi.fn()}
      onSelectAllUsable={vi.fn()} selectionNotice={null} />);
    expect(screen.getByText('Gastroenteritis — Độ tuổi — 1-5 tuổi')).toBeVisible();
  });
});
