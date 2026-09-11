import React, { useState } from 'react';
import { Archive, BookOpen, Pencil, Plus, X } from 'lucide-react';
import type { ApiCourse } from '../../types/api';
import { getErrorMessage } from '../../api/client';

interface CourseInput {
  code: string;
  name: string;
  term: string;
}

interface CourseListViewProps {
  courses: ApiCourse[];
  canCreate: boolean;
  loading: boolean;
  error?: string;
  onSelectCourse: (course: ApiCourse) => void;
  onSave: (input: CourseInput, courseId?: string) => Promise<void>;
  onArchive: (courseId: string) => Promise<void>;
}

export const CourseListView: React.FC<CourseListViewProps> = ({
  courses,
  canCreate,
  loading,
  error,
  onSelectCourse,
  onSave,
  onArchive,
}) => {
  const [editing, setEditing] = useState<ApiCourse | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [term, setTerm] = useState('');

  const openForm = (course?: ApiCourse) => {
    setEditing(course ?? null);
    setCode(course?.code ?? '');
    setName(course?.name ?? '');
    setTerm(course?.term ?? '');
    setFormError(undefined);
    setShowForm(true);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setFormError(undefined);
    try {
      await onSave({ code: code.trim(), name: name.trim(), term: term.trim() }, editing?.id);
      setShowForm(false);
    } catch (requestError) {
      setFormError(getErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (course: ApiCourse) => {
    if (!window.confirm(`Archive ${course.code}? Archived courses become read-only.`)) return;
    try {
      await onArchive(course.id);
    } catch (requestError) {
      setFormError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-[#172033]">Courses</h1>
          <p className="text-sm text-[#596579] mt-1">Courses returned by DocGrading API.</p>
        </div>
        {canCreate && (
          <button
            type="button"
            onClick={() => openForm()}
            className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold"
          >
            <Plus className="w-4 h-4" /> Create course
          </button>
        )}
      </div>

      {(error || formError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {formError ?? error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading courses...</p>
      ) : courses.length === 0 ? (
        <div className="p-10 text-center bg-white border border-dashed border-slate-300 rounded-xl">
          <BookOpen className="w-10 h-10 mx-auto text-slate-400" />
          <p className="mt-3 text-sm text-slate-600">No courses available.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {courses.map((course) => (
            <article key={course.id} className="bg-white border border-slate-200 rounded-xl p-5 shadow-2xs">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>
                  <h2 className="font-bold text-slate-900 mt-1">{course.name}</h2>
                  <p className="text-xs text-slate-500 mt-1">{course.term}</p>
                </div>
                <span className={`text-[11px] font-semibold px-2 py-1 rounded border ${
                  course.status === 'ACTIVE'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-slate-100 text-slate-600 border-slate-200'
                }`}>
                  {course.status}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-5">
                <button
                  type="button"
                  onClick={() => onSelectCourse(course)}
                  className="px-3 py-2 bg-slate-900 text-white rounded-lg text-xs font-semibold"
                >
                  Open
                </button>
                {course.status === 'ACTIVE' && (
                  <>
                    <button
                      type="button"
                      onClick={() => openForm(course)}
                      className="p-2 border border-slate-200 rounded-lg text-slate-600"
                      aria-label={`Edit ${course.code}`}
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => archive(course)}
                      className="p-2 border border-slate-200 rounded-lg text-slate-600"
                      aria-label={`Archive ${course.code}`}
                    >
                      <Archive className="w-4 h-4" />
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
          <form onSubmit={submit} className="bg-white rounded-xl border border-slate-200 shadow-xl w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-slate-900">{editing ? 'Edit course' : 'Create course'}</h2>
              <button type="button" onClick={() => setShowForm(false)} aria-label="Close">
                <X className="w-4 h-4" />
              </button>
            </div>
            {formError && <p role="alert" className="text-sm text-rose-700">{formError}</p>}
            <label className="block text-sm text-slate-700">
              Code
              <input
                required
                disabled={Boolean(editing)}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg disabled:bg-slate-100"
              />
            </label>
            <label className="block text-sm text-slate-700">
              Name
              <input required value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
            </label>
            <label className="block text-sm text-slate-700">
              Term
              <input required value={term} onChange={(event) => setTerm(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
            </label>
            <button disabled={saving} className="w-full px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">
              {saving ? 'Saving...' : 'Save'}
            </button>
          </form>
        </div>
      )}
    </div>
  );
};
