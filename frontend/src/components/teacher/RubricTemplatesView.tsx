import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { api, apiData, apiVoid, getErrorMessage } from '../../api/client';
import type { ApiCriterion, ApiRubric } from '../../types/api';
import {
  COMMON_LEVEL_DESCRIPTORS,
  DEFAULT_SRS_CATALOG,
  type CatalogCriterion,
} from '../../data/rubricCatalog';

interface CriterionModalProps {
  isOpen: boolean;
  mode: 'add' | 'edit';
  rubricId: string;
  existingCriteria: ApiCriterion[];
  criterionToEdit?: ApiCriterion;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

const EVALUATION_METHODS = [
  { value: 'AI', label: 'AI (LLM-Evaluator)' },
  { value: 'HYBRID', label: 'Hybrid (Hybrid-IR)' },
  { value: 'RULE_BASED', label: 'Rule-Based (Rule-Engine)' },
  { value: 'CITATION', label: 'Citation checks + Manual review' },
  { value: 'MANUAL', label: 'Manual (Manual Review)' },
];

function trapFocus(event: KeyboardEvent, container: HTMLElement) {
  if (event.key !== 'Tab') return;
  const elements = Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  );
  const first = elements[0];
  const last = elements.at(-1);
  if (!first || !last) return;
  if (
    (event.shiftKey && document.activeElement === first) ||
    (!event.shiftKey && document.activeElement === last)
  ) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}

function hasCompleteLevelScale(levels: ApiCriterion['levels']) {
  const scores = new Set(
    levels.map((level) => level.level).filter((level): level is number => typeof level === 'number'),
  );
  return scores.size === 5 && [0, 1, 2, 3, 4].every((level) => scores.has(level));
}

