import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  ExternalLink,
  FileText,
  History,
  Loader2,
  Maximize2,
  Pin,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import { PdfMarkerViewer, type PdfMarker } from './PdfEvidenceViewer';
import {
  createChatSession,
  deleteChatSession,
  listChatMessages,
  listChatSessions,
  listScopeSubmissions,
  sendChatMessage,
  updateChatSession,
  type ChatCitation,
  type ChatPayload,
  type ChatSession,
  type ClarificationOption,
  type CourseScope,
} from '../../services/chatService';

// ---------------------------------------------------------------------------
// Shared message rendering
// ---------------------------------------------------------------------------

interface UiMessage {
  id: string;
  sender: 'user' | 'bot';
  content: string;
  createdAt: string;
  payload?: ChatPayload;
  isError?: boolean;
}

interface Scope {
  courseId: CourseScope;
  submissionId: string | null;
  assignmentId?: string | null;
}

const CLASS_SUGGESTIONS = [
  'Tình hình báo cáo lớp thế nào?',
  'Còn bao nhiêu bài chưa duyệt?',
  'Bao nhiêu sinh viên chưa nộp?',
  'Tìm đoạn nói về kiểm thử',
];

const SUBMISSION_SUGGESTIONS = [
  'Tóm tắt bài này',
  'Tìm đoạn nói về kiểm thử',
  'Bài này có đề cập đến yêu cầu phi chức năng không?',
];

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Bot text may use **bold** (LLM output); render just that, never raw HTML. */
function renderInline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part,
  );
}

function pageLabel(citation: ChatCitation): string {
  return citation.page_end !== citation.page
    ? `Trang ${citation.page}–${citation.page_end}`
    : `Trang ${citation.page}`;
}

const StatsCard: React.FC<{ stats: NonNullable<ChatPayload['stats']> }> = ({ stats }) => (
  <div className="mt-3 pt-3 border-t border-slate-200 grid grid-cols-4 gap-2 text-center">
    {[
      { label: 'Tổng SV', value: stats.total_students, tone: 'text-slate-900' },
      { label: 'Đã nộp', value: stats.submitted, tone: 'text-emerald-600' },
      { label: 'Chờ duyệt', value: stats.pending_review, tone: 'text-amber-600' },
      { label: 'Có lỗi', value: stats.errors, tone: 'text-rose-600' },
    ].map((tile) => (
      <div key={tile.label} className="bg-white p-2 rounded border border-slate-200">
        <div className="text-[10px] text-slate-400">{tile.label}</div>
        <div className={`text-base font-bold font-mono ${tile.tone}`}>{tile.value}</div>
      </div>
    ))}
  </div>
);

const SnippetCards: React.FC<{
  citations: ChatCitation[];
  onOpen: (citation: ChatCitation) => void;
}> = ({ citations, onOpen }) => (
  <div className="mt-3 pt-3 border-t border-slate-200 space-y-2">
    {citations.map((citation) => (
      <div key={citation.chunk_id} className="bg-white p-3 rounded-lg border border-slate-200 hover:border-blue-400 transition-colors">
        <div className="flex justify-between items-start gap-2 mb-1 text-xs">
          <div className="min-w-0">
            {citation.student_name && <div className="font-semibold text-slate-900 truncate">{citation.student_name}</div>}
            <div className="text-slate-500 truncate">{citation.section_path ?? citation.file_name ?? 'Đoạn trích'}</div>
          </div>
          <span className="shrink-0 font-mono bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-[10px]">
            {pageLabel(citation)}
          </span>
        </div>
        <p className="text-xs text-slate-600 italic bg-slate-50 p-2 rounded mb-2">“{citation.excerpt}”</p>
        <button
          type="button"
          onClick={() => onOpen(citation)}
          className="w-full py-1 text-xs font-semibold bg-blue-50 hover:bg-blue-100 text-blue-700 rounded flex items-center justify-center gap-1.5 transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" /> Mở và xem đúng {pageLabel(citation)} trong PDF
        </button>
      </div>
    ))}
  </div>
);

