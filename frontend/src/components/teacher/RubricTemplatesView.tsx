import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CopyPlus, Pencil, Plus, Send, Trash2 } from 'lucide-react';
import { api, apiData, apiVoid, getErrorMessage } from '../../api/client';
import type { ApiCriterion } from '../../types/api';

interface CriterionForm {
  code: string;
  title: string;
  description: string;
  weight: string;
  position: number;
  evaluationMethod: string;
}

const emptyCriterion: CriterionForm = {
  code: '',
  title: '',
  description: '',
  weight: '',
  position: 1,
  evaluationMethod: 'AI',
};

export const RubricTemplatesView: React.FC = () => {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState('');
  const [newRubricName, setNewRubricName] = useState('');
  const [criterionForm, setCriterionForm] = useState<CriterionForm>(emptyCriterion);
  const [editingCriterion, setEditingCriterion] = useState<ApiCriterion>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const rubricsQuery = useQuery({
    queryKey: ['rubrics'],
    queryFn: () => apiData(api.GET('/api/v1/rubrics')),
  });
  const rubrics = rubricsQuery.data ?? [];
  const selectedRubric = rubrics.find((rubric) => rubric.id === selectedId);

  const criteriaQuery = useQuery({
    queryKey: ['rubric-criteria', selectedId],
    queryFn: () => apiData(api.GET('/api/v1/rubrics/{rubric_id}/criteria', {
      params: { path: { rubric_id: selectedId } },
    })),
    enabled: Boolean(selectedId),
  });
  const criteria = criteriaQuery.data ?? [];

  useEffect(() => {
    if (rubrics.length > 0 && !rubrics.some((rubric) => rubric.id === selectedId)) {
      setSelectedId(rubrics[0].id);
    }
  }, [rubrics, selectedId]);

  useEffect(() => {
    setEditingCriterion(undefined);
    setCriterionForm(emptyCriterion);
  }, [selectedId]);

  const refreshRubrics = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rubrics'] });
  };

  const refreshCriteria = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rubric-criteria', selectedId] });
    await refreshRubrics();
  };

  const createRubric = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const rubric = await apiData(api.POST('/api/v1/rubrics', {
        body: {
          name: newRubricName.trim(),
          description: null,
          calculation_method: 'WEIGHTED_SUM',
        },
      }));
      setNewRubricName('');
      await refreshRubrics();
      setSelectedId(rubric.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const publishRubric = async () => {
    if (!selectedRubric) return;
    setBusy(true);
    setError(undefined);
    try {
      await apiData(api.POST('/api/v1/rubrics/{rubric_id}/publish', {
        params: { path: { rubric_id: selectedRubric.id } },
      }));
      await refreshRubrics();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const createVersion = async () => {
    if (!selectedRubric) return;
    setBusy(true);
    setError(undefined);
    try {
      const rubric = await apiData(api.POST('/api/v1/rubrics/{rubric_id}/new-version', {
        params: { path: { rubric_id: selectedRubric.id } },
      }));
      await refreshRubrics();
      setSelectedId(rubric.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const saveCriterion = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedRubric) return;
    setBusy(true);
    setError(undefined);
    try {
      if (editingCriterion) {
        await apiData(api.PUT('/api/v1/rubrics/{rubric_id}/criteria/{criterion_id}', {
          params: { path: { rubric_id: selectedRubric.id, criterion_id: editingCriterion.id } },
          body: {
            title: criterionForm.title.trim(),
            description: criterionForm.description.trim(),
            weight: criterionForm.weight,
            position: criterionForm.position,
            evaluation_method: criterionForm.evaluationMethod,
          },
        }));
      } else {
        await apiData(api.POST('/api/v1/rubrics/{rubric_id}/criteria', {
          params: { path: { rubric_id: selectedRubric.id } },
          body: {
            code: criterionForm.code.trim(),
            title: criterionForm.title.trim(),
            description: criterionForm.description.trim(),
            weight: criterionForm.weight,
            position: criterionForm.position,
            evaluation_method: criterionForm.evaluationMethod,
            is_enabled: true,
          },
        }));
      }
      setEditingCriterion(undefined);
      setCriterionForm(emptyCriterion);
      await refreshCriteria();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const editCriterion = (criterion: ApiCriterion) => {
    setEditingCriterion(criterion);
    setCriterionForm({
      code: criterion.code,
      title: criterion.title,
      description: criterion.description,
      weight: criterion.weight,
      position: criterion.position,
      evaluationMethod: criterion.evaluation_method,
    });
  };

  const deleteCriterion = async (criterion: ApiCriterion) => {
    if (!selectedRubric || !window.confirm(`Delete criterion ${criterion.code}?`)) return;
    setBusy(true);
    setError(undefined);
    try {
      await apiVoid(api.DELETE('/api/v1/rubrics/{rubric_id}/criteria/{criterion_id}', {
        params: { path: { rubric_id: selectedRubric.id, criterion_id: criterion.id } },
      }));
      await refreshCriteria();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Rubrics</h1>
        <p className="text-sm text-slate-500 mt-1">Draft, publish, version, and criterion management.</p>
      </div>

      {(error || rubricsQuery.error || criteriaQuery.error) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {error ?? getErrorMessage(rubricsQuery.error ?? criteriaQuery.error)}
        </div>
      )}

      <form onSubmit={createRubric} className="flex gap-2 max-w-xl">
        <input
          required
          value={newRubricName}
          onChange={(event) => setNewRubricName(event.target.value)}
          placeholder="New rubric name"
          className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm"
        />
        <button disabled={busy} className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">
          <Plus className="w-4 h-4" /> Create
        </button>
      </form>

      {rubrics.length === 0 ? (
        <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No rubrics available.</p>
      ) : (
        <div className="grid lg:grid-cols-[280px_1fr] gap-5">
          <aside className="space-y-2">
            {rubrics.map((rubric) => (
              <button
                key={rubric.id}
                type="button"
                onClick={() => setSelectedId(rubric.id)}
                className={`w-full text-left p-3 rounded-lg border ${selectedId === rubric.id ? 'border-sky-300 bg-sky-50' : 'border-slate-200 bg-white'}`}
              >
                <p className="text-sm font-semibold text-slate-900">{rubric.name}</p>
                <p className="text-xs text-slate-500 mt-1">v{rubric.version_number} · {rubric.status} · {rubric.total_weight}%</p>
              </button>
            ))}
          </aside>

          {selectedRubric && (
            <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 border-b border-slate-200 pb-4">
                <div>
                  <h2 className="font-bold text-slate-900">{selectedRubric.name} v{selectedRubric.version_number}</h2>
                  <p className="text-sm text-slate-500 mt-1">{selectedRubric.status} · total weight {selectedRubric.total_weight}%</p>
                </div>
                {selectedRubric.status === 'DRAFT' ? (
                  <button type="button" disabled={busy} onClick={publishRubric} className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50">
                    <Send className="w-3.5 h-3.5" /> Publish
                  </button>
                ) : (
                  <button type="button" disabled={busy} onClick={createVersion} className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-800 text-white rounded-lg text-xs font-semibold disabled:opacity-50">
                    <CopyPlus className="w-3.5 h-3.5" /> New version
                  </button>
                )}
              </div>

              <div className="space-y-2">
                {criteria.map((criterion) => (
                  <article key={criterion.id} className="flex items-start justify-between gap-3 p-3 border border-slate-200 rounded-lg">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{criterion.code} · {criterion.title}</p>
                      <p className="text-xs text-slate-500 mt-1">{criterion.description}</p>
                      <p className="text-xs text-sky-700 mt-1">{criterion.weight}% · {criterion.evaluation_method}</p>
                    </div>
                    {selectedRubric.status === 'DRAFT' && (
                      <div className="flex gap-1">
                        <button type="button" onClick={() => editCriterion(criterion)} aria-label={`Edit ${criterion.code}`} className="p-2 text-slate-600"><Pencil className="w-4 h-4" /></button>
                        <button type="button" onClick={() => deleteCriterion(criterion)} aria-label={`Delete ${criterion.code}`} className="p-2 text-rose-600"><Trash2 className="w-4 h-4" /></button>
                      </div>
                    )}
                  </article>
                ))}
              </div>

              {selectedRubric.status === 'DRAFT' && (
                <form onSubmit={saveCriterion} className="grid sm:grid-cols-2 gap-3 pt-3 border-t border-slate-200">
                  <h3 className="sm:col-span-2 text-sm font-bold text-slate-900">{editingCriterion ? 'Edit criterion' : 'Add criterion'}</h3>
                  <input required disabled={Boolean(editingCriterion)} value={criterionForm.code} onChange={(event) => setCriterionForm({ ...criterionForm, code: event.target.value })} placeholder="Code" className="px-3 py-2 border border-slate-300 rounded-lg text-sm disabled:bg-slate-100" />
                  <input required value={criterionForm.title} onChange={(event) => setCriterionForm({ ...criterionForm, title: event.target.value })} placeholder="Title" className="px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                  <textarea required value={criterionForm.description} onChange={(event) => setCriterionForm({ ...criterionForm, description: event.target.value })} placeholder="Description" className="sm:col-span-2 px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                  <input required type="number" min="0.01" max="100" step="0.01" value={criterionForm.weight} onChange={(event) => setCriterionForm({ ...criterionForm, weight: event.target.value })} placeholder="Weight" className="px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                  <input required type="number" min="1" value={criterionForm.position} onChange={(event) => setCriterionForm({ ...criterionForm, position: Number(event.target.value) })} placeholder="Position" className="px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                  <select value={criterionForm.evaluationMethod} onChange={(event) => setCriterionForm({ ...criterionForm, evaluationMethod: event.target.value })} className="px-3 py-2 border border-slate-300 rounded-lg text-sm">
                    <option value="AI">AI</option>
                    <option value="MANUAL">Manual</option>
                    <option value="HYBRID">Hybrid</option>
                  </select>
                  <div className="flex gap-2">
                    <button disabled={busy} className="px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">{editingCriterion ? 'Update' : 'Add'}</button>
                    {editingCriterion && <button type="button" onClick={() => { setEditingCriterion(undefined); setCriterionForm(emptyCriterion); }} className="px-4 py-2 border border-slate-300 rounded-lg text-sm">Cancel</button>}
                  </div>
                </form>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
};
