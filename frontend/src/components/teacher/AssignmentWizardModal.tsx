import React, { useState } from 'react';
import { X } from 'lucide-react';
import type { components } from '../../api/schema';
import { getErrorMessage } from '../../api/client';
import type { ApiAssignment, ApiRubric } from '../../types/api';

type AssignmentInput = components['schemas']['AssignmentCreate'];

function toLocalDateTime(value?: string): string {
  if (!value) return '';
  const instant = new Date(value);
  return new Date(instant.getTime() - instant.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

interface AssignmentWizardModalProps {
  assignment?: ApiAssignment;
  rubrics: ApiRubric[];
  onClose: () => void;
  onSave: (input: AssignmentInput) => Promise<void>;
}

export const AssignmentWizardModal: React.FC<AssignmentWizardModalProps> = ({
  assignment,
  rubrics,
  onClose,
  onSave,
}) => {
  const [title, setTitle] = useState(assignment?.title ?? '');
  const [description, setDescription] = useState(assignment?.description ?? '');
  const [dueAt, setDueAt] = useState(toLocalDateTime(assignment?.due_at));
  const [maxSubmissions, setMaxSubmissions] = useState(assignment?.max_submissions ?? 3);
  const [rubricVersionId, setRubricVersionId] = useState(assignment?.rubric_version_id ?? rubrics[0]?.id ?? '');
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(undefined);
    try {
      await onSave({
        title: title.trim(),
        description: description.trim() || null,
        due_at: new Date(dueAt).toISOString(),
        max_submissions: maxSubmissions,
        rubric_version_id: rubricVersionId,
      });
      onClose();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4">
      <form onSubmit={submit} className="bg-white rounded-xl border border-slate-200 shadow-xl w-full max-w-lg p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-slate-900">{assignment ? 'Edit assignment' : 'Create assignment'}</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <label className="block text-sm text-slate-700">
          Title
          <input required value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
        </label>
        <label className="block text-sm text-slate-700">
          Description
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg min-h-24" />
        </label>
        <label className="block text-sm text-slate-700">
          Due date
          <input required type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
        </label>
        <label className="block text-sm text-slate-700">
          Maximum submissions
          <input required type="number" min={1} max={5} value={maxSubmissions} onChange={(event) => setMaxSubmissions(Number(event.target.value))} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
        </label>
        <label className="block text-sm text-slate-700">
          Published rubric
          <select required value={rubricVersionId} onChange={(event) => setRubricVersionId(event.target.value)} className="mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg">
            {rubrics.map((rubric) => (
              <option key={rubric.id} value={rubric.id}>{rubric.name} v{rubric.version_number}</option>
            ))}
          </select>
        </label>
        {rubrics.length === 0 && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            Publish a rubric before creating an assignment.
          </p>
        )}
        <button disabled={saving || rubrics.length === 0} className="w-full px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">
          {saving ? 'Saving...' : 'Save assignment'}
        </button>
      </form>
    </div>
  );
};
