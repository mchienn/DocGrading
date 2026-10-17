import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileQuestion,
  HelpCircle,
  Info,
  LockKeyhole,
  LocateFixed,
  Send,
  XCircle,
} from 'lucide-react';
import { useBeforeUnload, useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { ApiError, api, apiData, apiVoid, getErrorMessage } from '../../api/client';
import { getFindingPresentation, PdfEvidenceViewer } from './PdfEvidenceViewer';

type Finding = components['schemas']['FindingResponse'];
type Decision = components['schemas']['ReviewDecisionRequest'];
type DraftContent = Omit<components['schemas']['ReviewDraftRequest'], 'revision'>;
type EvidenceWorkspace = components['schemas']['EvidenceWorkspaceResponse'];
type ReviewDraft = components['schemas']['ReviewDraftResponse'];
type SemanticPipelineStatus = components['schemas']['SemanticPipelineStatus'];
type CitationReport = components['schemas']['CitationReportResponse'];
type SaveStatus = 'saved' | 'saving' | 'conflict' | 'error';

interface CriterionTab {
  id: string;
  code: string;
  title: string;
  findings: Finding[];
  totalFindings: number;
}

const semanticVerdicts: SemanticPipelineStatus[] = [
  'SUPPORTED',
  'PARTIALLY_SUPPORTED',
  'CONTRADICTED',
  'IRRELEVANT',
  'INSUFFICIENT_EVIDENCE',
  'SOURCE_UNAVAILABLE',
  'AMBIGUOUS_CLAIM',
  'NEEDS_MANUAL_REVIEW',
];

interface ReviewWorkspaceViewProps {
  role: 'teacher' | 'admin';
}
function trapFocus(event: React.KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== 'Tab') return;
  const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
    'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  ));
  const first = elements[0];
  const last = elements.at(-1);
  const wrap = event.shiftKey
    ? document.activeElement === first || document.activeElement === event.currentTarget
    : document.activeElement === last;
  if (!wrap) return;
  event.preventDefault();
  (event.shiftKey ? last : first)?.focus();
}


function serializeDraft(draft: DraftContent): string {
  return JSON.stringify(draft);
}
function getSemanticStatusConfig(status: SemanticPipelineStatus) {
  switch (status) {
    case 'SUPPORTED':
      return {
        label: 'Supported',
        badgeClass: 'bg-emerald-50 text-emerald-800 border-emerald-300',
        icon: CheckCircle2,
        iconClass: 'text-emerald-600',
      };
    case 'PARTIALLY_SUPPORTED':
      return {
        label: 'Partially supported',
        badgeClass: 'bg-amber-50 text-amber-800 border-amber-300',
        icon: AlertTriangle,
        iconClass: 'text-amber-600',
      };
    case 'CONTRADICTED':
      return {
        label: 'Contradicted',
        badgeClass: 'bg-rose-50 text-rose-800 border-rose-300',
        icon: XCircle,
        iconClass: 'text-rose-600',
      };
    case 'IRRELEVANT':
      return {
        label: 'Irrelevant',
        badgeClass: 'bg-rose-50 text-rose-800 border-rose-300',
        icon: XCircle,
        iconClass: 'text-rose-600',
      };
    case 'INSUFFICIENT_EVIDENCE':
      return {
        label: 'Insufficient evidence',
        badgeClass: 'bg-slate-100 text-slate-800 border-slate-300',
        icon: HelpCircle,
        iconClass: 'text-slate-600',
      };
    case 'SOURCE_UNAVAILABLE':
      return {
        label: 'Source unavailable',
        badgeClass: 'bg-slate-100 text-slate-800 border-slate-300',
        icon: FileQuestion,
        iconClass: 'text-slate-600',
      };
    case 'AMBIGUOUS_CLAIM':
      return {
        label: 'Ambiguous claim',
        badgeClass: 'bg-amber-50 text-amber-800 border-amber-300',
        icon: AlertCircle,
        iconClass: 'text-amber-600',
      };
    case 'NEEDS_MANUAL_REVIEW':
      return {
        label: 'Needs manual review',
        badgeClass: 'bg-amber-50 text-amber-800 border-amber-300',
        icon: AlertCircle,
        iconClass: 'text-amber-600',
      };
    default:
      return {
        label: status,
        badgeClass: 'bg-slate-100 text-slate-800 border-slate-300',
        icon: Info,
        iconClass: 'text-slate-600',
      };
  }
}

const findingSeverityLabels: Record<string, string> = {
  critical: 'Nghiêm trọng',
  error: 'Lỗi',
  high: 'Cao',
  info: 'Thông tin',
  low: 'Thấp',
  major: 'Quan trọng',
  medium: 'Trung bình',
  minor: 'Nhẹ',
  needs_review: 'Cần xem xét',
  warning: 'Cảnh báo',
};

function findingSeverityLabel(severity: string): string {
  return findingSeverityLabels[severity.toLowerCase()] ?? 'Chưa phân loại';
}

const citationIssueLabels: Record<string, string> = {
  AMBIGUOUS: 'Khớp nhiều tài liệu tham khảo',
  AMBIGUOUS_MAPPING: 'Chưa xác định được tài liệu tham khảo tương ứng',
  DUPLICATE: 'Tài liệu tham khảo có thể bị trùng',
  FINDINGS_TRUNCATED: 'Còn vấn đề trích dẫn chưa hiển thị',
  FRAGMENTED_REFERENCE: 'Mục tài liệu tham khảo chưa đầy đủ',
  METADATA_MISMATCH: 'Thông tin tài liệu không khớp nguồn',
  ORPHAN_MENTION: 'Trích dẫn không có mục tài liệu tham khảo',
  PARSER_UNCERTAIN: 'Cần kiểm tra cách phân tích trích dẫn',
  UNCITED_REFERENCE: 'Tài liệu tham khảo chưa được trích dẫn',
  UNRESOLVED: 'Không xác minh được tài liệu tham khảo',
};