const CitationList: React.FC<{
  citations: ChatCitation[];
  onOpen: (citation: ChatCitation) => void;
}> = ({ citations, onOpen }) => (
  <div className="mt-3 pt-3 border-t border-slate-200 space-y-2">
    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
      Căn cứ đối chiếu từ tài liệu gốc:
    </div>
    {citations.map((citation, index) => (
      <button
        key={citation.chunk_id}
        type="button"
        onClick={() => onOpen(citation)}
        className="group w-full text-left p-2.5 bg-white rounded-lg border border-slate-200 hover:border-blue-400 cursor-pointer transition-all flex items-start justify-between gap-2"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-semibold text-xs text-slate-900 group-hover:text-blue-600 transition-colors truncate">
              [{index + 1}] {citation.section_path ?? citation.file_name ?? 'Đoạn trích'}
            </span>
            <span className="shrink-0 font-mono bg-blue-50 text-blue-700 px-1.5 rounded text-[10px]">{pageLabel(citation)}</span>
          </div>
          <p className="text-xs text-slate-600 line-clamp-2">{citation.excerpt}</p>
        </div>
        <span className="p-1 rounded-full bg-slate-100 group-hover:bg-blue-600 group-hover:text-white text-slate-400 shrink-0">
          <ArrowRight className="w-3.5 h-3.5" />
        </span>
      </button>
    ))}
  </div>
);

const ClarificationChips: React.FC<{
  options: ClarificationOption[];
  disabled: boolean;
  onPick: (option: ClarificationOption) => void;
}> = ({ options, disabled, onPick }) => (
  <div className="mt-3 pt-3 border-t border-slate-200 flex flex-wrap gap-1.5">
    {options.map((option) => (
      <button
        key={option.id}
        type="button"
        disabled={disabled}
        onClick={() => onPick(option)}
        className="text-left rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs text-blue-800 hover:bg-blue-50 hover:border-blue-400 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="font-semibold">{option.label}</span>
        {option.detail && <span className="block text-[10px] text-slate-500">{option.detail}</span>}
      </button>
    ))}
  </div>
);

const MessageBubble: React.FC<{
  message: UiMessage;
  clarificationDisabled: boolean;
  onCitation: (citation: ChatCitation) => void;
  onClarify: (message: UiMessage, option: ClarificationOption) => void;
}> = ({ message, clarificationDisabled, onCitation, onClarify }) => {
  const payload = message.payload ?? {};
  const citations = payload.citations ?? [];
  const isUser = message.sender === 'user';
  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
      <div className="text-[11px] text-slate-400 mb-1 px-1">
        {isUser ? 'Giảng viên' : 'DocGrading Bot'} · {timeLabel(message.createdAt)}
      </div>
      <div
        className={`max-w-[90%] rounded-xl text-xs md:text-sm p-4 leading-relaxed ${
          isUser
            ? 'bg-slate-900 text-white rounded-tr-none'
            : message.isError
              ? 'bg-rose-50 border border-rose-200 text-rose-700 rounded-tl-none'
              : 'bg-slate-50 border border-slate-200 text-slate-800 rounded-tl-none'
        }`}
      >
        <p className="whitespace-pre-line">{isUser ? message.content : renderInline(message.content)}</p>
        {payload.stats && <StatsCard stats={payload.stats} />}
        {citations.length > 0 && (payload.intent === 'SEARCH_CONTENT'
          ? <SnippetCards citations={citations} onOpen={onCitation} />
          : <CitationList citations={citations} onOpen={onCitation} />)}
        {payload.needs_clarification && payload.clarification_options && (
          <ClarificationChips
            options={payload.clarification_options}
            disabled={clarificationDisabled}
            onPick={(option) => onClarify(message, option)}
          />
        )}
      </div>
    </div>
  );
};

