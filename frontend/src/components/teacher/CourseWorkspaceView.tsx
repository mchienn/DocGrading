import React, { useState } from 'react';
import { ArrowLeft, CalendarClock, Pencil, Plus, Send, Square } from 'lucide-react';
import type { components } from '../../api/schema';
import { getErrorMessage } from '../../api/client';
import type { ApiAssignment, ApiCourse, ApiRubric } from '../../types/api';
import { AssignmentWizardModal } from './AssignmentWizardModal';

type AssignmentInput = components['schemas']['AssignmentCreate'];

interface CourseWorkspaceViewProps {
  course: ApiCourse;
  assignments: ApiAssignment[];
  rubrics: ApiRubric[];
  loading: boolean;
  error?: string;
  onBack: () => void;
  onSaveAssignment: (input: AssignmentInput, assignmentId?: string) => Promise<void>;
  onPublishAssignment: (assignmentId: string) => Promise<void>;
  onCloseAssignment: (assignmentId: string) => Promise<void>;
}

export const CourseWorkspaceView: React.FC<CourseWorkspaceViewProps> = ({
  course,
  assignments,
  rubrics,
  loading,
  error,
  onBack,
  onSaveAssignment,
  onPublishAssignment,
  onCloseAssignment,
}) => {
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ApiAssignment>();
  const [actionError, setActionError] = useState<string>();

  const runAction = async (action: () => Promise<void>) => {
    setActionError(undefined);
    try {
      await action();
    } catch (requestError) {
      setActionError(getErrorMessage(requestError));
    }
  };

  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900">
        <ArrowLeft className="w-4 h-4" /> Back to courses
      </button>
      <div className="flex items-start justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>
          <h1 className="text-2xl font-bold text-slate-900 mt-1">{course.name}</h1>
          <p className="text-sm text-slate-500 mt-1">{course.term} · {course.status}</p>
        </div>
        {course.status === 'ACTIVE' && (
          <button
            type="button"
            onClick={() => {
              setEditing(undefined);
              setShowForm(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold"
          >
            <Plus className="w-4 h-4" /> Create assignment
          </button>
        )}
      </div>

      {(error || actionError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {actionError ?? error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading assignments...</p>
      ) : assignments.length === 0 ? (
        <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No assignments in this course.</p>
      ) : (
        <div className="space-y-3">
          {assignments.map((assignment) => (
            <article key={assignment.id} className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-bold text-slate-900">{assignment.title}</h2>
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded border bg-slate-50 text-slate-600 border-slate-200">{assignment.status}</span>
                  </div>
                  {assignment.description && <p className="text-sm text-slate-600 mt-2">{assignment.description}</p>}
                  <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
                    <CalendarClock className="w-3.5 h-3.5" /> Due {new Date(assignment.due_at).toLocaleString()} · max {assignment.max_submissions}
                  </p>
                </div>
                {course.status === 'ACTIVE' && (
                  <div className="flex items-center gap-2 shrink-0">
                    {assignment.status === 'DRAFT' && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setEditing(assignment);
                            setShowForm(true);
                          }}
                          className="p-2 border border-slate-200 rounded-lg text-slate-600"
                          aria-label={`Edit ${assignment.title}`}
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => runAction(() => onPublishAssignment(assignment.id))}
                          className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-700 text-white rounded-lg text-xs font-semibold"
                        >
                          <Send className="w-3.5 h-3.5" /> Publish
                        </button>
                      </>
                    )}
                    {assignment.status === 'OPEN' && (
                      <button
                        type="button"
                        onClick={() => runAction(() => onCloseAssignment(assignment.id))}
                        className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-800 text-white rounded-lg text-xs font-semibold"
                      >
                        <Square className="w-3.5 h-3.5" /> Close
                      </button>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {showForm && (
        <AssignmentWizardModal
          assignment={editing}
          rubrics={rubrics}
          onClose={() => setShowForm(false)}
          onSave={(input) => onSaveAssignment(input, editing?.id)}
        />
      )}
    </div>
  );
};
