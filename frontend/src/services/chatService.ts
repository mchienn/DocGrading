import { ApiError, csrfFetch, notifyAuthExpired } from '../api/client';

/**
 * Client for the teacher chatbot endpoints (rule-based intents + RAG over
 * submission content + saved chat sessions).
 *
 * Hand-written rather than routed through the generated `api` client because
 * the `/api/v1/chat*` routes aren't part of the openapi-typescript codegen
 * output yet (that requires a running backend to regenerate `schema.ts`). It
 * still reuses the same cookie + CSRF-header auth as every other call.
 */

export type ClarificationKind = 'course' | 'assignment' | 'submission';

export interface ClarificationOption {
  id: string;
  label: string;
  detail: string | null;
}

export interface ChatHighlight {
  page: number;
  bbox: { x0: number; top: number; x1: number; bottom: number };
}

/** A passage of a student document backing an answer (RAG). */
export interface ChatCitation {
  chunk_id: string;
  page: number;
  page_end: number;
  section_path: string | null;
  excerpt: string;
  submission_id: string | null;
  student_name: string | null;
  document_version_id: string | null;
  file_name: string | null;
  highlights: ChatHighlight[];
}

export interface ChatStats {
  total_students: number;
  submitted: number;
  reviewed: number;
  pending_review: number;
  errors: number;
}

/** A submission the UI should open: set it as scope and show its PDF. */
export interface OpenDocument {
  submission_id: string;
  document_version_id: string;
  label: string;
  file_name: string;
}

export interface ChatResponse {
  reply: string;
  intent: string;
  needs_clarification: ClarificationKind | null;
  clarification_options: ClarificationOption[] | null;
  pending_message: string | null;
  stats: ChatStats | null;
  citations: ChatCitation[] | null;
  open_document: OpenDocument | null;
  session_id: string | null;
}

/** Structured part of a saved bot turn (everything but the reply text). */
export type ChatPayload = Partial<Omit<ChatResponse, 'reply' | 'session_id'>>;

export interface ChatSession {
  id: string;
  title: string;
  course_id: string | null;
  all_courses: boolean;
  submission_id: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChatSavedMessage {
  id: string;
  sender: 'user' | 'bot';
  content: string;
  payload: ChatPayload;
  created_at: string;
}

export interface ChatScopeSubmission {
  submission_id: string;
  document_version_id: string;
  student_name: string;
  student_email: string;
  assignment_title: string;
  file_name: string;
  submitted_at: string;
}

/** Course scope as the API expects it: a course id, "all", or nothing. */
export type CourseScope = string | 'all' | null;

async function chatRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await csrfFetch(`/api/v1/chat${path}`, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (response.status === 204) return undefined as T;
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = undefined;
  }
  if (!response.ok) {
    if (response.status === 401) {
      notifyAuthExpired();
    }
    const detail = (data as { detail?: unknown } | undefined)?.detail;
    const errorMessage = typeof detail === 'string' ? detail : `Request failed (${response.status})`;
    throw new ApiError(errorMessage, response.status, data);
  }
  return data as T;
}

export function sendChatMessage(input: {
  message: string;
  courseId: CourseScope;
  assignmentId?: string | null;
  submissionId?: string | null;
  sessionId?: string | null;
}): Promise<ChatResponse> {
  return chatRequest<ChatResponse>('', {
    method: 'POST',
    body: JSON.stringify({
      message: input.message,
      course_id: input.courseId,
      assignment_id: input.assignmentId ?? null,
      submission_id: input.submissionId ?? null,
      session_id: input.sessionId ?? null,
    }),
  });
}

export function listChatSessions(): Promise<ChatSession[]> {
  return chatRequest<ChatSession[]>('/sessions');
}

export function createChatSession(input: {
  title?: string;
  courseId?: CourseScope;
  submissionId?: string | null;
}): Promise<ChatSession> {
  return chatRequest<ChatSession>('/sessions', {
    method: 'POST',
    body: JSON.stringify({
      title: input.title ?? null,
      course_id: input.courseId ?? null,
      submission_id: input.submissionId ?? null,
    }),
  });
}

export function updateChatSession(
  sessionId: string,
  changes: {
    title?: string;
    is_pinned?: boolean;
    course_id?: CourseScope;
    submission_id?: string | null;
  },
): Promise<ChatSession> {
  return chatRequest<ChatSession>(`/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  });
}

export function deleteChatSession(sessionId: string): Promise<void> {
  return chatRequest<void>(`/sessions/${sessionId}`, { method: 'DELETE' });
}

export function listChatMessages(sessionId: string): Promise<ChatSavedMessage[]> {
  return chatRequest<ChatSavedMessage[]>(`/sessions/${sessionId}/messages`);
}

export function listScopeSubmissions(courseId: string): Promise<ChatScopeSubmission[]> {
  return chatRequest<ChatScopeSubmission[]>(`/courses/${courseId}/submissions`);
}