const ChatPane: React.FC<{
  messages: UiMessage[];
  sending: boolean;
  suggestions: string[];
  answered: Set<string>;
  onSend: (text: string) => void;
  onCitation: (citation: ChatCitation) => void;
  onClarify: (message: UiMessage, option: ClarificationOption) => void;
  placeholder: string;
}> = ({ messages, sending, suggestions, answered, onSend, onCitation, onClarify, placeholder }) => {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  const submit = (text: string) => {
    if (!text.trim() || sending) return;
    onSend(text.trim());
    setInput('');
  };

  return (
    <div className="flex-1 flex flex-col bg-white min-w-0 min-h-0">
      <div ref={scrollRef} className="flex-1 p-5 overflow-y-auto space-y-4">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            clarificationDisabled={sending || answered.has(message.id)}
            onCitation={onCitation}
            onClarify={onClarify}
          />
        ))}
        {sending && (
          <div className="text-xs text-slate-400 animate-pulse flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-blue-500" /> Đang tra cứu dữ liệu...
          </div>
        )}
      </div>

      <div className="px-4 py-2 border-t border-slate-100 bg-slate-50 flex flex-wrap gap-1.5 shrink-0">
        <span className="text-[11px] text-slate-400 font-medium py-0.5 mr-1">Gợi ý:</span>
        {suggestions.map((question) => (
          <button
            key={question}
            type="button"
            disabled={sending}
            onClick={() => submit(question)}
            className="text-xs bg-white hover:bg-slate-100 text-slate-700 px-2.5 py-1 rounded-full border border-slate-200 disabled:opacity-50"
          >
            {question}
          </button>
        ))}
      </div>

      <div className="p-3 border-t border-slate-200 bg-white shrink-0">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit(input);
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={placeholder}
            disabled={sending}
            className="flex-1 px-3 py-2 text-xs md:text-sm bg-slate-50 rounded-lg border border-slate-200 focus:outline-none focus:bg-white focus:ring-1 focus:ring-blue-600"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white rounded-lg text-xs md:text-sm font-semibold flex items-center gap-1.5 transition-colors"
          >
            {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Gửi
          </button>
        </form>
      </div>
    </div>
  );
};

let localIdSeq = 0;
function localId(prefix: string): string {
  localIdSeq += 1;
  return `${prefix}-${Date.now()}-${localIdSeq}`;
}

function scopeAfterPick(scope: Scope, message: UiMessage, option: ClarificationOption): Scope {
  switch (message.payload?.needs_clarification) {
    case 'course':
      return { courseId: option.id, submissionId: null };
    case 'assignment':
      return { ...scope, assignmentId: option.id };
    case 'submission':
      return { ...scope, submissionId: option.id };
    default:
      return scope;
  }
}

// ---------------------------------------------------------------------------
// Compact widget (Review workspace): one submission, not saved as a session
// ---------------------------------------------------------------------------

