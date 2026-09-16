import React, { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, KeyRound } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { api, apiData, getErrorMessage } from '../../api/client';

type CourseJoinResponse = components['schemas']['CourseJoinResponse'];

const outcomeDetails: Record<
  components['schemas']['CourseJoinOutcome'],
  { label: string; description: string; badgeClass: string }
> = {
  JOINED: {
    label: 'Joined Course',
    description: 'You have successfully enrolled in this course.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  },
  REACTIVATED: {
    label: 'Membership Reactivated',
    description: 'Your enrollment in this course has been reactivated.',
    badgeClass: 'bg-sky-100 text-sky-800 border-sky-300',
  },
  ALREADY_MEMBER: {
    label: 'Already Enrolled',
    description: 'You are already an active member of this course.',
    badgeClass: 'bg-slate-100 text-slate-800 border-slate-300',
  },
};

export const StudentJoinCourseView: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const codeParam = searchParams.get('code') ?? '';
  const [code, setCode] = useState(codeParam);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CourseJoinResponse | null>(null);

  const handleJoin = async (codeToSubmit: string) => {
    const normalized = codeToSubmit.trim().toUpperCase();
    if (!normalized || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const data = await apiData(
        api.POST('/api/v1/course-joins', {
          body: { code: normalized },
        }),
      );
      setResult(data);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['courses'] }),
        queryClient.invalidateQueries({ queryKey: ['assignments'] }),
      ]);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    setCode(codeParam.trim().toUpperCase());
    setError(null);
    setResult(null);
  }, [codeParam]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void handleJoin(code);
  };

  const handleReset = () => {
    setResult(null);
    setCode('');
    setError(null);
  };

  return (
    <div className="p-6 sm:p-8 max-w-2xl mx-auto space-y-6">
      <button
        type="button"
        onClick={() => navigate('/student/assignments')}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to assignments
      </button>

      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Join Course</h1>
        <p className="text-sm text-slate-500 mt-1">
          Enter a course join code provided by your instructor or follow an invitation link.
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 text-sm space-y-1"
        >
          <div className="font-semibold flex items-center gap-1.5">
            <span>Unable to join course</span>
          </div>
          <p className="text-rose-700">{error}</p>
        </div>
      )}

      {result ? (
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-6 h-6 text-emerald-600 shrink-0 mt-0.5" />
            <div className="space-y-1 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-sky-700">{result.course_code}</span>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border ${
                    outcomeDetails[result.outcome]?.badgeClass ?? 'bg-slate-100 text-slate-800'
                  }`}
                >
                  {outcomeDetails[result.outcome]?.label ?? result.outcome}
                </span>
              </div>
              <h2 className="text-xl font-bold text-slate-900">{result.course_name}</h2>
              <p className="text-sm text-slate-600">
                {outcomeDetails[result.outcome]?.description}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={() => navigate('/student/assignments')}
              className="px-5 py-2.5 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-sm font-semibold inline-flex items-center gap-2 shadow-sm"
            >
              Go to assignments
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="px-4 py-2.5 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-medium"
            >
              Join another course
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
          <div>
            <label htmlFor="join-code" className="block text-sm font-semibold text-slate-900 mb-1">
              Course join code
            </label>
            <p className="text-xs text-slate-500 mb-2">
              Code is 20 characters long (e.g. ABCDEFGHJKMNPQRSTUV0)
            </p>
            <input
              id="join-code"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="Enter join code"
              maxLength={20}
              autoFocus
              required
              className="block w-full font-mono text-base tracking-widest uppercase px-3.5 py-2.5 border border-slate-300 rounded-lg text-slate-900 bg-white focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 placeholder:normal-case placeholder:tracking-normal placeholder:text-slate-400"
            />
          </div>

          <div className="flex items-center justify-between pt-2">
            <button
              type="submit"
              disabled={submitting || !code.trim()}
              className="px-6 py-2.5 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-sm font-semibold inline-flex items-center gap-2 disabled:opacity-50 shadow-sm"
            >
              <KeyRound className="w-4 h-4" />
              {submitting ? 'Joining course...' : 'Join course'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
};