function citationIssueLabel(status: string): string {
  return citationIssueLabels[status]
    ?? status.toLowerCase().replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

function citationIssueFor(finding: Finding, citation?: CitationReport) {
  const internalId = finding.description.match(/\b(?:mention|reference)-[a-z0-9-]+\b/i)?.[0];
  const referenceNumber = finding.description.match(/Bibliography entry \[(\d+)\]/i)?.[1];
  if (referenceNumber) {
    const reference = citation?.issues.find(
      (candidate) => candidate.id === `reference-${referenceNumber}`,
    );
    if (reference) return reference;
  }
  if (internalId) {
    const direct = citation?.issues.find((candidate) => candidate.id === internalId);
    if (direct) return direct;
  }
  const evidenceKeys = new Set(
    finding.evidence.map((item) => `${item.element_id}:${item.page_number}`),
  );
  return citation?.issues.find((candidate) =>
    evidenceKeys.has(`${candidate.element_id}:${candidate.page_number}`)
    || candidate.anchors.some((anchor) =>
      evidenceKeys.has(`${anchor.element_id}:${anchor.page_number}`),
    ),
  );
}

function citationTarget(issue: CitationReport['issues'][number]): string {
  const referenceNumber = issue.id.match(/^reference-(\d+)$/i)?.[1];
  if (referenceNumber) return `Tài liệu tham khảo [${referenceNumber}]`;
  const marker = issue.snippet.match(/\[(?:\d+(?:\s*[-,]\s*\d+)*)\]/)?.[0];
  return marker ? `Trích dẫn ${marker}` : `Trích dẫn ở trang ${issue.page_number}`;
}

function findingSummary(finding: Finding, citation?: CitationReport): string {
  const issue = citationIssueFor(finding, citation);
  if (issue) return `${citationTarget(issue)}: ${citationIssueLabel(issue.status)}.`;
  if (/\b(?:mention|reference)-[a-z0-9-]+\b/i.test(finding.description)) {
    const page = finding.evidence[0]?.page_number;
    return `Vấn đề trích dẫn${page ? ` ở trang ${page}` : ''}; cần kiểm tra đoạn được đánh dấu.`;
  }
  const normalized = finding.description.replace(/\s+/g, ' ').trim();
  return normalized.length > 180 ? `${normalized.slice(0, 177).trimEnd()}...` : normalized;
}

function findingDescription(finding: Finding, citation?: CitationReport): string {
  const issue = citationIssueFor(finding, citation);
  if (!issue) return finding.description;
  const normalizedSnippet = issue.snippet.replace(/\s+/g, ' ').trim();
  const snippet = normalizedSnippet.length > 180
    ? `${normalizedSnippet.slice(0, 177).trimEnd()}...`
    : normalizedSnippet;
  return `${citationTarget(issue)}: ${citationIssueLabel(issue.status)} (trang ${issue.page_number}).${snippet ? ` Ngữ cảnh: “${snippet}”.` : ''}`;
}

const queuePageSize = 100;

async function loadDocumentStatus(courseId: string, submissionId: string): Promise<string> {
  for (let page = 1; ; page += 1) {
    const queue = await apiData(api.GET('/api/v1/courses/{course_id}/submission-queue', {
      params: {
        path: { course_id: courseId },
        query: { sort: 'desc', page, page_size: queuePageSize },
      },
    }));
    const submission = queue.items.find((item) => item.submission_id === submissionId);
    if (submission) return submission.document_status ?? 'NO_DOCUMENT';
    if (page * queue.page_size >= queue.total) throw new Error('Submission not found in course queue');
  }
}

export const ReviewWorkspaceView: React.FC<ReviewWorkspaceViewProps> = ({ role }) => {
  const { courseId = '', submissionId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const routeState = location.state as { documentStatus?: string } | null;
  const [documentStatus, setDocumentStatus] = useState<string | undefined>(routeState?.documentStatus);
  const [reviewLock, setReviewLock] = useState<components['schemas']['ReviewLockResponse']>();
  const [lockError, setLockError] = useState<string>();
  const [draft, setDraft] = useState<DraftContent>();
  const [selectedFindingId, setSelectedFindingId] = useState<string>();
  const [activeCriterionId, setActiveCriterionId] = useState<string>();
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved');
  const [saveError, setSaveError] = useState<string>();
  const [action, setAction] = useState<'approve' | 'publish'>();
  const [actionError, setActionError] = useState<string>();
  const [showPublish, setShowPublish] = useState(false);
  const [publishReason, setPublishReason] = useState('');
  const [publishedResultId, setPublishedResultId] = useState<string>();
  const [leaving, setLeaving] = useState(false);
  const [expandedSemanticResults, setExpandedSemanticResults] = useState(false);
  const revisionRef = useRef(1);
  const lastSavedRef = useRef('');
  const draftRef = useRef<DraftContent>();
  const queuedRef = useRef<DraftContent>();
  const savePromiseRef = useRef<Promise<void>>();
  const approveKeyRef = useRef(crypto.randomUUID());
  const publishAttemptRef = useRef<{ key: string; reason: string }>();
  const hydratedDocumentRef = useRef<string>();
  const navigationBypassRef = useRef(false);
  const exitPromiseRef = useRef<Promise<boolean>>();
  const publishButtonRef = useRef<HTMLButtonElement>(null);
  const publishDialogRef = useRef<HTMLDialogElement>(null);
  const publishReasonRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!showPublish) return;
    const dialog = publishDialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    publishReasonRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      publishButtonRef.current?.focus();
    };
  }, [showPublish]);

  const hydrateDraft = useCallback((evidence: EvidenceWorkspace, stored: ReviewDraft) => {
    const loaded: DraftContent = {
      document_version_id: evidence.document_version_id,
      comment: stored.comment,
      decisions: stored.decisions,
    };
    hydratedDocumentRef.current = evidence.document_version_id;
    revisionRef.current = stored.revision;
    lastSavedRef.current = serializeDraft(loaded);
    queuedRef.current = undefined;
    draftRef.current = loaded;
    setDraft(loaded);
    setSaveStatus('saved');
    setSaveError(undefined);
    setSelectedFindingId(evidence.findings[0]?.id);
    setActiveCriterionId(evidence.findings[0]?.criterion_version_id);
  }, []);

  const evidenceQuery = useQuery({
    queryKey: ['submission-evidence', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/evidence', {
      params: { path: { submission_id: submissionId } },
    })),
    enabled: Boolean(submissionId),
  });
  const draftQuery = useQuery({
    queryKey: ['review-draft', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/review-draft', {
      params: { path: { submission_id: submissionId } },
    })),
    enabled: Boolean(submissionId),
  });
  const statusQuery = useQuery({
    queryKey: ['submission-document-status', courseId, submissionId],
    queryFn: () => loadDocumentStatus(courseId, submissionId),
    enabled: Boolean(courseId && submissionId && !routeState?.documentStatus),
  });

  useEffect(() => {
    if (statusQuery.data) setDocumentStatus(statusQuery.data);
  }, [statusQuery.data]);

  useEffect(() => {
    const evidence = evidenceQuery.data;
    const stored = draftQuery.data;
    if (!evidence || !stored || hydratedDocumentRef.current === evidence.document_version_id) return;
    hydrateDraft(evidence, stored);
  }, [draftQuery.data, evidenceQuery.data, hydrateDraft]);

  const reloadServerDraft = async () => {
    const result = await draftQuery.refetch();
    if (result.data && evidenceQuery.data) hydrateDraft(evidenceQuery.data, result.data);
  };

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const acquireLock = useCallback(async () => {
    setLockError(undefined);
    try {
      setReviewLock(await apiData(api.POST('/api/v1/submissions/{submission_id}/review-lock', {
        params: { path: { submission_id: submissionId } },
      })));
    } catch (error) {
      setLockError(getErrorMessage(error));
    }
  }, [submissionId]);

  useEffect(() => {
    if (!submissionId || documentStatus !== 'AWAITING_REVIEW') return;
    void acquireLock();
  }, [acquireLock, documentStatus, submissionId]);

  useEffect(() => {
    if (!reviewLock?.acquired) return;
    const interval = window.setInterval(() => {
      void apiData(api.PUT('/api/v1/submissions/{submission_id}/review-lock/heartbeat', {
        params: { path: { submission_id: submissionId } },
      })).then(setReviewLock).catch((error) => {
        setReviewLock((current) => current ? { ...current, acquired: false } : current);
        setLockError(getErrorMessage(error));
      });
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [reviewLock?.acquired, submissionId]);

  const drainSaves = useCallback((): Promise<void> => {
    if (savePromiseRef.current) return savePromiseRef.current;
    const savePromise = (async () => {
      while (queuedRef.current) {
        const content = queuedRef.current;
        queuedRef.current = undefined;
        setSaveStatus('saving');
        try {
          const saved = await apiData(api.PUT('/api/v1/submissions/{submission_id}/review-draft', {
            params: { path: { submission_id: submissionId } },
            body: { ...content, revision: revisionRef.current },
          }));
          revisionRef.current = saved.revision;
          lastSavedRef.current = serializeDraft(content);
          setSaveError(undefined);
          const latest = draftRef.current;
          if (!queuedRef.current && latest && serializeDraft(latest) === lastSavedRef.current) {
            setSaveStatus('saved');
          }
        } catch (error) {
          queuedRef.current = undefined;
          setSaveStatus(error instanceof ApiError && error.status === 409 ? 'conflict' : 'error');
          setSaveError(getErrorMessage(error));
          break;
        }
      }
    })();
    savePromiseRef.current = savePromise;
    void savePromise.finally(() => {
      if (savePromiseRef.current === savePromise) savePromiseRef.current = undefined;
    });
    return savePromise;
  }, [submissionId]);

  const canEdit = reviewLock?.acquired === true && documentStatus === 'AWAITING_REVIEW';
  const editable = !leaving && canEdit;
  useEffect(() => {
    if (!draft || !editable || serializeDraft(draft) === lastSavedRef.current) return;
    setSaveStatus('saving');
    const timeout = window.setTimeout(() => {
      queuedRef.current = draft;
      void drainSaves();
    }, 800);
    return () => window.clearTimeout(timeout);
  }, [draft, drainSaves, editable]);

  const findings = evidenceQuery.data?.findings ?? [];
  const citation = evidenceQuery.data?.citation;
  const semanticCitation = evidenceQuery.data?.semantic_citation;
  const decisions = draft?.decisions ?? [];
  const decisionByFinding = useMemo(
    () => new Map(decisions.map((decision) => [decision.finding_id, decision])),
    [decisions],
  );

  const criteria = useMemo<CriterionTab[]>(() => {
    const map = new Map<string, CriterionTab>();
    for (const finding of findings) {
      const existing = map.get(finding.criterion_version_id);
      if (existing) {
        existing.findings.push(finding);
        existing.totalFindings += 1;
      } else {
        map.set(finding.criterion_version_id, {
          id: finding.criterion_version_id,
          code: finding.criterion_code,
          title: finding.criterion_title,
          findings: [finding],
          totalFindings: 1,
        });
      }
    }
    return Array.from(map.values());
  }, [findings]);
  // Decision counts live outside `criteria` so edits don't change finding-group identity
  // (PdfEvidenceViewer receives activeFindings).
  const decidedCount = (criterion?: CriterionTab) =>
    criterion?.findings.filter((finding) => decisionByFinding.has(finding.id)).length ?? 0;

  useEffect(() => {
    if (!criteria.length) return;
    if (!activeCriterionId || !criteria.some((c) => c.id === activeCriterionId)) {
      setActiveCriterionId(criteria[0].id);
    }
  }, [criteria, activeCriterionId]);

  const activeCriterion = criteria.find((c) => c.id === activeCriterionId) ?? criteria[0];
  const activeFindings = activeCriterion?.findings ?? [];
  const selectedFinding = activeFindings.find((finding) => finding.id === selectedFindingId) ?? activeFindings[0];
  const allDecided = findings.length > 0 && findings.every((finding) => decisions.some((decision) => decision.finding_id === finding.id));

  const handleSelectCriterion = (criterionId: string) => {
    setActiveCriterionId(criterionId);
    const targetGroup = criteria.find((c) => c.id === criterionId);
    if (targetGroup && targetGroup.findings.length > 0) {
      const stillValid = targetGroup.findings.some((f) => f.id === selectedFindingId);
      if (!stillValid) {
        setSelectedFindingId(targetGroup.findings[0].id);
      }
    }
  };

  const selectFindingWithCriterion = (finding: Finding) => {
    setActiveCriterionId(finding.criterion_version_id);
    setSelectedFindingId(finding.id);
    setTimeout(() => {
      const el = document.getElementById(`finding-card-${finding.id}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
  };

  const jumpToFindingInPdf = (findingId: string) => {
    setSelectedFindingId(findingId);
    document.getElementById('pdf-evidence-panel')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  };

  const advanceToNextFinding = () => {
    if (!activeFindings.length) return;
    const currentIndex = activeFindings.findIndex((f) => f.id === selectedFinding?.id);
    const nextIndex = (currentIndex + 1) % activeFindings.length;
    const nextFinding = activeFindings[nextIndex];
    setSelectedFindingId(nextFinding.id);
    const el = document.getElementById(`finding-card-${nextFinding.id}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const semanticResultByFinding = useMemo(() => {
    const mapped = new Map<string, NonNullable<typeof semanticCitation>['results'][number]>();
    for (const result of semanticCitation?.results ?? []) {
      for (const link of result.finding_links ?? []) {
        mapped.set(link.finding_id, result);
      }
    }
    return mapped;
  }, [semanticCitation]);

  const focusTextByFindingId = useMemo(() => {
    const map: Record<string, string> = {};
    for (const finding of findings) {
      const semanticResult = semanticResultByFinding.get(finding.id);
      if (semanticResult?.claim) {
        map[finding.id] = semanticResult.claim.trim();
        continue;
      }
      const directRefMatch = finding.description.match(/\breference-(\d+)\b/i);
      if (directRefMatch) {
        map[finding.id] = `[${directRefMatch[1]}]`;
        continue;
      }
      const issueIds = new Set(
        (finding.description.match(/\b(?:reference|mention)-[a-zA-Z0-9_-]+\b/gi) ?? [])
          .map((issueId) => issueId.toLowerCase()),
      );
      const matchedIssue = citation?.issues?.find(
        (issue) => issueIds.has(issue.id.toLowerCase()),
      );
      if (matchedIssue) {
        const bracketMatch = matchedIssue.snippet?.match(/\[[\d\s,–-]+\]/)
          || matchedIssue.snippet?.match(/\[[^\]]+\]/);
        if (bracketMatch) {
          map[finding.id] = bracketMatch[0].trim();
          continue;
        }
      }
      const directBracketMatch = finding.description.match(/\[[\d\s,–-]+\]/);
      if (directBracketMatch) {
        map[finding.id] = directBracketMatch[0].trim();
      }
    }
    return map;
  }, [findings, citation?.issues, semanticResultByFinding]);

  const changeDecision = (finding: Finding, decision: Decision['decision']) => {
    setDraft((current) => {
      if (!current) return current;
      const existing = current.decisions?.find((item) => item.finding_id === finding.id);
      const next: Decision = decision === 'EDIT'
        ? {
            finding_id: finding.id,
            decision,
            edited_description: existing?.edited_description ?? findingDescription(finding, citation),
            final_score: existing?.final_score ?? finding.proposed_score,
            reason: existing?.reason ?? null,
            edited_semantic_verdict: existing?.edited_semantic_verdict ?? null,
          }
        : {
            finding_id: finding.id,
            decision,
            reason: existing?.reason ?? null,
          };
      const currentDecisions = current.decisions ?? [];
      const index = currentDecisions.findIndex((item) => item.finding_id === next.finding_id);
      const updated = index < 0
        ? [...currentDecisions, next]
        : currentDecisions.map((item, currentIndex) => currentIndex === index ? next : item);
      return { ...current, decisions: updated };
    });
  };

  const updateDecision = (findingId: string, patch: Partial<Decision>) => {
    setDraft((current) => {
      if (!current) return current;
      const existing = current.decisions?.find((decision) => decision.finding_id === findingId);
      if (!existing) return current;
      const currentDecisions = current.decisions ?? [];
      const next = { ...existing, ...patch };
      return {
        ...current,
        decisions: currentDecisions.map((decision) => decision.finding_id === findingId ? next : decision),
      };
    });
  };

  const draftDirty = Boolean(draft && serializeDraft(draft) !== lastSavedRef.current);
  const shouldBlockNavigation = draftDirty || saveStatus === 'saving' || reviewLock?.acquired === true;
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    !navigationBypassRef.current
    && shouldBlockNavigation
    && (
      currentLocation.pathname !== nextLocation.pathname
      || currentLocation.search !== nextLocation.search
      || currentLocation.hash !== nextLocation.hash
    ));
  const handleBeforeUnload = useCallback((event: BeforeUnloadEvent) => {
    if (!draftDirty && saveStatus !== 'saving') return;
    event.preventDefault();
    event.returnValue = '';
  }, [draftDirty, saveStatus]);
  useBeforeUnload(handleBeforeUnload);

  const prepareToLeave = useCallback((): Promise<boolean> => {
    if (exitPromiseRef.current) return exitPromiseRef.current;
    const exitPromise = (async () => {
      setLeaving(true);
      const latest = draftRef.current;
      if (canEdit && latest && serializeDraft(latest) !== lastSavedRef.current) {
        queuedRef.current = latest;
        setSaveStatus('saving');
        await drainSaves();
        const savedLatest = draftRef.current;
        if (savedLatest && serializeDraft(savedLatest) !== lastSavedRef.current) {
          setLeaving(false);
          return false;
        }
      }
      if (reviewLock?.acquired) {
        try {
          await apiVoid(api.DELETE('/api/v1/submissions/{submission_id}/review-lock', {
            params: { path: { submission_id: submissionId } },
          }));
        } catch {
          // Lock expires server-side if release cannot reach API.
        }
      }
      return true;
    })();
    exitPromiseRef.current = exitPromise;
    void exitPromise.finally(() => {
      if (exitPromiseRef.current === exitPromise) exitPromiseRef.current = undefined;
    });
    return exitPromise;
  }, [canEdit, drainSaves, reviewLock?.acquired, submissionId]);

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    let active = true;
    const { proceed, reset } = blocker;
    void prepareToLeave().then((ready) => {
      if (!active) return;
      if (ready) {
        navigationBypassRef.current = true;
        proceed();
      } else {
        reset();
      }
    });
    return () => { active = false; };
  }, [blocker, prepareToLeave]);

  const leave = async () => {
    if (!await prepareToLeave()) return;
    navigationBypassRef.current = true;
    navigate(`/${role}/courses/${courseId}/submissions`);
  };

  const approve = async () => {
    const versionId = evidenceQuery.data?.document_version_id;
    if (!versionId) return;
    setAction('approve');
    setActionError(undefined);
    try {
      const response = await apiData(api.POST('/api/v1/document-versions/{version_id}/approve', {
        params: {
          path: { version_id: versionId },
          header: { 'Idempotency-Key': approveKeyRef.current },
        },
      }));
      setDocumentStatus(response.status);
      try {
        await apiVoid(api.DELETE('/api/v1/submissions/{submission_id}/review-lock', {
          params: { path: { submission_id: submissionId } },
        }));
      } catch {
        // Approved document is immutable even if lock release cannot reach API.
      }
      setReviewLock((current) => current ? { ...current, acquired: false } : current);
      await queryClient.invalidateQueries({ queryKey: ['submission-queue', courseId] });
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setAction(undefined);
    }
  };

  const publish = async () => {
    const versionId = evidenceQuery.data?.document_version_id;
    const reason = publishReason.trim();
    if (!versionId || !reason) return;
    const attempt = publishAttemptRef.current ?? {
      key: crypto.randomUUID(),
      reason,
    };
    publishAttemptRef.current = attempt;
    setPublishReason(attempt.reason);
    setAction('publish');
    setActionError(undefined);
    try {
      const response = await apiData(api.POST('/api/v1/document-versions/{version_id}/publish', {
        params: {
          path: { version_id: versionId },
          header: { 'Idempotency-Key': attempt.key },
        },
        body: { reason: attempt.reason },
      }));
      setDocumentStatus('PUBLISHED');
      setPublishedResultId(response.published_result_id);
      setShowPublish(false);
      await queryClient.invalidateQueries({ queryKey: ['submission-queue', courseId] });
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setAction(undefined);
    }
  };

  const loadError = evidenceQuery.error ?? draftQuery.error ?? statusQuery.error;
  const saveLabel = saveStatus === 'saved'
    ? 'saved'
    : saveStatus === 'saving'
      ? 'saving'
      : saveStatus;

  return (
    <div className="p-4 sm:p-6 max-w-[1800px] mx-auto space-y-4">
      <header className="sticky top-2 z-30 bg-white border border-slate-200 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-sm">
        <div className="flex items-center gap-3 min-w-0">
          <button type="button" disabled={leaving} onClick={() => void leave()} className="p-2 border border-slate-300 rounded-lg disabled:opacity-40" aria-label="Back to queue">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="min-w-0">
            <h1 className="font-bold text-slate-900">Review Workspace</h1>
            <p className="font-mono text-xs text-slate-500 truncate">Submission {submissionId}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {findings.length > 0 && (
            <span className="px-2 py-1 rounded border border-slate-200 bg-slate-50 font-mono text-xs text-slate-700">
              {decisions.length}/{findings.length} decided
            </span>
          )}
          <span className="px-2 py-1 rounded border border-slate-200 bg-slate-50 font-mono text-xs">{documentStatus ?? 'LOADING_STATUS'}</span>
          <span className={`px-2 py-1 rounded border font-mono text-xs ${saveStatus === 'conflict' ? 'border-rose-300 bg-rose-50 text-rose-700' : 'border-slate-200 bg-white text-slate-600'}`}>
            {saveLabel}
          </span>
          <button
            type="button"
            disabled={!editable || !allDecided || saveStatus !== 'saved' || action !== undefined}
            onClick={() => void approve()}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-900 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
          >
            <CheckCircle2 className="w-4 h-4" /> {action === 'approve' ? 'Approving...' : 'Approve'}
          </button>
          <button
            ref={publishButtonRef}
            type="button"
            disabled={documentStatus !== 'APPROVED' || action !== undefined}
            onClick={() => setShowPublish(true)}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
          >
            <Send className="w-4 h-4" /> Publish
          </button>
        </div>
      </header>

      {(loadError || lockError || saveError || actionError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm flex items-start justify-between gap-3">
          <span>{actionError ?? saveError ?? lockError ?? getErrorMessage(loadError)}</span>
          {lockError && documentStatus === 'AWAITING_REVIEW' && (
            <button type="button" onClick={() => void acquireLock()} className="underline shrink-0">Retry lock</button>
          )}
          {(saveStatus === 'conflict' || saveStatus === 'error') && draft && (
            <span className="flex gap-2 shrink-0">
              <button type="button" onClick={() => void reloadServerDraft()} className="underline">Reload server draft</button>
              {saveStatus === 'error' && <button type="button" onClick={() => { queuedRef.current = draft; void drainSaves(); }} className="underline">Retry save</button>}
            </span>
          )}
        </div>
      )}

      {publishedResultId && (
        <div role="status" className="p-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-sm">
          Published result <span className="font-mono break-all">{publishedResultId}</span>
        </div>
      )}

      {documentStatus === 'AWAITING_REVIEW' && !reviewLock?.acquired && !lockError && (
        <div className="p-3 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2">
            <LockKeyhole className="w-4 h-4" />
            {reviewLock ? `Read-only: locked by ${reviewLock.reviewer_display_name ?? 'another reviewer'} until ${reviewLock.expires_at ? new Date(reviewLock.expires_at).toLocaleString() : 'expiry'}.` : 'Acquiring review lock...'}
          </span>
          {reviewLock && <button type="button" onClick={() => void acquireLock()} className="underline shrink-0">Retry lock</button>}
        </div>
      )}

      {evidenceQuery.isLoading || draftQuery.isLoading ? (
        <p className="p-8 text-center text-slate-500">Loading evidence and review draft...</p>
      ) : !evidenceQuery.data || !draft ? null : (
        <>
          {criteria.length > 0 && (
            <nav aria-label="Rubric criteria tabs" className="border-b border-slate-200">
              <div role="tablist" aria-label="Rubric criteria" className="flex flex-wrap gap-2 pb-2">
                {criteria.map((criterion) => {
                  const isActive = criterion.id === activeCriterion?.id;
                  const isComplete = criterion.totalFindings > 0 && decidedCount(criterion) === criterion.totalFindings;
                  return (
                    <button
                      key={criterion.id}
                      id={`criterion-tab-${criterion.id}`}
                      role="tab"
                      aria-selected={isActive}
                      aria-controls="criterion-panel"
                      tabIndex={isActive ? 0 : -1}
                      onClick={() => handleSelectCriterion(criterion.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                          e.preventDefault();
                          const currentIndex = criteria.findIndex((c) => c.id === criterion.id);
                          const delta = e.key === 'ArrowRight' ? 1 : -1;
                          const nextIndex = (currentIndex + delta + criteria.length) % criteria.length;
                          handleSelectCriterion(criteria[nextIndex].id);
                          document.getElementById(`criterion-tab-${criteria[nextIndex].id}`)?.focus();
                        }
                      }}
                      className={`group inline-flex items-center gap-2 px-3.5 py-2 rounded-lg font-medium text-xs transition focus:outline-none focus:ring-2 focus:ring-sky-400 ${
                        isActive
                          ? 'bg-slate-900 text-white shadow-sm'
                          : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 hover:text-slate-900'
                      }`}
                    >
                      <span className="font-bold">{criterion.code}</span>
                      <span className="max-w-[200px] truncate" title={criterion.title}>
                        {criterion.title}
                      </span>
                      <span
                        className={`ml-1 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                          isActive
                            ? isComplete
                              ? 'bg-emerald-500/25 text-emerald-200'
                              : 'bg-white/20 text-white'
                            : isComplete
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {isComplete && <Check className="w-2.5 h-2.5 inline" />}
                        {decidedCount(criterion)}/{criterion.totalFindings}
                      </span>
                    </button>
                  );
                })}
              </div>
            </nav>
          )}

          <div className="grid lg:grid-cols-[minmax(0,1.55fr)_minmax(380px,1fr)] gap-4 items-start min-w-0">
            <div id="pdf-evidence-panel" className="min-w-0 scroll-mt-20">
              <PdfEvidenceViewer
                documentVersionId={evidenceQuery.data.document_version_id}
                findings={activeFindings}
                selectedFindingId={selectedFinding?.id}
                onSelectFinding={setSelectedFindingId}
                focusTexts={focusTextByFindingId}
              />
            </div>

            <section
              id="criterion-panel"
              role="tabpanel"
              aria-labelledby={activeCriterion ? `criterion-tab-${activeCriterion.id}` : undefined}
              className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5 space-y-4 min-w-0 w-full lg:max-h-[calc(100vh-10rem)] lg:overflow-y-auto lg:overflow-x-hidden shadow-sm"
              aria-label={`Review decisions for ${activeCriterion?.title ?? 'criterion'}`}
            >
              <div className="border-b border-slate-200 pb-3 flex flex-wrap items-center justify-between gap-2 min-w-0">
                <div className="min-w-0">
                  {activeCriterion && (
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-slate-900">{activeCriterion.code}</span>
                      <span className="text-xs text-slate-500 truncate">· {activeCriterion.title}</span>
                    </div>
                  )}
                  <p className="text-xs text-slate-500 mt-0.5">
                    {activeFindings.length} finding{activeFindings.length === 1 ? '' : 's'} ({decidedCount(activeCriterion)} decided)
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  {activeFindings.length > 1 && (
                    <button
                      type="button"
                      onClick={advanceToNextFinding}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 text-xs font-medium"
                      title="Jump to next finding in this criterion"
                    >
                      <span>Next</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>

              <label className="block text-sm font-semibold text-slate-800 min-w-0">
                Review comment
                <textarea
                  rows={3}
                  maxLength={10_000}
                  disabled={!editable}
                  value={draft.comment}
                  onChange={(event) => setDraft((current) => current ? { ...current, comment: event.target.value } : current)}
                  className="block w-full max-w-full min-w-0 mt-2 p-3 border border-slate-300 rounded-lg font-normal disabled:bg-slate-100 box-border break-words [overflow-wrap:anywhere]"
                  placeholder="Add general review comments or feedback for this submission..."
                />
              </label>

              <div className="space-y-3 min-w-0">
                {activeFindings.map((finding, findingIndex) => {
                  const decision = decisionByFinding.get(finding.id);
                  const semanticResult = semanticResultByFinding.get(finding.id);
                  const issue = citationIssueFor(finding, citation);
                  const summary = findingSummary(finding, citation);
                  const pres = getFindingPresentation(finding.id);
                  const isSelected = selectedFinding?.id === finding.id;

                  return (
                    <article
                      key={finding.id}
                      id={`finding-card-${finding.id}`}
                      className={`p-4 rounded-xl border-2 transition-all min-w-0 w-full box-border break-words [overflow-wrap:anywhere] ${
                        isSelected ? 'border-sky-500 bg-sky-50/40 shadow-sm ring-1 ring-sky-300' : 'border-slate-200 bg-white hover:border-slate-300'
                      }`}
                      style={{
                        borderLeftWidth: '5px',
                        borderLeftColor: pres.borderColor,
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedFindingId(finding.id)}
                        className="w-full text-left min-w-0 focus:outline-none"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2 text-[11px] text-slate-500">
                          <span
                            className="inline-flex items-center gap-1 font-semibold text-slate-700"
                            title={finding.severity}
                          >
                            <span aria-hidden="true" style={{ color: pres.borderColor }}>{pres.symbol}</span>
                            Phát hiện {findingIndex + 1} · {findingSeverityLabel(finding.severity)}
                          </span>
                          <div className="flex flex-wrap justify-end gap-1">
                            {issue && (
                              <span className="px-1.5 py-0.5 rounded bg-rose-100 text-rose-800 font-semibold text-[10px]">
                                {citationIssueLabel(issue.status)}
                              </span>
                            )}
                            {decision ? (
                              <span
                                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-bold text-[10px] uppercase ${
                                  decision.decision === 'ACCEPT'
                                    ? 'bg-emerald-100 text-emerald-800'
                                    : decision.decision === 'EDIT'
                                      ? 'bg-sky-100 text-sky-800'
                                      : 'bg-rose-100 text-rose-800'
                                }`}
                              >
                                {decision.decision === 'ACCEPT' ? '✓ Đã chấp nhận' : decision.decision === 'EDIT' ? '✎ Đã sửa' : '✗ Đã loại'}
                              </span>
                            ) : (
                              <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-semibold text-[10px]">
                                Chờ quyết định
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="mt-1.5 text-sm font-medium text-slate-800 leading-snug break-words [overflow-wrap:anywhere]">
                          {summary}
                        </p>
                      </button>

                      <details className="mt-2 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-600">
                        <summary className="cursor-pointer font-semibold text-slate-700">Chi tiết ngữ cảnh</summary>
                        <div className="mt-2 space-y-2">
                          <p>Trang PDF: {issue?.page_number ?? finding.evidence[0]?.page_number ?? 'không xác định'} · Bằng chứng: {finding.evidence.length}</p>
                          <blockquote className="border-l-2 border-slate-300 pl-2 whitespace-pre-wrap">
                            {issue?.snippet || finding.description.replace(/\b(?:mention|reference)-[a-z0-9-]+\b/gi, 'trích dẫn')}
                          </blockquote>
                          {finding.suggestion && <p><strong>Gợi ý:</strong> {finding.suggestion}</p>}
                          <p>Điểm đề xuất: {finding.proposed_score ?? 'không có'}</p>
                        </div>
                      </details>

                      <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-100">
                        <button
                          type="button"
                          onClick={() => jumpToFindingInPdf(finding.id)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-sky-300 bg-sky-50 text-sky-800 text-xs font-semibold"
                        >
                          <LocateFixed className="w-3.5 h-3.5" /> Xem trên PDF
                        </button>
                        {(['ACCEPT', 'EDIT', 'REJECT'] as const).map((value) => (
                          <button
                            key={value}
                            type="button"
                            disabled={!editable}
                            onClick={() => changeDecision(finding, value)}
                            className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition disabled:opacity-40 ${
                              decision?.decision === value
                                ? 'bg-slate-900 border-slate-900 text-white shadow-sm'
                                : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
                            }`}
                          >
                            {value}
                          </button>
                        ))}
                      </div>

                      {decision?.decision === 'EDIT' && (
                        <div className="grid gap-2 mt-3 p-3 bg-slate-50/70 border border-slate-200 rounded-lg min-w-0 w-full box-border">
                          <label className="text-xs text-slate-700 font-medium block w-full min-w-0">
                            Edited description
                            <textarea
                              maxLength={10_000}
                              rows={3}
                              disabled={!editable}
                              value={decision.edited_description ?? ''}
                              onChange={(event) => updateDecision(finding.id, { edited_description: event.target.value || null })}
                              className="block w-full max-w-full min-w-0 mt-1 p-2 border border-slate-300 rounded-lg bg-white box-border text-xs break-words [overflow-wrap:anywhere]"
                            />
                          </label>

                          {semanticResult && (
                            <label className="text-xs text-slate-700 font-medium block w-full min-w-0">
                              Semantic verdict override
                              <select
                                disabled={!editable}
                                value={decision.edited_semantic_verdict ?? ''}
                                onChange={(event) => {
                                  const verdict = event.target.value as SemanticPipelineStatus | '';
                                  updateDecision(finding.id, {
                                    edited_semantic_verdict: verdict && verdict !== semanticResult.status
                                      ? verdict
                                      : null,
                                  });
                                }}
                                className="block w-full max-w-full min-w-0 mt-1 p-2 border border-slate-300 rounded-lg bg-white box-border text-xs truncate"
                              >
                                <option value="">Keep pipeline verdict ({semanticResult.status})</option>
                                {semanticVerdicts.map((verdict) => (
                                  <option key={verdict} value={verdict}>{verdict}</option>
                                ))}
                              </select>
                            </label>
                          )}

                          <label className="text-xs text-slate-700 font-medium block w-full min-w-0">
                            Final score
                            <input
                              type="number"
                              min={0}
                              max={100}
                              step={0.01}
                              disabled={!editable}
                              value={decision.final_score ?? ''}
                              onChange={(event) => updateDecision(finding.id, { final_score: event.target.value || null })}
                              className="block w-full max-w-full min-w-0 mt-1 p-2 border border-slate-300 rounded-lg bg-white box-border text-xs"
                            />
                          </label>
                        </div>
                      )}

                      {decision && (
                        <label className="block mt-3 text-xs text-slate-700 font-medium w-full min-w-0">
                          Override reason {
                            decision.decision === 'REJECT' || decision.edited_semantic_verdict
                              ? '(required)'
                              : decision.decision === 'ACCEPT'
                                ? '(required when restoring an override)'
                                : '(required when score changes)'
                          }
                          <textarea
                            rows={2}
                            maxLength={2_000}
                            disabled={!editable}
                            value={decision.reason ?? ''}
                            onChange={(event) => updateDecision(finding.id, { reason: event.target.value || null })}
                            className="block w-full max-w-full min-w-0 mt-1 p-2 border border-slate-300 rounded-lg bg-white box-border text-xs break-words [overflow-wrap:anywhere]"
                            placeholder="Explain reason for this decision..."
                          />
                        </label>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          </div>

          {(citation || semanticCitation) && (
            <details className="group rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <summary className="flex cursor-pointer select-none flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-slate-50/80 hover:bg-slate-100/80 transition text-xs">
                <div className="flex flex-wrap items-center gap-3 min-w-0">
                  <span className="font-semibold text-slate-800 inline-flex items-center gap-1.5">
                    <Info className="w-4 h-4 text-slate-500" />
                    Analysis Diagnostics & Summaries
                  </span>
                  {citation && (
                    <span className="inline-flex items-center gap-1 text-slate-600 bg-white border border-slate-200 rounded px-2 py-0.5 text-[11px]">
                      Citations: {citation.counts.verified}/{citation.counts.references} verified ({Math.round(citation.counts.verified_rate * 100)}%)
                    </span>
                  )}
                  {semanticCitation && (
                    <span
                      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium border ${
                        semanticCitation.quality_gate.passed
                          ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                          : 'bg-amber-50 text-amber-800 border-amber-200'
                      }`}
                    >
                      Gate: {semanticCitation.quality_gate.passed ? 'Passed' : 'Blocked'}
                      {semanticCitation.semantic_support_score != null &&
                        ` · Support: ${Math.round(semanticCitation.semantic_support_score)}%`}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1 text-slate-500 text-[11px] font-medium">
                  <span className="group-open:hidden inline-flex items-center gap-1">
                    Show details <ChevronDown className="w-3.5 h-3.5" />
                  </span>
                  <span className="hidden group-open:inline-flex items-center gap-1">
                    Hide details <ChevronUp className="w-3.5 h-3.5" />
                  </span>
                </div>
              </summary>

              <div className="p-4 space-y-4 border-t border-slate-200">
                {citation && (
                  <section aria-label="Citation checks" className="space-y-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h2 className="font-semibold text-slate-900">Citation checks</h2>
                        <p className="text-xs text-slate-500">
                          Deterministic identity and in-text linkage. Unresolved does not mean false.
                        </p>
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {citation.counts.references} references · {citation.counts.mentions} mentions
                      </span>
                    </div>
                    {(citation.parser_status !== 'PARSED' ||
                      citation.bibliography_status !== 'PARSED' ||
                      (citation.parser_warnings?.length ?? 0) > 0) && (
                      <div
                        role="alert"
                        className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"
                      >
                        <p className="font-semibold">
                          Citation analysis incomplete. Manual review required.
                        </p>
                        <p className="mt-1">
                          Parser: {citation.parser_status} · Bibliography: {citation.bibliography_status}
                        </p>
                        {(citation.parser_warnings ?? []).slice(0, 4).map((warning) => (
                          <p key={warning} className="mt-1">{warning}</p>
                        ))}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 lg:grid-cols-7">
                      <div className="rounded-lg bg-emerald-50 p-2 text-emerald-800">
                        Verified: {citation.counts.verified} ({Math.round(citation.counts.verified_rate * 100)}%)
                      </div>
                      <div className="rounded-lg bg-sky-50 p-2 text-sky-800">
                        Linked: {citation.counts.linked} ({Math.round(citation.counts.linkage_rate * 100)}%)
                      </div>
                      <div className="rounded-lg bg-amber-50 p-2 text-amber-800">
                        Unresolved: {citation.counts.unresolved}
                      </div>
                      <div className="rounded-lg bg-rose-50 p-2 text-rose-800">
                        Mismatch: {citation.counts.metadata_mismatch}
                      </div>
                      <div className="rounded-lg bg-rose-50 p-2 text-rose-800">
                        Orphan: {citation.counts.orphan_mentions}
                      </div>
                      <div className="rounded-lg bg-amber-50 p-2 text-amber-800">
                        Uncited: {citation.counts.uncited_references}
                      </div>
                      <div className="rounded-lg bg-amber-50 p-2 text-amber-800">
                        Ambiguous: {citation.counts.ambiguous}
                      </div>
                    </div>
                    {citation.issues.length > 0 && (
                      <ul className="space-y-1 text-xs text-slate-600">
                        {citation.issues.slice(0, 8).map((issue) => (
                          <li key={`${issue.id}:${issue.status}`} className="flex gap-2">
                            <span className="font-medium text-slate-700">{citationIssueLabel(issue.status)}</span>
                            <span>Page {issue.page_number} · {issue.snippet}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                )}

                {semanticCitation && (
                  <section aria-label="Citation semantic support" className="space-y-4 pt-3 border-t border-slate-200">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h2 className="font-semibold text-slate-900">Citation semantic support</h2>
                        <p className="text-xs text-slate-500">
                          Source support for report claims, not scientific truth.
                        </p>
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {semanticCitation.results.length} claim-source result{semanticCitation.results.length === 1 ? '' : 's'}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                      <div className="rounded-lg bg-slate-50 p-2.5 border border-slate-200">
                        <span className="text-slate-500 block text-[11px]">Support score</span>
                        <span className="font-semibold text-slate-900 text-sm">
                          {semanticCitation.semantic_support_score != null
                            ? `${Math.round(semanticCitation.semantic_support_score)}%`
                            : 'Not scored'}
                        </span>
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2.5 border border-slate-200">
                        <span className="text-slate-500 block text-[11px]">Semantic coverage</span>
                        <span className="font-semibold text-slate-900 text-sm">
                          {Math.round(semanticCitation.semantic_coverage * 100)}%
                        </span>
                        <span className="text-[10px] text-slate-500 block">
                          {semanticCitation.evaluable_claim_count} of {semanticCitation.eligible_linked_claim_count} evaluable claims
                        </span>
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2.5 border border-slate-200">
                        <span className="text-slate-500 block text-[11px]">Proposed score</span>
                        <span className="font-semibold text-slate-900 text-sm">
                          {semanticCitation.proposed_score != null
                            ? `${Math.round(semanticCitation.proposed_score)}%`
                            : 'None'}
                        </span>
                      </div>
                      <div className={`rounded-lg p-2.5 border ${
                        semanticCitation.quality_gate.passed
                          ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                          : 'bg-amber-50 border-amber-200 text-amber-900'
                      }`}>
                        <span className="block text-[11px] font-medium">Quality gate</span>
                        <span className="font-semibold text-sm inline-flex items-center gap-1 mt-0.5">
                          {semanticCitation.quality_gate.passed ? (
                            <>
                              <CheckCircle2 className="w-4 h-4 text-emerald-600" /> Passed
                            </>
                          ) : (
                            <>
                              <AlertTriangle className="w-4 h-4 text-amber-600" /> Blocked
                            </>
                          )}
                        </span>
                      </div>
                    </div>

                    {!semanticCitation.quality_gate.passed && (
                      <div
                        role="alert"
                        className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 flex items-start gap-2"
                      >
                        <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                        <div>
                          <p className="font-semibold">
                            Quality gate blocked: findings are review-only and no automatic score is applied.
                          </p>
                          {semanticCitation.quality_gate.reason && (
                            <p className="mt-1 text-amber-800">
                              Reason: {semanticCitation.quality_gate.reason}
                            </p>
                          )}
                        </div>
                      </div>
                    )}

                    {semanticCitation.results.length > 0 && (
                      <div className="space-y-3 pt-2">
                        <div className="flex items-center justify-between">
                          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                            Claim results ({semanticCitation.results.length})
                          </h3>
                          {semanticCitation.results.length > 20 && (
                            <button
                              type="button"
                              onClick={() => setExpandedSemanticResults((prev) => !prev)}
                              className="text-xs text-sky-700 hover:underline font-medium"
                            >
                              {expandedSemanticResults
                                ? 'Show first 20 claims'
                                : `Show all ${semanticCitation.results.length} claims`}
                            </button>
                          )}
                        </div>

                        <div className="space-y-3">
                          {(expandedSemanticResults
                            ? semanticCitation.results
                            : semanticCitation.results.slice(0, 20)
                          ).map((result, index) => {
                            const statusCfg = getSemanticStatusConfig(result.status);
                            const StatusIcon = statusCfg.icon;
                            const firstLink = result.finding_links?.[0];
                            const linkedFinding = firstLink
                              ? findings.find((f) => f.id === firstLink.finding_id)
                              : undefined;

                            return (
                              <article
                                key={result.pair_id || index}
                                className="rounded-lg border border-slate-200 bg-slate-50/50 p-3.5 space-y-2.5 text-xs"
                              >
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span
                                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-semibold border text-xs ${statusCfg.badgeClass}`}
                                    >
                                      <StatusIcon className={`w-3.5 h-3.5 ${statusCfg.iconClass}`} />
                                      {statusCfg.label}
                                    </span>

                                    {result.manual_review_required && (
                                      <span className="px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-900 border border-amber-300 text-[11px]">
                                        Manual review required
                                      </span>
                                    )}

                                    <span className="font-mono text-slate-500 text-[11px]">
                                      Reason: <span className="text-slate-700 font-semibold">{result.reason_code}</span>
                                    </span>

                                    {result.source_access_type && (
                                      <span className="font-mono text-slate-500 text-[11px]">
                                        Access: <span className="text-slate-700">{result.source_access_type}</span>
                                      </span>
                                    )}

                                    <span className="text-slate-500 text-[11px]">
                                      Report: Page {result.claim_anchor.page_number}
                                      {result.claim_anchor.line_start != null && (
                                        <>
                                          , Lines {result.claim_anchor.line_start}
                                          {result.claim_anchor.line_end != null && result.claim_anchor.line_end !== result.claim_anchor.line_start
                                            ? `–${result.claim_anchor.line_end}`
                                            : ''}
                                        </>
                                      )}
                                    </span>
                                  </div>

                                  <div>
                                    {linkedFinding ? (
                                      <button
                                        type="button"
                                        onClick={() => selectFindingWithCriterion(linkedFinding)}
                                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg bg-sky-50 text-sky-700 border border-sky-200 hover:bg-sky-100 transition-colors"
                                      >
                                        Review linked finding
                                      </button>
                                    ) : (
                                      <span className="text-[11px] text-slate-400 italic">
                                        No review finding link
                                      </span>
                                    )}
                                  </div>
                                </div>

                                <div className="bg-white p-2.5 rounded border border-slate-200">
                                  <span className="text-[11px] font-semibold text-slate-500 block uppercase tracking-wide mb-1">
                                    Claim verbatim:
                                  </span>
                                  <p className="text-slate-900 text-xs italic leading-relaxed break-words [overflow-wrap:anywhere]">
                                    "{result.claim}"
                                  </p>
                                </div>

                                {((result.supported_parts && result.supported_parts.length > 0) ||
                                  (result.unsupported_parts && result.unsupported_parts.length > 0)) && (
                                  <div className="grid sm:grid-cols-2 gap-2 text-xs">
                                    {result.supported_parts && result.supported_parts.length > 0 && (
                                      <div className="p-2 rounded bg-emerald-50/70 border border-emerald-200 text-emerald-900">
                                        <span className="font-semibold block text-[11px]">Supported parts:</span>
                                        <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-[11px]">
                                          {result.supported_parts.map((part, i) => (
                                            <li key={i} className="leading-snug break-words [overflow-wrap:anywhere]">{part}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    )}
                                    {result.unsupported_parts && result.unsupported_parts.length > 0 && (
                                      <div className="p-2 rounded bg-rose-50/70 border border-rose-200 text-rose-900">
                                        <span className="font-semibold block text-[11px]">Unsupported parts:</span>
                                        <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-[11px]">
                                          {result.unsupported_parts.map((part, i) => (
                                            <li key={i} className="leading-snug break-words [overflow-wrap:anywhere]">{part}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    )}
                                  </div>
                                )}

                                <div className="pt-1">
                                  {result.status === 'SOURCE_UNAVAILABLE' ? (
                                    <div className="text-xs text-slate-600 italic bg-white p-2 rounded border border-slate-200">
                                      No source evidence available (source could not be retrieved; this is not an automatic student error).
                                    </div>
                                  ) : result.source_passages && result.source_passages.length > 0 ? (
                                    <details className="group">
                                      <summary className="cursor-pointer text-xs font-medium text-slate-600 hover:text-slate-900 select-none py-1">
                                        Source evidence passages ({Math.min(result.source_passages.length, 3)} of {result.source_passages.length})
                                      </summary>
                                      <div className="mt-2 space-y-2 pl-2 border-l-2 border-slate-200">
                                        {result.source_passages.slice(0, 3).map((passage, pIdx) => (
                                          <div
                                            key={passage.passage_id ?? pIdx}
                                            className="bg-white p-2.5 rounded border border-slate-200 text-xs space-y-1"
                                          >
                                            <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-500 gap-1">
                                              <span className="font-semibold text-slate-700">Passage {pIdx + 1}</span>
                                              <div className="flex items-center gap-2">
                                                <span>{passage.page_number != null ? `Page ${passage.page_number}` : 'No PDF page'}</span>
                                                {passage.section && <span>· Section: {passage.section}</span>}
                                                <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-mono text-[10px]">
                                                  {passage.kind}
                                                </span>
                                              </div>
                                            </div>
                                            <p className="text-slate-800 text-[11px] font-mono leading-relaxed bg-slate-50/50 p-2 rounded border border-slate-100 whitespace-pre-wrap max-h-32 overflow-y-auto break-words [overflow-wrap:anywhere]">
                                              {passage.text}
                                            </p>
                                          </div>
                                        ))}
                                      </div>
                                    </details>
                                  ) : (
                                    <div className="text-xs text-slate-400 italic">
                                      No source passages available.
                                    </div>
                                  )}
                                </div>
                              </article>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </section>
                )}
              </div>
            </details>
          )}
        </>
      )}

      {showPublish && (
        <dialog
          ref={publishDialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="publish-title"
          tabIndex={-1}
          onKeyDown={trapFocus}
          onCancel={(event) => {
            event.preventDefault();
            setShowPublish(false);
          }}
          className="m-auto w-[calc(100%-2rem)] max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-xl backdrop:bg-slate-900/60"
        >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="publish-title" className="font-bold text-slate-900">Confirm publish</h2>
                <p className="text-sm text-rose-700 mt-1">Students see result immediately. Reversal requires separate audited unpublish.</p>
              </div>
              <button type="button" onClick={() => setShowPublish(false)} aria-label="Close publish dialog"><XCircle className="w-5 h-5" /></button>
            </div>
            <label className="block text-sm font-semibold text-slate-700">Publish reason
              <textarea
                ref={publishReasonRef}
                required
                maxLength={2_000}
                rows={3}
                disabled={Boolean(publishAttemptRef.current) || action === 'publish'}
                value={publishReason}
                onChange={(event) => setPublishReason(event.target.value)}
                className="block w-full mt-2 p-3 border border-slate-300 rounded-lg font-normal"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowPublish(false)} className="px-3 py-2 border border-slate-300 rounded-lg text-sm">Cancel</button>
              <button
                type="button"
                disabled={!publishReason.trim() || action === 'publish'}
                onClick={() => void publish()}
                className="px-3 py-2 bg-emerald-700 text-white rounded-lg text-sm font-semibold disabled:opacity-40"
              >
                {action === 'publish' ? 'Publishing...' : 'Confirm publish'}
              </button>
            </div>
        </dialog>
      )}
    </div>
  );
};
