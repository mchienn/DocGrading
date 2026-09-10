import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, FileText, UploadCloud } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';

const PDF_MAX_SIZE_BYTES = 50_000_000;

function sha256Hex(file: File): Promise<string> {
  return file.arrayBuffer()
    .then((buffer) => crypto.subtle.digest('SHA-256', buffer))
    .then((digest) => Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join(''));
}

function uploadObject(
  url: string,
  fields: Record<string, string>,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', url);
    request.timeout = 10 * 60 * 1000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new Error('Object storage upload failed.'));
    request.ontimeout = () => reject(new Error('Object storage upload timed out.'));
    request.onabort = () => reject(new Error('Object storage upload was cancelled.'));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new Error(`Object storage upload failed (${request.status}).`));
    };
    const form = new FormData();
    Object.entries(fields).forEach(([key, value]) => form.append(key, value));
    form.append('file', file);
    request.send(form);
  });
}

export const StudentUploadView: React.FC = () => {
  const { courseId = '', assignmentId = '' } = useParams();
  const navigate = useNavigate();
  const [file, setFile] = useState<File>();
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState('Ready');
  const [error, setError] = useState<string>();
  const [uploading, setUploading] = useState(false);

  const assignmentQuery = useQuery({
    queryKey: ['assignment', courseId, assignmentId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/assignments/{assignment_id}', {
      params: { path: { course_id: courseId, assignment_id: assignmentId } },
    })),
    enabled: Boolean(courseId && assignmentId),
  });
  const [now, setNow] = useState(Date.now());
  const deadline = assignmentQuery.data
    ? new Date(assignmentQuery.data.due_at).getTime()
    : Number.POSITIVE_INFINITY;
  const acceptingSubmissions = assignmentQuery.data?.status === 'OPEN' && deadline > now;
  useEffect(() => {
    if (!Number.isFinite(deadline) || deadline <= now) return;
    const timeout = window.setTimeout(
      () => setNow(Date.now()),
      Math.min(deadline - now + 50, 2_147_483_647),
    );
    return () => window.clearTimeout(timeout);
  }, [deadline, now]);

  const chooseFile = (selected?: File) => {
    setError(undefined);
    setProgress(0);
    setPhase('Ready');
    if (!selected) {
      setFile(undefined);
      return;
    }
    if (!selected.name.toLowerCase().endsWith('.pdf')) {
      setFile(undefined);
      setError('Only PDF files are accepted.');
      return;
    }
    if (selected.size > PDF_MAX_SIZE_BYTES) {
      setFile(undefined);
      setError('PDF exceeds 50,000,000 bytes.');
      return;
    }
    setFile(selected);
    setIdempotencyKey(crypto.randomUUID());
  };

  const upload = async () => {
    if (!file || !assignmentId) return;
    setUploading(true);
    setError(undefined);
    try {
      setPhase('Computing SHA-256');
      const sha256 = await sha256Hex(file);
      setPhase('Requesting upload URL');
      const presign = await apiData(api.POST('/api/v1/assignments/{assignment_id}/uploads/presign', {
        params: {
          path: { assignment_id: assignmentId },
          header: { 'Idempotency-Key': idempotencyKey },
        },
        body: {
          filename: file.name,
          content_type: 'application/pdf',
          size_bytes: file.size,
          sha256,
        },
      }));

      if (presign.analysis_job_id) {
        navigate(`/jobs/${presign.analysis_job_id}`);
        return;
      }
      if (presign.upload_url && presign.fields) {
        setPhase('Uploading to object storage');
        await uploadObject(presign.upload_url, presign.fields, file, setProgress);
      }

      setPhase('Confirming upload');
      const completion = await apiData(api.POST('/api/v1/document-versions/{version_id}/complete', {
        params: { path: { version_id: presign.document_version_id } },
      }));
      navigate(`/jobs/${completion.analysis_job_id}`);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
      setPhase('Failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-6 sm:p-8 max-w-3xl mx-auto space-y-6">
      <button type="button" onClick={() => navigate('/student/assignments')} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600">
        <ArrowLeft className="w-4 h-4" /> Back to assignments
      </button>
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Upload submission</h1>
        <p className="text-sm text-slate-500 mt-1">{assignmentQuery.data?.title ?? 'Loading assignment...'}</p>
      </div>

      {(error || assignmentQuery.error) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {error ?? getErrorMessage(assignmentQuery.error)}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
        <label className="block border-2 border-dashed border-slate-300 rounded-xl p-8 text-center cursor-pointer hover:border-sky-400">
          <UploadCloud className="w-10 h-10 mx-auto text-slate-400" />
          <span className="block text-sm font-semibold text-slate-700 mt-3">Choose PDF</span>
          <span className="block text-xs text-slate-500 mt-1">Maximum 50,000,000 bytes</span>
          <input type="file" accept="application/pdf,.pdf" className="sr-only" disabled={uploading} onChange={(event) => chooseFile(event.target.files?.[0])} />
        </label>

        {file && (
          <div className="flex items-center gap-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
            <FileText className="w-5 h-5 text-sky-700" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 truncate">{file.name}</p>
              <p className="text-xs text-slate-500">{file.size.toLocaleString()} bytes</p>
            </div>
          </div>
        )}

        <div>
          <div className="flex justify-between text-xs text-slate-600 mb-1">
            <span>{phase}</span><span>{progress}%</span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-sky-600 transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>

        {assignmentQuery.data && !acceptingSubmissions && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            Assignment is no longer accepting submissions.
          </p>
        )}

        <button
          type="button"
          disabled={!file || uploading || !acceptingSubmissions}
          onClick={upload}
          className="w-full px-4 py-2.5 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50"
        >
          {uploading ? phase : 'Upload PDF'}
        </button>
      </div>
    </div>
  );
};
