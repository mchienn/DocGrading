import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot, Loader2, Send, User as UserIcon } from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import { sendChatMessage, type ChatAssignmentOption } from '../../services/chatService';

interface ChatMessage {
  id: string;
  role: 'user' | 'bot';
  text: string;
  isError?: boolean;
}

const EXAMPLE_QUESTIONS = [
  'Tình hình báo cáo lớp thế nào?',
  'Còn bao nhiêu bài chưa duyệt?',
  'Những bài nào đang lỗi?',
  'Bao nhiêu sinh viên chưa nộp?',
  'Hôm nay có yêu cầu xem lại nào mới không?',
];

let messageIdSeq = 0;
function nextId(): string {
  messageIdSeq += 1;
  return `m${messageIdSeq}`;
}

export const ChatView: React.FC = () => {
  const [courseId, setCourseId] = useState('');
  const [assignmentId, setAssignmentId] = useState('');
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: nextId(),
      role: 'bot',
      text: 'Chào bạn! Chọn một lớp ở trên rồi hỏi mình về tình hình chấm bài nhé.',
    },
  ]);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });

  const assignmentsQuery = useQuery({
    queryKey: ['assignments', courseId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/assignments', {
      params: { path: { course_id: courseId } },
    })),
    enabled: Boolean(courseId),
  });

  useEffect(() => {
    if (!coursesQuery.data || courseId) return;
    if (coursesQuery.data.length > 0) setCourseId(coursesQuery.data[0].id);
  }, [coursesQuery.data, courseId]);

  useEffect(() => {
    setAssignmentId('');
  }, [courseId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const appendAssignmentOptions = (options: ChatAssignmentOption[]) => {
    const listText = options.map((option) => `• ${option.title}`).join('\n');
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: 'bot', text: `Các bài tập trong lớp:\n${listText}` },
    ]);
  };

  const submit = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setMessages((prev) => [...prev, { id: nextId(), role: 'user', text: trimmed }]);
    setInput('');
    setSending(true);
    try {
      const result = await sendChatMessage(trimmed, courseId || null, assignmentId || null);
      setMessages((prev) => [...prev, { id: nextId(), role: 'bot', text: result.reply }]);
      if (result.needs_assignment && result.assignment_options?.length) {
        appendAssignmentOptions(result.assignment_options);
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: 'bot', text: getErrorMessage(error), isError: true },
      ]);
    } finally {
      setSending(false);
    }
  };

  const onSubmitForm = (event: React.FormEvent) => {
    event.preventDefault();
    void submit(input);
  };

  return (
    <div className="p-6 sm:p-8 max-w-4xl mx-auto flex flex-col h-[calc(100vh-64px)]">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <label className="block text-[11px] font-semibold text-[#596579] mb-1" htmlFor="chat-course">
            Lớp
          </label>
          <select
            id="chat-course"
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
            className="border border-[#DDE2E8] rounded-lg px-3 py-2 text-sm bg-white min-w-[220px]"
          >
            <option value="">-- Chọn lớp --</option>
            {(coursesQuery.data ?? []).map((course) => (
              <option key={course.id} value={course.id}>
                {course.code} - {course.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-[#596579] mb-1" htmlFor="chat-assignment">
            Bài tập
          </label>
          <select
            id="chat-assignment"
            value={assignmentId}
            onChange={(event) => setAssignmentId(event.target.value)}
            disabled={!courseId || assignmentsQuery.isLoading}
            className="border border-[#DDE2E8] rounded-lg px-3 py-2 text-sm bg-white min-w-[220px] disabled:bg-[#F5F6F8]"
          >
            <option value="">Tất cả bài tập</option>
            {(assignmentsQuery.data ?? []).map((assignment) => (
              <option key={assignment.id} value={assignment.id}>
                {assignment.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto space-y-3 border border-[#DDE2E8] rounded-xl bg-[#F8FAFC] p-4">
        {messages.map((message) => (
          <div key={message.id} className={`flex items-start gap-2 ${message.role === 'user' ? 'justify-end' : ''}`}>
            {message.role === 'bot' && <Bot size={18} className="mt-2 text-[#2563EB]" />}
            <div className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-3 text-sm ${message.role === 'user' ? 'bg-[#2563EB] text-white' : message.isError ? 'bg-[#FEF2F2] text-[#B91C1C]' : 'bg-white text-[#263244] border border-[#E5E7EB]'}`}>
              {message.text}
            </div>
            {message.role === 'user' && <UserIcon size={18} className="mt-2 text-[#596579]" />}
          </div>
        ))}
        {sending && <div className="flex items-center gap-2 text-sm text-[#596579]"><Loader2 size={16} className="animate-spin" /> Đang xử lý...</div>}
      </div>

      <div className="flex flex-wrap gap-2 py-3">
        {EXAMPLE_QUESTIONS.map((question) => (
          <button key={question} type="button" onClick={() => void submit(question)} disabled={sending} className="rounded-full border border-[#DDE2E8] bg-white px-3 py-1.5 text-xs text-[#596579] hover:border-[#2563EB] hover:text-[#2563EB] disabled:opacity-50">
            {question}
          </button>
        ))}
      </div>

      <form onSubmit={onSubmitForm} className="flex items-center gap-2">
        <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Hỏi về tình hình chấm bài..." disabled={sending} className="min-w-0 flex-1 rounded-lg border border-[#DDE2E8] px-4 py-3 text-sm outline-none focus:border-[#2563EB]" />
        <button type="submit" disabled={sending || !input.trim()} aria-label="Gửi câu hỏi" className="rounded-lg bg-[#2563EB] p-3 text-white hover:bg-[#1D4ED8] disabled:opacity-50">
          <Send size={18} />
        </button>
      </form>
    </div>
  );
};

