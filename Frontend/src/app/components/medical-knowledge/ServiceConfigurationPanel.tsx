import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Loader2, Settings2, Sparkles } from 'lucide-react';
import {
  getMedicalKnowledgeServiceStatus,
  serviceConfigurationErrorMessage,
  testLlmConnection,
  testPubMedConnection,
  type MedicalKnowledgeServiceStatus,
} from '@/lib/medicalKnowledgeApi';

type TestState = { kind: 'success' | 'error'; message: string } | null;

function StatusLine({ configured, yes, no }: { configured: boolean; yes: string; no: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${configured ? 'text-emerald-700' : 'text-amber-700'}`}>
      {configured ? <CheckCircle2 aria-hidden size={16} /> : <AlertTriangle aria-hidden size={16} />}
      {configured ? yes : no}
    </span>
  );
}

export default function ServiceConfigurationPanel() {
  const [status, setStatus] = useState<MedicalKnowledgeServiceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [pubmedTesting, setPubmedTesting] = useState(false);
  const [llmTesting, setLlmTesting] = useState(false);
  const [pubmedResult, setPubmedResult] = useState<TestState>(null);
  const [llmResult, setLlmResult] = useState<TestState>(null);

  useEffect(() => {
    let cancelled = false;
    getMedicalKnowledgeServiceStatus()
      .then((value) => {
        if (!cancelled) setStatus(value);
      })
      .catch(() => {
        if (!cancelled) setStatusError('Không thể tải trạng thái cấu hình dịch vụ.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function runPubmedTest() {
    setPubmedTesting(true);
    setPubmedResult(null);
    try {
      const result = await testPubMedConnection();
      setPubmedResult({ kind: 'success', message: result.message });
    } catch (error) {
      setPubmedResult({ kind: 'error', message: serviceConfigurationErrorMessage(error, 'PubMed') });
    } finally {
      setPubmedTesting(false);
    }
  }

  async function runLlmTest() {
    setLlmTesting(true);
    setLlmResult(null);
    try {
      const result = await testLlmConnection();
      setLlmResult({ kind: 'success', message: result.message });
    } catch (error) {
      const service = status?.llm.provider === 'ollama'
        ? 'AI cục bộ'
        : status?.llm.provider === 'groq'
          ? 'Groq'
          : 'OpenAI';
      setLlmResult({ kind: 'error', message: serviceConfigurationErrorMessage(error, service) });
    } finally {
      setLlmTesting(false);
    }
  }

  const missingPubmed = status && !status.pubmed.email_configured;
  const missingLlm = status && !status.llm.configured;
  const isOllama = status?.llm.provider === 'ollama';
  const isGroq = status?.llm.provider === 'groq';

  return (
    <section aria-labelledby="service-configuration-title" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-slate-100 p-2 text-slate-700"><Settings2 aria-hidden size={20} /></div>
        <div>
          <h2 id="service-configuration-title" className="text-lg font-semibold text-slate-900">Cấu hình dịch vụ</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            Trạng thái chỉ cho biết cấu hình đã sẵn sàng hay chưa; hệ thống không hiển thị giá trị bí mật.
          </p>
        </div>
      </div>

      {loading && (
        <div role="status" className="mt-4 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 aria-hidden size={16} className="animate-spin" /> Đang tải trạng thái dịch vụ…
        </div>
      )}
      {statusError && <div role="alert" className="mt-4 text-sm text-red-700">{statusError}</div>}

      {status && (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <article aria-label="PubMed" className="rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-2 text-slate-900"><Database aria-hidden size={18} /><h3 className="font-semibold">PubMed</h3></div>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Trạng thái</dt><dd><StatusLine configured={status.pubmed.configured} yes="Đã cấu hình" no="Chưa cấu hình" /></dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Email liên hệ</dt><dd><StatusLine configured={status.pubmed.email_configured} yes="Đã thiết lập" no="Chưa thiết lập" /></dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">NCBI API key</dt><dd className="text-slate-700">{status.pubmed.api_key_configured ? 'Đã thiết lập' : 'Không bắt buộc'}</dd></div>
            </dl>
            <button type="button" onClick={runPubmedTest} disabled={pubmedTesting} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3.5 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
              {pubmedTesting && <Loader2 aria-hidden size={15} className="animate-spin" />}
              {pubmedTesting ? 'Đang kiểm tra…' : 'Kiểm tra kết nối'}
            </button>
            {pubmedResult && <p role={pubmedResult.kind === 'error' ? 'alert' : 'status'} className={`mt-3 text-sm ${pubmedResult.kind === 'success' ? 'text-emerald-700' : 'text-red-700'}`}>{pubmedResult.message}</p>}
          </article>

          <article aria-label={isOllama ? 'AI cục bộ' : isGroq ? 'Groq' : 'OpenAI'} className="rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-2 text-slate-900"><Sparkles aria-hidden size={18} /><h3 className="font-semibold">AI tạo bản nháp</h3></div>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Trạng thái</dt><dd><StatusLine configured={status.llm.configured} yes="Đã cấu hình" no="Chưa cấu hình" /></dd></div>
              {isOllama && <div className="flex justify-between gap-3"><dt className="text-slate-500">Loại</dt><dd className="text-slate-700">AI cục bộ</dd></div>}
              {isGroq && <div className="flex justify-between gap-3"><dt className="text-slate-500">Loại</dt><dd className="text-slate-700">API trực tuyến</dd></div>}
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Provider</dt><dd className="text-slate-700">{isOllama ? 'Ollama' : isGroq ? 'Groq' : status.llm.provider === 'openai' ? 'OpenAI' : status.llm.provider || 'Chưa thiết lập'}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Model</dt><dd className="font-mono text-xs text-slate-700">{status.llm.model || (isOllama ? 'Chưa chọn' : 'Chưa thiết lập')}</dd></div>
              {!isOllama && <div className="flex justify-between gap-3"><dt className="text-slate-500">API key</dt><dd><StatusLine configured={status.llm.api_key_configured} yes="Đã thiết lập" no="Chưa thiết lập" /></dd></div>}
            </dl>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              {isOllama
                ? 'Ollama chạy trực tiếp trên máy này. Không sử dụng OpenAI API cho provider hiện tại.'
                : isGroq
                  ? 'Groq chạy AI trên máy chủ bên ngoài. Khi tạo bản nháp, hệ thống chỉ gửi thông tin nhóm bệnh, yếu tố thời tiết và các tóm tắt PubMed đã chọn. Không gửi dữ liệu bệnh nhi.'
                  : 'Kiểm tra OpenAI sẽ gửi một yêu cầu rất nhỏ tới API.'}
            </p>
            {isGroq && (
              <p className="mt-2 text-xs leading-5 text-slate-500">
                Việc sử dụng phụ thuộc giới hạn/gói của tài khoản Groq. Project không tự chuyển sang nhà cung cấp khác khi Groq lỗi hoặc hết giới hạn.
              </p>
            )}
            <button type="button" onClick={runLlmTest} disabled={llmTesting} className="mt-2 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3.5 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
              {llmTesting && <Loader2 aria-hidden size={15} className="animate-spin" />}
              {llmTesting ? 'Đang kiểm tra…' : isOllama ? 'Kiểm tra AI cục bộ' : 'Kiểm tra kết nối'}
            </button>
            {llmResult && <p role={llmResult.kind === 'error' ? 'alert' : 'status'} className={`mt-3 text-sm ${llmResult.kind === 'success' ? 'text-emerald-700' : 'text-red-700'}`}>{llmResult.message}</p>}
          </article>
        </div>
      )}

      {(missingPubmed || missingLlm) && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-semibold">Cần cấu hình</p>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {missingPubmed && <li>PubMed: NCBI_EMAIL</li>}
            {missingLlm && <li>{isOllama ? 'Ollama: OLLAMA_MODEL' : isGroq ? 'Groq: GROQ_API_KEY và GROQ_MODEL' : 'OpenAI: OPENAI_API_KEY và OPENAI_MODEL'}</li>}
          </ul>
        </div>
      )}

      <p className="mt-4 text-sm leading-6 text-slate-600">
        Các thông tin này được cấu hình trong file <code className="rounded bg-slate-100 px-1.5 py-0.5">seasonal_disease_backend/.env</code>. Sau khi sửa .env, hãy khởi động lại backend để cấu hình mới có hiệu lực.
      </p>
    </section>
  );
}