const CompactChat: React.FC<{
  submissionId?: string;
  onCitationClick?: (citation: ChatCitation) => void;
}> = ({ submissionId, onCitationClick }) => {
  const [messages, setMessages] = useState<UiMessage[]>([
    {
      id: localId('welcome'),
      sender: 'bot',
      content: 'Hỏi mình về nội dung bài nộp này — ví dụ "Tóm tắt bài này".',
      createdAt: new Date().toISOString(),
    },
  ]);
  const [sending, setSending] = useState(false);
  const [answered, setAnswered] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState<Scope>({ courseId: null, submissionId: submissionId ?? null });

  const send = async (text: string, useScope: Scope = scope) => {
    setMessages((prev) => [...prev, { id: localId('u'), sender: 'user', content: text, createdAt: new Date().toISOString() }]);
    setSending(true);
    try {
      const result = await sendChatMessage({ message: text, ...useScope });
      const { reply, session_id: _ignored, ...payload } = result;
      setMessages((prev) => [...prev, { id: localId('b'), sender: 'bot', content: reply, payload, createdAt: new Date().toISOString() }]);
    } catch (error) {
      setMessages((prev) => [...prev, { id: localId('e'), sender: 'bot', content: getErrorMessage(error), isError: true, createdAt: new Date().toISOString() }]);
    } finally {
      setSending(false);
    }
  };

  const clarify = (message: UiMessage, option: ClarificationOption) => {
    const next = scopeAfterPick(scope, message, option);
    setScope(next);
    setAnswered((prev) => new Set(prev).add(message.id));
    if (message.payload?.pending_message) void send(message.payload.pending_message, next);
  };

  return (
    <div className="flex flex-col h-[520px] border border-slate-200 rounded-xl overflow-hidden">
      <ChatPane
        messages={messages}
        sending={sending}
        suggestions={SUBMISSION_SUGGESTIONS}
        answered={answered}
        onSend={(text) => void send(text)}
        onCitation={onCitationClick ?? (() => {})}
        onClarify={clarify}
        placeholder="Hỏi về nội dung bài này..."
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Full page (/teacher/chat): saved sessions as tabs + history, split PDF view
// ---------------------------------------------------------------------------

const OPEN_TABS_KEY = 'docgrading.chat.openTabs';

function readOpenTabs(): string[] {
  try {
    const raw = window.localStorage.getItem(OPEN_TABS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    return [];
  }
}

function writeOpenTabs(ids: string[]): void {
  try {
    window.localStorage.setItem(OPEN_TABS_KEY, JSON.stringify(ids));
  } catch {
    // Tabs are a convenience; the sessions themselves are saved server-side.
  }
}

function sessionScope(session: ChatSession | undefined): Scope {
  if (!session) return { courseId: null, submissionId: null };
  return {
    courseId: session.all_courses ? 'all' : session.course_id,
    submissionId: session.submission_id,
  };
}

interface PdfFocus {
  documentVersionId: string;
  fileName: string | null;
  markers: PdfMarker[];
  selectedMarkerId?: string;
}

function focusFromCitation(citation: ChatCitation): PdfFocus | null {
  if (!citation.document_version_id) return null;
  const markers: PdfMarker[] = citation.highlights.length
    ? citation.highlights.map((highlight, index) => ({
        id: `${citation.chunk_id}-${index}`,
        label: `Trang ${highlight.page}`,
        pageNumber: highlight.page,
        bbox: highlight.bbox,
      }))
    : [{ id: `${citation.chunk_id}-page`, label: pageLabel(citation), pageNumber: citation.page }];
  return {
    documentVersionId: citation.document_version_id,
    fileName: citation.file_name,
    markers,
    selectedMarkerId: markers[0]?.id,
  };
}

const FullChat: React.FC = () => {
  const queryClient = useQueryClient();
  const [openTabIds, setOpenTabIds] = useState<string[]>(readOpenTabs);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [isPdfOpen, setIsPdfOpen] = useState(true);
  const [pdfFocus, setPdfFocus] = useState<PdfFocus | null>(null);
  const [pending, setPending] = useState<Record<string, UiMessage[]>>({});
  const [sendingSession, setSendingSession] = useState<string | null>(null);
  const [answered, setAnswered] = useState<Set<string>>(new Set());
  const [assignmentId, setAssignmentId] = useState<string | null>(null);
  const creatingFirst = useRef(false);

  const sessionsQuery = useQuery({ queryKey: ['chat-sessions'], queryFn: listChatSessions });
  const sessions = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data]);
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });

  const createSession = useMutation({
    mutationFn: createChatSession,
    onSuccess: (session) => {
      queryClient.setQueryData<ChatSession[]>(['chat-sessions'], (prev) => [session, ...(prev ?? [])]);
      setOpenTabIds((prev) => (prev.includes(session.id) ? prev : [...prev, session.id]));
      setActiveTabId(session.id);
    },
  });

  // Keep tabs pointing at sessions that still exist; ensure one session exists.
  useEffect(() => {
    if (!sessionsQuery.data) return;
    const known = new Set(sessions.map((s) => s.id));
    const valid = openTabIds.filter((id) => known.has(id));
    if (valid.length === 0 && sessions.length > 0) valid.push(sessions[0].id);
    if (valid.join() !== openTabIds.join()) setOpenTabIds(valid);
    if (!activeTabId || !known.has(activeTabId)) setActiveTabId(valid[0] ?? null);
    if (sessions.length === 0 && !creatingFirst.current) {
      creatingFirst.current = true;
      createSession.mutate({});
    }
  }, [sessionsQuery.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => writeOpenTabs(openTabIds), [openTabIds]);

  const activeSession = sessions.find((s) => s.id === activeTabId);
  const scope = sessionScope(activeSession);
  const courseUuid = scope.courseId && scope.courseId !== 'all' ? scope.courseId : null;

  const submissionsQuery = useQuery({
    queryKey: ['chat-scope-submissions', courseUuid],
    queryFn: () => listScopeSubmissions(courseUuid as string),
    enabled: Boolean(courseUuid),
  });

  const messagesQuery = useQuery({
    queryKey: ['chat-messages', activeTabId],
    queryFn: () => listChatMessages(activeTabId as string),
    enabled: Boolean(activeTabId),
  });

  const messages: UiMessage[] = useMemo(() => {
    const saved: UiMessage[] = (messagesQuery.data ?? []).map((m) => ({
      id: m.id,
      sender: m.sender,
      content: m.content,
      payload: m.payload,
      createdAt: m.created_at,
    }));
    const welcome: UiMessage = {
      id: 'welcome',
      sender: 'bot',
      content: 'Chào Thầy/Cô! Thầy/Cô có thể hỏi nhanh về tiến độ nộp bài, tra cứu đoạn trích trong báo cáo PDF hoặc yêu cầu tóm tắt một bài nộp.',
      createdAt: activeSession?.created_at ?? new Date().toISOString(),
    };
    return [welcome, ...saved, ...(activeTabId ? pending[activeTabId] ?? [] : [])];
  }, [messagesQuery.data, pending, activeTabId, activeSession?.created_at]);

  // With a submission in scope and no citation opened yet, show that PDF.
  const scopedSubmission = submissionsQuery.data?.find((s) => s.submission_id === scope.submissionId);
  const shownPdf: PdfFocus | null = pdfFocus
    ?? (scopedSubmission
      ? { documentVersionId: scopedSubmission.document_version_id, fileName: scopedSubmission.file_name, markers: [] }
      : null);

  const patchScope = async (next: Scope) => {
    if (!activeSession) return;
    queryClient.setQueryData<ChatSession[]>(['chat-sessions'], (prev) =>
      (prev ?? []).map((s) =>
        s.id === activeSession.id
          ? { ...s, course_id: next.courseId === 'all' ? null : next.courseId, all_courses: next.courseId === 'all', submission_id: next.submissionId }
          : s,
      ),
    );
    setPdfFocus(null);
    try {
      await updateChatSession(activeSession.id, { course_id: next.courseId, submission_id: next.submissionId });
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chat-sessions'] });
    }
  };

  const send = async (text: string, useScope: Scope = { ...scope, assignmentId }) => {
    const sessionId = activeTabId;
    if (!sessionId || sendingSession) return;
    const userMessage: UiMessage = { id: localId('u'), sender: 'user', content: text, createdAt: new Date().toISOString() };
    setPending((prev) => ({ ...prev, [sessionId]: [...(prev[sessionId] ?? []), userMessage] }));
    setSendingSession(sessionId);
    try {
      await sendChatMessage({ message: text, ...useScope, sessionId });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['chat-messages', sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['chat-sessions'] }),
      ]);
      setPending((prev) => ({ ...prev, [sessionId]: [] }));
    } catch (error) {
      const errorMessage: UiMessage = { id: localId('e'), sender: 'bot', content: getErrorMessage(error), isError: true, createdAt: new Date().toISOString() };
      setPending((prev) => ({ ...prev, [sessionId]: [...(prev[sessionId] ?? []), errorMessage] }));
    } finally {
      setSendingSession(null);
    }
  };

  const clarify = async (message: UiMessage, option: ClarificationOption) => {
    const next = scopeAfterPick({ ...scope, assignmentId }, message, option);
    setAnswered((prev) => new Set(prev).add(message.id));
    if (message.payload?.needs_clarification === 'assignment') {
      setAssignmentId(option.id);
    } else {
      await patchScope(next);
    }
    if (message.payload?.pending_message) await send(message.payload.pending_message, next);
  };

  const openCitation = (citation: ChatCitation) => {
    const focus = focusFromCitation(citation);
    if (!focus) return;
    setPdfFocus(focus);
    setIsPdfOpen(true);
  };

  const closeTab = (event: React.MouseEvent, tabId: string) => {
    event.stopPropagation();
    const remaining = openTabIds.filter((id) => id !== tabId);
    if (remaining.length === 0) {
      createSession.mutate({});
      setOpenTabIds([]);
      return;
    }
    setOpenTabIds(remaining);
    if (activeTabId === tabId) setActiveTabId(remaining[remaining.length - 1]);
  };

  const openSession = (sessionId: string) => {
    setOpenTabIds((prev) => (prev.includes(sessionId) ? prev : [...prev, sessionId]));
    setActiveTabId(sessionId);
    setPdfFocus(null);
  };

  const togglePin = async (session: ChatSession) => {
    await updateChatSession(session.id, { is_pinned: !session.is_pinned });
    await queryClient.invalidateQueries({ queryKey: ['chat-sessions'] });
  };

  const removeSession = async (session: ChatSession) => {
    if (!window.confirm(`Xoá phiên "${session.title}"?`)) return;
    await deleteChatSession(session.id);
    setOpenTabIds((prev) => prev.filter((id) => id !== session.id));
    await queryClient.invalidateQueries({ queryKey: ['chat-sessions'] });
  };

  const visibleHistory = sessions.filter((s) => s.title.toLowerCase().includes(historySearch.toLowerCase()));

  return (
    <div className="flex h-[calc(100vh-64px)] w-full bg-[#f8fafc] text-slate-800 overflow-hidden">
      {showHistory && (
        <aside className="w-72 bg-white border-r border-slate-200 flex flex-col shrink-0">
          <div className="p-3 border-b border-slate-200 flex items-center justify-between">
            <span className="font-semibold text-xs text-slate-700 uppercase flex items-center gap-1.5">
              <History className="w-3.5 h-3.5 text-blue-600" /> Các phiên đã lưu
            </span>
            <button type="button" onClick={() => createSession.mutate({})} className="p-1 px-2 text-blue-600 hover:bg-blue-50 rounded text-xs flex items-center gap-1 font-medium">
              <Plus className="w-3.5 h-3.5" /> Mới
            </button>
          </div>
          <div className="p-2 border-b border-slate-100">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <input
                type="text"
                value={historySearch}
                onChange={(event) => setHistorySearch(event.target.value)}
                placeholder="Tìm phiên tra cứu..."
                className="w-full pl-8 pr-2 py-1.5 bg-slate-50 border border-slate-200 rounded text-xs focus:outline-none focus:bg-white"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {visibleHistory.map((s) => (
              <div
                key={s.id}
                onClick={() => openSession(s.id)}
                className={`group p-2.5 rounded-lg text-xs cursor-pointer border transition-colors ${
                  s.id === activeTabId ? 'bg-blue-50/80 border-blue-200 font-semibold text-blue-950' : 'border-transparent hover:bg-slate-50 text-slate-600'
                }`}
              >
                <div className="flex justify-between items-start gap-1">
                  <span className="truncate flex-1">{s.title}</span>
                  <button type="button" onClick={(event) => { event.stopPropagation(); void togglePin(s); }} title={s.is_pinned ? 'Bỏ ghim' : 'Ghim'}>
                    <Pin className={`w-3 h-3 shrink-0 ${s.is_pinned ? 'text-amber-500' : 'text-slate-300 group-hover:text-slate-400'}`} />
                  </button>
                  <button type="button" onClick={(event) => { event.stopPropagation(); void removeSession(s); }} title="Xoá phiên" className="opacity-0 group-hover:opacity-100">
                    <Trash2 className="w-3 h-3 text-slate-400 hover:text-rose-600" />
                  </button>
                </div>
                <div className="text-[10px] text-slate-400 mt-1">{new Date(s.updated_at).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </aside>
      )}

      <div className="flex-1 flex flex-col min-w-0 bg-white">
        {/* Tabs */}
        <div className="h-9 bg-slate-100 border-b border-slate-200 px-3 flex items-end gap-1 overflow-x-auto shrink-0 select-none">
          <button
            type="button"
            onClick={() => setShowHistory((open) => !open)}
            className={`h-7 mb-0.5 mr-1 px-2 rounded text-xs flex items-center gap-1.5 font-medium ${showHistory ? 'bg-indigo-100 text-indigo-700' : 'text-slate-600 hover:bg-slate-200'}`}
            title="Lịch sử tra cứu"
          >
            <History className="w-3.5 h-3.5" /> Lịch sử
            <span className="text-[10px] font-mono bg-white px-1.5 rounded border border-slate-200">{sessions.length}</span>
          </button>
          {openTabIds.map((tabId) => {
            const s = sessions.find((item) => item.id === tabId);
            if (!s) return null;
            const isActive = tabId === activeTabId;
            return (
              <div
                key={tabId}
                onClick={() => openSession(tabId)}
                className={`h-8 px-3 max-w-[210px] rounded-t-md flex items-center gap-2 text-xs cursor-pointer border-t border-x transition-colors ${
                  isActive ? 'bg-white border-slate-200 text-slate-900 font-semibold' : 'bg-slate-200/70 text-slate-500 hover:bg-slate-200 border-transparent'
                }`}
              >
                <span className="truncate flex-1">{s.title}</span>
                <button type="button" onClick={(event) => closeTab(event, tabId)} className="w-3.5 h-3.5 rounded hover:bg-slate-300 flex items-center justify-center text-slate-400" aria-label="Đóng tab">
                  <X className="w-2.5 h-2.5" />
                </button>
              </div>
            );
          })}
          <button type="button" onClick={() => createSession.mutate({})} className="h-6 w-6 mb-0.5 rounded text-slate-500 hover:bg-slate-200 flex items-center justify-center" title="Thêm tab mới">
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Scope */}
        <div className="p-3 border-b border-slate-200 bg-slate-50/50 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <label className="font-semibold text-slate-700" htmlFor="chat-course">Lớp:</label>
            <select
              id="chat-course"
              value={scope.courseId ?? ''}
              disabled={!activeSession}
              onChange={(event) => void patchScope({ courseId: event.target.value || null, submissionId: null })}
              className="bg-white border border-slate-300 rounded px-2.5 py-1 text-xs font-medium text-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">-- Chọn lớp --</option>
              <option value="all">Tất cả lớp</option>
              {(coursesQuery.data ?? []).map((course) => (
                <option key={course.id} value={course.id}>{course.code} - {course.name}</option>
              ))}
            </select>

            <span className="text-slate-300">|</span>

            <label className="font-semibold text-slate-700" htmlFor="chat-scope">Phạm vi:</label>
            <select
              id="chat-scope"
              value={scope.submissionId ?? ''}
              disabled={!courseUuid}
              onChange={(event) => void patchScope({ courseId: scope.courseId, submissionId: event.target.value || null })}
              className="bg-blue-50 border border-blue-200 text-blue-800 rounded px-2.5 py-1 text-xs font-semibold focus:outline-none disabled:opacity-50 max-w-[360px]"
            >
              <option value="">Toàn bộ lớp (Số liệu tổng hợp)</option>
              {(submissionsQuery.data ?? []).map((s) => (
                <option key={s.submission_id} value={s.submission_id}>{s.student_name} — {s.assignment_title}</option>
              ))}
            </select>
          </div>

          <button type="button" onClick={() => setIsPdfOpen((open) => !open)} className="flex items-center gap-1.5 text-blue-700 hover:text-blue-900 font-medium">
            <Maximize2 className="w-3.5 h-3.5" />
            <span>{isPdfOpen ? 'Thu gọn PDF' : 'Mở xem PDF song song'}</span>
          </button>
        </div>

        {/* Split view */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {isPdfOpen && (
            <div className="w-1/2 border-r border-slate-300 bg-slate-100 flex flex-col min-w-0">
              <div className="h-10 bg-white border-b border-slate-200 px-4 flex items-center gap-2 text-xs shrink-0">
                <FileText className="w-4 h-4 text-rose-600" />
                <span className="font-semibold text-slate-800 truncate">
                  {shownPdf?.fileName ?? 'Chưa mở tài liệu nào'}
                </span>
              </div>
              <div className="flex-1 overflow-auto p-3">
                {shownPdf ? (
                  <PdfMarkerViewer
                    key={shownPdf.documentVersionId}
                    documentVersionId={shownPdf.documentVersionId}
                    markers={shownPdf.markers}
                    selectedMarkerId={shownPdf.selectedMarkerId}
                    onSelectMarker={(markerId) => setPdfFocus((focus) => (focus ? { ...focus, selectedMarkerId: markerId } : focus))}
                    ariaLabel="Tài liệu được trích dẫn"
                  />
                ) : (
                  <p className="p-8 text-center text-sm text-slate-500">
                    Chọn một bài ở "Phạm vi" hoặc bấm vào một đoạn trích dẫn để xem PDF tại đúng trang.
                  </p>
                )}
              </div>
            </div>
          )}

          <ChatPane
            messages={messages}
            sending={sendingSession === activeTabId}
            suggestions={scope.submissionId ? SUBMISSION_SUGGESTIONS : CLASS_SUGGESTIONS}
            answered={answered}
            onSend={(text) => void send(text)}
            onCitation={openCitation}
            onClarify={(message, option) => void clarify(message, option)}
            placeholder="Hỏi về tình hình chấm bài, tra cứu đoạn văn trong PDF, tóm tắt bài nộp..."
          />
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------

interface ChatViewProps {
  /** Scope content questions to one submission, e.g. from the Review workspace. */
  submissionId?: string;
  /** Embedded widget layout: just the conversation, not saved as a session. */
  compact?: boolean;
  /** Citation click handler for the compact widget (full page opens the PDF). */
  onCitationClick?: (citation: ChatCitation) => void;
}

export const ChatView: React.FC<ChatViewProps> = ({ submissionId, compact = false, onCitationClick }) =>
  compact ? <CompactChat submissionId={submissionId} onCitationClick={onCitationClick} /> : <FullChat />;

export default ChatView;