const CriterionModal: React.FC<CriterionModalProps> = ({
  isOpen,
  mode,
  rubricId,
  existingCriteria,
  criterionToEdit,
  onClose,
  onSaved,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCatalog, setSelectedCatalog] = useState<CatalogCriterion | null>(null);

  // Form states
  const [code, setCode] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [weight, setWeight] = useState<string>('10');
  const [evaluationMethod, setEvaluationMethod] = useState<string>('AI');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  const searchInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const savingRef = useRef(false);

  const requestClose = () => {
    if (!savingRef.current) onClose();
  };

  // Filter catalog criteria
  const filteredCatalog = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return DEFAULT_SRS_CATALOG;
    return DEFAULT_SRS_CATALOG.filter(
      (item) =>
        item.code.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
    );
  }, [searchQuery]);

  // Set initial state based on mode
  useEffect(() => {
    if (!isOpen) return;
    setError(undefined);
    setSearchQuery('');

    if (mode === 'edit' && criterionToEdit) {
      setCode(criterionToEdit.code);
      setTitle(criterionToEdit.title);
      setDescription(criterionToEdit.description);
      setWeight(String(criterionToEdit.weight));
      setEvaluationMethod(criterionToEdit.evaluation_method || 'AI');
      const matched = DEFAULT_SRS_CATALOG.find((c) => c.code.toUpperCase() === criterionToEdit.code.toUpperCase());
      setSelectedCatalog(matched ?? null);
    } else {
      // Add mode: default select the first available unadded catalog item
      const unadded = DEFAULT_SRS_CATALOG.find(
        (cat) => !existingCriteria.some((c) => c.code.toUpperCase() === cat.code.toUpperCase())
      );
      const initial = unadded ?? DEFAULT_SRS_CATALOG[0];
      setSelectedCatalog(initial);
      setCode(initial.code);
      setTitle(initial.name);
      setDescription(initial.description);
      setWeight(String(initial.weight));
      setEvaluationMethod(initial.evaluationMethod);
    }
  }, [isOpen, mode, criterionToEdit, existingCriteria]);

  // When user clicks a catalog item in Add mode
  const handleSelectCatalogItem = (item: CatalogCriterion) => {
    setSelectedCatalog(item);
    setCode(item.code);
    setTitle(item.name);
    setDescription(item.description);
    setWeight(String(item.weight));
    setEvaluationMethod(item.evaluationMethod);
    setError(undefined);
  };

  useEffect(() => {
    if (!isOpen) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => {
      if (mode === 'add') searchInputRef.current?.focus();
      else modalRef.current?.focus();
    }, 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') requestClose();
      else if (modalRef.current) trapFocus(event, modalRef.current);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener('keydown', handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [isOpen, mode, onClose]);

  if (!isOpen) return null;

  const numWeight = parseFloat(weight) || 0;
  const isAlreadyAddedInRubric = (catCode: string) =>
    existingCriteria.some((c) => c.code.toUpperCase() === catCode.toUpperCase());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (numWeight <= 0 || numWeight > 100) {
      setError('Weight must be between 0.01% and 100%.');
      return;
    }

    savingRef.current = true;
    setSaving(true);
    setError(undefined);

    try {
      if (mode === 'edit' && criterionToEdit) {
        await apiData(
          api.PUT('/api/v1/rubrics/{rubric_id}/criteria/{criterion_id}', {
            params: { path: { rubric_id: rubricId, criterion_id: criterionToEdit.id } },
            body: {
              title: title.trim(),
              description: description.trim(),
              weight: String(numWeight),
              position: criterionToEdit.position,
              evaluation_method: evaluationMethod,
              levels: hasCompleteLevelScale(criterionToEdit.levels)
                ? criterionToEdit.levels
                : COMMON_LEVEL_DESCRIPTORS,
              evaluator_config: {
                ...criterionToEdit.evaluator_config,
                grading_bullets:
                  selectedCatalog?.gradingBullets ??
                  criterionToEdit.evaluator_config.grading_bullets ??
                  [],
              },
              evidence_requirements: {
                ...criterionToEdit.evidence_requirements,
                required:
                  selectedCatalog?.evidenceRequired ??
                  Boolean(criterionToEdit.evidence_requirements.required),
              },
            },
          })
        );
      } else {
        const nextPosition =
          existingCriteria.length > 0
            ? Math.max(...existingCriteria.map((c) => c.position || 0)) + 1
            : 1;

        await apiData(
          api.POST('/api/v1/rubrics/{rubric_id}/criteria', {
            params: { path: { rubric_id: rubricId } },
            body: {
              code: code.trim(),
              title: title.trim(),
              description: description.trim(),
              weight: String(numWeight),
              position: nextPosition,
              evaluation_method: evaluationMethod,
              is_enabled: true,
              levels: selectedCatalog?.levelDescriptors ?? COMMON_LEVEL_DESCRIPTORS,
              evaluator_config: {
                grading_bullets: selectedCatalog?.gradingBullets ?? [],
              },
              evidence_requirements: {
                required: selectedCatalog?.evidenceRequired ?? false,
              },
            },
          })
        );
      }

      await onSaved();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="criterion-modal-title"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50/50">
          <div>
            <h2 id="criterion-modal-title" className="text-lg font-bold text-slate-900">
              {mode === 'edit' ? `Edit Criterion: ${criterionToEdit?.code}` : 'Add Criterion from Catalog'}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {mode === 'edit'
                ? 'Update criterion parameters, weights, and evaluation configuration.'
                : 'Select a standard SRS criterion from catalog, verify grading guidance, and add to rubric.'}
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            disabled={saving}
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div role="alert" className="mx-6 mt-4 p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Modal Body */}
        <form onSubmit={handleSubmit} className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 overflow-y-auto p-6">
            {mode === 'add' ? (
              <div className="grid md:grid-cols-[280px_1fr] gap-6">
                {/* Left: Catalog Selector */}
                <div className="space-y-3">
                  <label htmlFor="catalog-search-input" className="block text-xs font-bold uppercase tracking-wider text-slate-600">
                    Standard SRS Catalog ({filteredCatalog.length})
                  </label>
                  <div className="relative">
                    <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                    <input
                      id="catalog-search-input"
                      ref={searchInputRef}
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search code or title..."
                      aria-label="Search catalog criteria"
                      className="w-full pl-9 pr-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                    />
                  </div>

                  <div className="space-y-1.5 max-h-[380px] overflow-y-auto pr-1 border border-slate-200 rounded-xl p-1.5 bg-slate-50/50">
                    {filteredCatalog.map((item) => {
                      const alreadyAdded = isAlreadyAddedInRubric(item.code);
                      const isSelected = selectedCatalog?.code === item.code;

                      return (
                        <button
                          key={item.id}
                          type="button"
                          disabled={alreadyAdded}
                          onClick={() => handleSelectCatalogItem(item)}
                          aria-pressed={isSelected}
                          className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                            alreadyAdded
                              ? 'opacity-40 bg-slate-100 border-slate-200 cursor-not-allowed'
                              : isSelected
                              ? 'bg-sky-50 border-sky-400 ring-1 ring-sky-300'
                              : 'bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-mono font-bold text-slate-800">{item.code}</span>
                            {alreadyAdded ? (
                              <span className="text-[10px] font-semibold text-slate-500 bg-slate-200/80 px-1.5 py-0.5 rounded">
                                Added
                              </span>
                            ) : (
                              <span className="font-mono font-semibold text-sky-700">{item.weight}%</span>
                            )}
                          </div>
                          <p className="font-medium text-slate-900 mt-1 line-clamp-1">{item.name}</p>
                        </button>
                      );
                    })}
                    {filteredCatalog.length === 0 && (
                      <p className="p-4 text-center text-xs text-slate-400">No criteria matching search.</p>
                    )}
                  </div>
                </div>

                {/* Right: Selected Criterion Detail Preview & Configuration */}
                {selectedCatalog ? (
                  <div className="space-y-4">
                    <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-sky-700 bg-sky-100 px-2 py-0.5 rounded">
                              {selectedCatalog.code}
                            </span>
                            <h3 className="font-bold text-sm text-slate-900">{selectedCatalog.name}</h3>
                          </div>
                          <p className="text-xs text-slate-600 mt-1.5">{selectedCatalog.description}</p>
                        </div>
                      </div>

                      {/* Grading Bullets */}
                      {selectedCatalog.gradingBullets && selectedCatalog.gradingBullets.length > 0 && (
                        <div className="border-t border-slate-200 pt-3">
                          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-2">
                            {selectedCatalog.semanticPreview
                              ? 'Kiểm chứng thường — có tính điểm'
                              : 'What is graded (Concrete criteria)'}
                          </p>
                          <ul className="space-y-1.5 text-xs text-slate-700">
                            {selectedCatalog.gradingBullets.map((bullet, idx) => (
                              <li key={idx} className="flex items-start gap-2">
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" />
                                <span>{bullet}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {selectedCatalog.semanticPreview && (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-[11px] font-bold uppercase tracking-wider text-amber-900">
                              Semantic checks
                            </p>
                            <span className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[10px] font-bold text-amber-800">
                              Chưa tính điểm
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] text-amber-800">
                            Chỉ xem trước phạm vi. Không lưu evaluator semantic, không tạo điểm và không ảnh hưởng tổng điểm.
                          </p>
                          <ul className="mt-2 space-y-1.5 text-xs text-amber-950">
                            {selectedCatalog.semanticPreview.map((bullet) => (
                              <li key={bullet} className="flex items-start gap-2">
                                <span aria-hidden="true">•</span>
                                <span>{bullet}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Score Formula & Level Guide */}
                      <div className="border-t border-slate-200 pt-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
                            Score Calculation Formula
                          </span>
                          <span className="font-mono text-xs font-bold text-slate-800 bg-white border border-slate-200 px-2 py-0.5 rounded">
                            Score = (Level / 4) × {numWeight || 0}%
                          </span>
                        </div>

                        {/* Level breakdown chips */}
                        <div className="grid grid-cols-5 gap-1.5 text-[11px] font-mono text-center">
                          <div className="p-1.5 bg-white border border-slate-200 rounded">
                            <div className="text-slate-400 text-[10px]">L0 (0/4)</div>
                            <div className="font-bold text-slate-700">0.0%</div>
                          </div>
                          <div className="p-1.5 bg-white border border-slate-200 rounded">
                            <div className="text-slate-400 text-[10px]">L1 (1/4)</div>
                            <div className="font-bold text-slate-700">{(numWeight * 0.25).toFixed(1).replace(/\.0$/, '')}%</div>
                          </div>
                          <div className="p-1.5 bg-white border border-slate-200 rounded">
                            <div className="text-slate-400 text-[10px]">L2 (2/4)</div>
                            <div className="font-bold text-slate-700">{(numWeight * 0.5).toFixed(1).replace(/\.0$/, '')}%</div>
                          </div>
                          <div className="p-1.5 bg-white border border-slate-200 rounded">
                            <div className="text-slate-400 text-[10px]">L3 (3/4)</div>
                            <div className="font-bold text-slate-700">{(numWeight * 0.75).toFixed(1).replace(/\.0$/, '')}%</div>
                          </div>
                          <div className="p-1.5 bg-white border border-emerald-300 bg-emerald-50/50 rounded">
                            <div className="text-emerald-700 text-[10px]">L4 (4/4)</div>
                            <div className="font-bold text-emerald-800">{numWeight.toFixed(1).replace(/\.0$/, '')}%</div>
                          </div>
                        </div>

                        {/* Level Descriptor summary */}
                        <div className="text-[11px] text-slate-500 space-y-1 pt-1">
                          {COMMON_LEVEL_DESCRIPTORS.map((lvl) => (
                            <div key={lvl.level} className="flex items-baseline gap-2">
                              <span className="font-bold font-mono text-slate-700 w-14 shrink-0">Level {lvl.level}:</span>
                              <span className="text-slate-600">{lvl.label} - {lvl.description}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Configuration Inputs */}
                    <div className="grid sm:grid-cols-2 gap-3 pt-1">
                      <div>
                        <label htmlFor="criterion-weight" className="block text-xs font-semibold text-slate-700 mb-1">
                          Assigned Weight (%)
                        </label>
                        <input
                          id="criterion-weight"
                          required
                          type="number"
                          min="0.01"
                          max="100"
                          step="0.01"
                          value={weight}
                          onChange={(e) => setWeight(e.target.value)}
                          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs font-mono font-semibold text-slate-900 focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                        />
                      </div>
                      <div>
                        <label htmlFor="criterion-evaluation-method" className="block text-xs font-semibold text-slate-700 mb-1">
                          Evaluation Method
                        </label>
                        <select
                          id="criterion-evaluation-method"
                          value={evaluationMethod}
                          onChange={(e) => setEvaluationMethod(e.target.value)}
                          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs font-medium text-slate-900 focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                        >
                          {EVALUATION_METHODS.map((method) => (
                            <option key={method.value} value={method.value}>
                              {method.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-8 text-center text-slate-400 text-xs flex flex-col items-center justify-center border border-dashed border-slate-200 rounded-xl">
                    <HelpCircle className="w-8 h-8 text-slate-300 mb-2" />
                    <span>Select a criterion from the catalog on the left to preview details.</span>
                  </div>
                )}
              </div>
            ) : (
              /* Edit Mode: Focused criterion form */
              <div className="space-y-4 max-w-2xl mx-auto">
                <div className="grid sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="criterion-code" className="block text-xs font-semibold text-slate-700 mb-1">Criterion Code</label>
                    <input
                      id="criterion-code"
                      disabled
                      value={code}
                      className="w-full px-3 py-2 border border-slate-200 bg-slate-100 rounded-lg text-xs font-mono font-bold text-slate-700"
                    />
                  </div>
                  <div>
                    <label htmlFor="criterion-title" className="block text-xs font-semibold text-slate-700 mb-1">Title</label>
                    <input
                      id="criterion-title"
                      required
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-900 focus:ring-2 focus:ring-sky-500"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="criterion-description" className="block text-xs font-semibold text-slate-700 mb-1">Description</label>
                  <textarea
                    id="criterion-description"
                    required
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs text-slate-900 focus:ring-2 focus:ring-sky-500"
                  />
                </div>

                {selectedCatalog && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <p className="text-xs font-bold text-slate-700">
                      {selectedCatalog.semanticPreview
                        ? 'Kiểm chứng thường — có tính điểm'
                        : 'What is graded'}
                    </p>
                    <ul className="mt-2 space-y-1.5 text-xs text-slate-600">
                      {selectedCatalog.gradingBullets.map((bullet) => (
                        <li key={bullet} className="flex gap-2">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                          <span>{bullet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {selectedCatalog?.semanticPreview && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-bold text-amber-900">Semantic checks</p>
                      <span className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[10px] font-bold text-amber-800">
                        Chưa tính điểm
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-amber-800">
                      Không lưu evaluator semantic và không dùng để tính điểm.
                    </p>
                  </div>
                )}

                <div className="grid sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="criterion-edit-weight" className="block text-xs font-semibold text-slate-700 mb-1">Weight (%)</label>
                    <input
                      id="criterion-edit-weight"
                      required
                      type="number"
                      min="0.01"
                      max="100"
                      step="0.01"
                      value={weight}
                      onChange={(e) => setWeight(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs font-mono font-semibold text-slate-900 focus:ring-2 focus:ring-sky-500"
                    />
                  </div>
                  <div>
                    <label htmlFor="criterion-edit-evaluation-method" className="block text-xs font-semibold text-slate-700 mb-1">Evaluation Method</label>
                    <select
                      id="criterion-edit-evaluation-method"
                      value={evaluationMethod}
                      onChange={(e) => setEvaluationMethod(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs font-medium text-slate-900 focus:ring-2 focus:ring-sky-500"
                    >
                      {EVALUATION_METHODS.map((method) => (
                        <option key={method.value} value={method.value}>
                          {method.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Read-only scoring explanation */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-700">Scoring Formula</span>
                    <span className="font-mono text-xs font-bold text-slate-800 bg-white border border-slate-200 px-2 py-0.5 rounded">
                      Score = (Level / 4) × {numWeight || 0}%
                    </span>
                  </div>
                  <div className="grid grid-cols-5 gap-1.5 text-[11px] font-mono text-center pt-1">
                    <div className="p-1 bg-white border border-slate-200 rounded">
                      <div className="text-slate-400 text-[10px]">L0 (0%)</div>
                      <div className="font-bold text-slate-700">0%</div>
                    </div>
                    <div className="p-1 bg-white border border-slate-200 rounded">
                      <div className="text-slate-400 text-[10px]">L1 (25%)</div>
                      <div className="font-bold text-slate-700">{(numWeight * 0.25).toFixed(1).replace(/\.0$/, '')}%</div>
                    </div>
                    <div className="p-1 bg-white border border-slate-200 rounded">
                      <div className="text-slate-400 text-[10px]">L2 (50%)</div>
                      <div className="font-bold text-slate-700">{(numWeight * 0.5).toFixed(1).replace(/\.0$/, '')}%</div>
                    </div>
                    <div className="p-1 bg-white border border-slate-200 rounded">
                      <div className="text-slate-400 text-[10px]">L3 (75%)</div>
                      <div className="font-bold text-slate-700">{(numWeight * 0.75).toFixed(1).replace(/\.0$/, '')}%</div>
                    </div>
                    <div className="p-1 bg-white border border-emerald-300 bg-emerald-50 rounded">
                      <div className="text-emerald-700 text-[10px]">L4 (100%)</div>
                      <div className="font-bold text-emerald-800">{numWeight.toFixed(1).replace(/\.0$/, '')}%</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Modal Footer */}
          <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-slate-200 bg-slate-50">
            <button
              type="button"
              onClick={requestClose}
              disabled={saving}
              className="px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-50 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || (mode === 'add' && (!selectedCatalog || isAlreadyAddedInRubric(selectedCatalog.code)))}
              className="px-4 py-2 bg-[#1F4B7A] hover:bg-[#183b60] text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {saving ? 'Saving...' : mode === 'edit' ? 'Save changes' : 'Add to rubric'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export const RubricTemplatesView: React.FC = () => {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState('');
  const [newRubricName, setNewRubricName] = useState('');

  // Rubric metadata editing state
  const [isEditingMetadata, setIsEditingMetadata] = useState(false);
  const [rubricNameEdit, setRubricNameEdit] = useState('');
  const [rubricDescEdit, setRubricDescEdit] = useState('');

  // Criterion Modal State
  const [criterionModalOpen, setCriterionModalOpen] = useState(false);
  const [criterionModalMode, setCriterionModalMode] = useState<'add' | 'edit'>('add');
  const [editingCriterion, setEditingCriterion] = useState<ApiCriterion | undefined>();

  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  // Queries
  const rubricsQuery = useQuery({
    queryKey: ['rubrics'],
    queryFn: () => apiData(api.GET('/api/v1/rubrics')),
  });
  const rubrics = rubricsQuery.data ?? [];
  const selectedRubric = rubrics.find((rubric) => rubric.id === selectedId);

  const criteriaQuery = useQuery({
    queryKey: ['rubric-criteria', selectedId],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/rubrics/{rubric_id}/criteria', {
          params: { path: { rubric_id: selectedId } },
        })
      ),
    enabled: Boolean(selectedId),
  });
  const criteria = criteriaQuery.data ?? [];

  // Auto-select first rubric
  useEffect(() => {
    if (rubrics.length > 0 && !rubrics.some((rubric) => rubric.id === selectedId)) {
      setSelectedId(rubrics[0].id);
    }
  }, [rubrics, selectedId]);

  // Sync metadata edit form when selected rubric changes
  useEffect(() => {
    if (selectedRubric) {
      setRubricNameEdit(selectedRubric.name);
      setRubricDescEdit(selectedRubric.description ?? '');
    }
    setIsEditingMetadata(false);
    setError(undefined);
  }, [selectedRubric]);

  const enabledCriteria = useMemo(
    () => criteria.filter((criterion) => criterion.is_enabled),
    [criteria],
  );
  const totalWeight = useMemo(
    () =>
      enabledCriteria.reduce(
        (sum, criterion) => sum + (parseFloat(String(criterion.weight)) || 0),
        0,
      ),
    [enabledCriteria],
  );
  const hasCompleteScales =
    enabledCriteria.length > 0 &&
    enabledCriteria.every((criterion) => hasCompleteLevelScale(criterion.levels));
  const isReady = Math.abs(totalWeight - 100) < 0.001 && hasCompleteScales;

  const refreshRubrics = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rubrics'] });
  };

  const refreshCriteria = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rubric-criteria', selectedId] });
    await refreshRubrics();
  };

  // Create Rubric
  const createRubric = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newRubricName.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      const rubric = await apiData(
        api.POST('/api/v1/rubrics', {
          body: {
            name: newRubricName.trim(),
            description: null,
            calculation_method: 'WEIGHTED_SUM',
          },
        })
      );
      setNewRubricName('');
      await refreshRubrics();
      setSelectedId(rubric.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  // Save Rubric Metadata
  const saveRubricMetadata = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedRubric || !rubricNameEdit.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await apiData(
        api.PUT('/api/v1/rubrics/{rubric_id}', {
          params: { path: { rubric_id: selectedRubric.id } },
          body: {
            name: rubricNameEdit.trim(),
            description: rubricDescEdit.trim() || null,
          },
        })
      );
      await refreshRubrics();
      setIsEditingMetadata(false);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  // Delete Rubric
  const deleteRubric = async () => {
    if (!selectedRubric) return;
    if (
      !window.confirm(
        `Are you sure you want to delete rubric "${selectedRubric.name}"? This action cannot be undone.`
      )
    ) {
      return;
    }

    setBusy(true);
    setError(undefined);
    try {
      await apiVoid(
        api.DELETE('/api/v1/rubrics/{rubric_id}', {
          params: { path: { rubric_id: selectedRubric.id } },
        }),
      );
      const remaining = rubrics.filter((r) => r.id !== selectedRubric.id);
      setSelectedId(remaining[0]?.id ?? '');
      await refreshRubrics();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  // Open modal in Add mode
  const openAddCriterionModal = () => {
    setEditingCriterion(undefined);
    setCriterionModalMode('add');
    setCriterionModalOpen(true);
  };

  // Open modal in Edit mode
  const openEditCriterionModal = (criterion: ApiCriterion) => {
    setEditingCriterion(criterion);
    setCriterionModalMode('edit');
    setCriterionModalOpen(true);
  };

  // Delete Criterion
  const deleteCriterion = async (criterion: ApiCriterion) => {
    if (!selectedRubric || !window.confirm(`Delete criterion ${criterion.code}?`)) return;
    setBusy(true);
    setError(undefined);
    try {
      await apiVoid(
        api.DELETE('/api/v1/rubrics/{rubric_id}/criteria/{criterion_id}', {
          params: { path: { rubric_id: selectedRubric.id, criterion_id: criterion.id } },
        })
      );
      await refreshCriteria();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Rubric Builder</h1>
        <p className="text-sm text-slate-500 mt-1">
          Create, customize, and configure criterion rubrics for assignment evaluation.
        </p>
      </div>

      {/* Global Alert Banner */}
      {(error || rubricsQuery.error || criteriaQuery.error) && (
        <div role="alert" className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-700 text-sm flex items-start gap-2.5">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold">Operation Failed</p>
            <p className="mt-0.5 text-xs">
              {error ?? getErrorMessage(rubricsQuery.error ?? criteriaQuery.error)}
            </p>
          </div>
        </div>
      )}

      {/* Master / Detail Layout */}
      <div className="grid lg:grid-cols-[300px_1fr] gap-6 items-start">
        {/* Left Column: Rubric List & Create */}
        <aside className="space-y-4">
          {/* Create Form */}
          <form onSubmit={createRubric} className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-600">Create Rubric</h2>
            <div className="flex gap-2">
              <input
                required
                value={newRubricName}
                onChange={(e) => setNewRubricName(e.target.value)}
                placeholder="Rubric name"
                aria-label="New rubric name"
                className="flex-1 min-w-0 px-3 py-2 border border-slate-300 rounded-lg text-xs focus:ring-2 focus:ring-sky-500 focus:outline-none"
              />
              <button
                type="submit"
                disabled={busy || !newRubricName.trim()}
                className="inline-flex items-center gap-1 px-3 py-2 bg-[#1F4B7A] hover:bg-[#183b60] text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-50"
              >
                <Plus className="w-4 h-4" />
                <span>Create</span>
              </button>
            </div>
          </form>

          {/* Rubrics List */}
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
                Saved Rubrics ({rubrics.length})
              </span>
            </div>

            {rubrics.length === 0 ? (
              <p className="p-6 text-center border border-dashed border-slate-300 rounded-xl text-xs text-slate-500">
                No rubrics created yet. Use form above to create your first rubric.
              </p>
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto pr-0.5">
                {rubrics.map((rubric) => {
                  const isSelected = selectedId === rubric.id;
                  const isRubric100 = Math.abs(parseFloat(String(rubric.total_weight)) - 100) < 0.001;

                  return (
                    <button
                      key={rubric.id}
                      type="button"
                      onClick={() => setSelectedId(rubric.id)}
                      aria-pressed={isSelected}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all ${
                        isSelected
                          ? 'border-sky-500 bg-sky-50/70 shadow-xs ring-1 ring-sky-300'
                          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs font-bold text-slate-900 leading-snug">{rubric.name}</p>
                        <span
                          className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${
                            isRubric100
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {parseFloat(String(rubric.total_weight))}%
                        </span>
                      </div>
                      {rubric.description && (
                        <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">{rubric.description}</p>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </aside>

        {/* Right Column: Selected Rubric Details & Criteria */}
        {selectedRubric ? (
          <section className="space-y-5">
            {/* Metadata Card */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-2xs space-y-4">
              {isEditingMetadata ? (
                <form onSubmit={saveRubricMetadata} className="space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700">Edit Rubric Details</h3>
                  </div>
                  <div>
                    <label htmlFor="rubric-name" className="block text-xs font-semibold text-slate-700 mb-1">Rubric Name</label>
                    <input
                      id="rubric-name"
                      required
                      value={rubricNameEdit}
                      onChange={(e) => setRubricNameEdit(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-slate-900 focus:ring-2 focus:ring-sky-500"
                    />
                  </div>
                  <div>
                    <label htmlFor="rubric-description" className="block text-xs font-semibold text-slate-700 mb-1">Description (Optional)</label>
                    <textarea
                      id="rubric-description"
                      rows={2}
                      value={rubricDescEdit}
                      onChange={(e) => setRubricDescEdit(e.target.value)}
                      placeholder="Add an optional description for this rubric..."
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs text-slate-900 focus:ring-2 focus:ring-sky-500"
                    />
                  </div>
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setIsEditingMetadata(false)}
                      className="px-3 py-1.5 border border-slate-300 bg-white text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={busy || !rubricNameEdit.trim()}
                      className="px-4 py-1.5 bg-[#1F4B7A] text-white rounded-lg text-xs font-semibold hover:bg-[#183b60] disabled:opacity-50"
                    >
                      Save changes
                    </button>
                  </div>
                </form>
              ) : (
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-bold text-slate-900">{selectedRubric.name}</h2>
                    <p className="text-xs text-slate-600 mt-1">
                      {selectedRubric.description || (
                        <span className="italic text-slate-400">No description provided.</span>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => setIsEditingMetadata(true)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 text-slate-700 bg-white hover:bg-slate-50 rounded-lg text-xs font-semibold transition-colors"
                    >
                      <Pencil className="w-3.5 h-3.5 text-slate-500" />
                      <span>Edit</span>
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={deleteRubric}
                      aria-label={`Delete rubric ${selectedRubric.name}`}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-rose-200 text-rose-700 bg-rose-50/50 hover:bg-rose-100 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Live Weight Readiness & Add Criterion Toolbar */}
            <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div
                  className={`w-12 h-12 rounded-xl flex items-center justify-center font-bold text-sm shrink-0 ${
                    isReady
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-amber-100 text-amber-800'
                  }`}
                >
                  {totalWeight.toFixed(0)}%
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-900">Total Weight:</span>
                    <span
                      className={`font-mono text-xs font-bold px-2 py-0.5 rounded ${
                        isReady
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                          : 'bg-amber-50 text-amber-700 border border-amber-200'
                      }`}
                    >
                      {totalWeight.toFixed(1).replace(/\.0$/, '')} / 100%
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {isReady ? (
                      <span className="text-emerald-700 font-medium inline-flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Rubric is ready: 100% and levels 0–4
                      </span>
                    ) : !hasCompleteScales && criteria.length > 0 ? (
                      <span className="text-amber-700 font-medium inline-flex items-center gap-1">
                        <AlertCircle className="w-3.5 h-3.5" /> Every criterion needs score levels 0–4
                      </span>
                    ) : totalWeight > 100 ? (
                      <span className="text-rose-600 font-medium inline-flex items-center gap-1">
                        <AlertCircle className="w-3.5 h-3.5" /> Exceeds 100% by {(totalWeight - 100).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-amber-700 font-medium inline-flex items-center gap-1">
                        <AlertCircle className="w-3.5 h-3.5" /> Incomplete: {(100 - totalWeight).toFixed(1)}% remaining to reach 100%
                      </span>
                    )}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={openAddCriterionModal}
                className="inline-flex items-center justify-center gap-1.5 px-4 py-2.5 bg-[#1F4B7A] hover:bg-[#183b60] text-white rounded-lg text-xs font-semibold transition-colors shadow-2xs"
              >
                <Plus className="w-4 h-4" />
                <span>Add criterion</span>
              </button>
            </div>

            {/* Criteria List */}
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600">
                  Criteria ({criteria.length})
                </h3>
              </div>

              {criteria.length === 0 ? (
                <div className="p-8 text-center border border-dashed border-slate-300 bg-slate-50/50 rounded-xl space-y-3">
                  <p className="text-xs text-slate-500">No criteria added to this rubric yet.</p>
                  <button
                    type="button"
                    onClick={openAddCriterionModal}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-50"
                  >
                    <Plus className="w-4 h-4 text-slate-500" />
                    <span>Select criterion from catalog</span>
                  </button>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {criteria.map((criterion) => {
                    const matchedCatalog = DEFAULT_SRS_CATALOG.find(
                      (c) => c.code.toUpperCase() === criterion.code.toUpperCase()
                    );

                    return (
                      <article
                        key={criterion.id}
                        className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs hover:border-slate-300 transition-colors"
                      >
                        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                          <div className="space-y-1.5 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-xs font-bold text-sky-800 bg-sky-100 px-2 py-0.5 rounded">
                                {criterion.code}
                              </span>
                              <h4 className="font-bold text-slate-900 text-sm">{criterion.title}</h4>
                            </div>
                            <p className="text-xs text-slate-600">{criterion.description}</p>

                            {/* Concrete grading bullets if available */}
                            {matchedCatalog?.gradingBullets && matchedCatalog.gradingBullets.length > 0 && (
                              <div className="pt-2">
                                <ul className="grid sm:grid-cols-2 gap-1.5 text-[11px] text-slate-600">
                                  {matchedCatalog.gradingBullets.map((bullet, idx) => (
                                    <li key={idx} className="flex items-start gap-1.5">
                                      <span className="text-sky-600 font-bold">•</span>
                                      <span className="line-clamp-2">{bullet}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>

                          <div className="flex sm:flex-col items-center sm:items-end justify-between gap-2 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-100">
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-xs font-bold text-slate-900 bg-slate-100 px-2 py-0.5 rounded">
                                {criterion.weight}%
                              </span>
                              <span className="text-[10px] font-semibold text-slate-600 bg-slate-50 border border-slate-200 px-1.5 py-0.5 rounded">
                                {criterion.evaluation_method}
                              </span>
                            </div>

                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => openEditCriterionModal(criterion)}
                                aria-label={`Edit ${criterion.code}`}
                                className="p-1.5 text-slate-500 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
                              >
                                <Pencil className="w-4 h-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => deleteCriterion(criterion)}
                                aria-label={`Delete ${criterion.code}`}
                                className="p-1.5 text-rose-500 hover:text-rose-700 hover:bg-rose-50 rounded-lg transition-colors"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        ) : (
          <div className="p-12 text-center border border-dashed border-slate-300 rounded-2xl bg-slate-50/50">
            <p className="text-sm font-semibold text-slate-700">No Rubric Selected</p>
            <p className="text-xs text-slate-500 mt-1">Select an existing rubric from the left or create a new one.</p>
          </div>
        )}
      </div>

      {/* Criterion Modal */}
      {selectedRubric && (
        <CriterionModal
          isOpen={criterionModalOpen}
          mode={criterionModalMode}
          rubricId={selectedRubric.id}
          existingCriteria={criteria}
          criterionToEdit={editingCriterion}
          onClose={() => setCriterionModalOpen(false)}
          onSaved={refreshCriteria}
        />
      )}
    </div>
  );
};
