import { ApiError, csrfFetch, notifyAuthExpired } from '../api/client';

/**
 * Client for the basic (rule-based, no-RAG) teacher chatbot endpoint.
 *
 * Hand-written rather than routed through the generated `api` client because
 * `POST /api/v1/chat` isn't part of the openapi-typescript codegen output yet
 * (that requires a running backend to regenerate `schema.ts`). It still
 * reuses the same cookie + CSRF-header auth as every other mutating call
 * (see `csrfFetch` in `api/client.ts`), so it works with the existing
 * session cookie without any extra setup.
 */

export interface ChatAssignmentOption {
  id: string;
  title: string;
}

export interface ChatResponse {
  reply: string;
  intent: string;
  needs_assignment: boolean;
  assignment_options: ChatAssignmentOption[] | null;
}

export async function sendChatMessage(
  message: string,
  courseId: string | null,
  assignmentId: string | null,
): Promise<ChatResponse> {
  const response = await csrfFetch('/api/v1/chat', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      course_id: courseId,
      assignment_id: assignmentId,
    }),
  });
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
  return data as ChatResponse;
}