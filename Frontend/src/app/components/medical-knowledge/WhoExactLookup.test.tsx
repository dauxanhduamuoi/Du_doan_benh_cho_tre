import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import type { MedicalFactorSelector } from '@/lib/medicalKnowledgeFactors';
import WhoExactLookup from './WhoExactLookup';

const mocks = vi.hoisted(() => ({ lookup: vi.fn(), importSources: vi.fn() }));
vi.mock('@/lib/medicalKnowledgeApi', () => ({
  lookupMedicalEvidenceExact: mocks.lookup, importMedicalEvidenceProviderSources: mocks.importSources,
}));
const id = '69e416c8-c71b-4e2b-839b-c6f44d59cc2f';
const weatherSelector = (key: string): MedicalFactorSelector => ({
  factor_type: 'WEATHER', factor_key: key, factor_value: null, weather_factor: key,
});
const source = { provider_id: 'WHO', external_id: id, title: 'Unrelated WHO policy',
  source_kind: 'GUIDELINE', url: 'https://www.who.int/publications/i/item/123',
  authors: null, publisher_or_journal: null, publication_date: null, publication_year: null, doi: null,
  abstract_text: null, usable_for_draft: false, in_topic_library: false, relevance: 'EXACT_LOOKUP' };
const makeProps = () => ({ diseaseGroupId: '9', factor: weatherSelector('humidity'), disabled: false,
  onStart: vi.fn(), onBusyChange: vi.fn(), onImported: vi.fn().mockResolvedValue(undefined) });
function submit(value = id) {
  fireEvent.click(screen.getByText('Tìm chính xác ấn phẩm WHO'));
  fireEvent.change(screen.getByLabelText('GUID của ấn phẩm WHO'), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'Tìm theo GUID WHO' }));
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.lookup.mockResolvedValue({ lookup_mode: 'EXACT', requested_identifier: id, result: source });
  mocks.importSources.mockResolvedValue({ sources: [{ ...source, source_id: 17, outcome: 'ADDED_REFERENCE_ONLY' }] });
});

describe('WHO exact GUID workflow', () => {
  it('keeps an unrelated exact record visible and imports its exact identity as a reference', async () => {
    const props = makeProps();
    render(<WhoExactLookup {...props} />);
    submit();
    expect(await screen.findByText('Unrelated WHO policy')).toBeInTheDocument();
    expect(screen.getByText(/không đồng nghĩa đủ điều kiện/)).toBeInTheDocument();
    expect(mocks.lookup).toHaveBeenCalledWith('WHO', id, '9', weatherSelector('humidity'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm ấn phẩm WHO vào kho chủ đề' }));
    await waitFor(() => expect(props.onImported).toHaveBeenCalledTimes(1));
    expect(mocks.importSources.mock.calls[0][2]).toEqual([{
      provider_id: 'WHO', external_id: id, canonical_url: source.url, title: source.title, source_kind: 'GUIDELINE',
      authors: null, publisher_or_journal: null, publication_date: null, publication_year: null, doi: null,
    }]);
    expect(screen.getByRole('button', { name: 'Đã có trong kho chủ đề' })).toBeDisabled();
  });

  it.each(['73164', 'https://www.who.int/publications/b/73164', 'https://evil.test/x'])(
    'rejects unsupported %s without network fallback', value => {
      render(<WhoExactLookup {...makeProps()} />);
      submit(value);
      expect(screen.getByRole('alert')).toHaveTextContent('Chưa hỗ trợ');
      expect(mocks.lookup).not.toHaveBeenCalled();
    });

  it('does not render a substituted identity', async () => {
    mocks.lookup.mockResolvedValue({ lookup_mode: 'EXACT', requested_identifier: id,
      result: { ...source, external_id: '742f074f-d820-4d95-a48d-054513c6bc73' } });
    render(<WhoExactLookup {...makeProps()} />);
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Không thể xác minh');
    expect(screen.queryByText(source.title)).not.toBeInTheDocument();
  });

  it('reports not found without substituting a source', async () => {
    mocks.lookup.mockRejectedValue(new ApiError(404, 'NOT_FOUND'));
    render(<WhoExactLookup {...makeProps()} />);
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy');
    expect(mocks.lookup).toHaveBeenCalledTimes(1);
  });

  it('does not mark a failed import as stored', async () => {
    mocks.importSources.mockResolvedValue({ sources: [{ ...source, source_id: null, outcome: 'PROVIDER_ERROR' }] });
    render(<WhoExactLookup {...makeProps()} />);
    submit();
    await screen.findByText(source.title);
    fireEvent.click(screen.getByRole('button', { name: 'Thêm ấn phẩm WHO vào kho chủ đề' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Chưa thêm được');
    expect(screen.getByRole('button', { name: 'Thêm ấn phẩm WHO vào kho chủ đề' })).toBeEnabled();
  });

  it('drops pending results when topic changes/remounts', async () => {
    let resolve!: (value: unknown) => void;
    mocks.lookup.mockReturnValue(new Promise(value => { resolve = value; }));
    const props = makeProps();
    const view = render(<WhoExactLookup key="first" {...props} />);
    submit();
    expect(screen.getByRole('button', { name: 'Đang xử lý…' })).toBeDisabled();
    view.rerender(<WhoExactLookup key="second" {...props} diseaseGroupId="1" />);
    await act(async () => resolve({ lookup_mode: 'EXACT', requested_identifier: id, result: source }));
    expect(screen.queryByText(source.title)).not.toBeInTheDocument();
    expect(props.onBusyChange).toHaveBeenLastCalledWith(false);
  });
});
