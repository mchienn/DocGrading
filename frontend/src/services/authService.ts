import { api, apiData, apiVoid } from '../api/client';
import type { LoginParams, UserSession } from '../types/auth';

export const authService = {
  login(params: LoginParams): Promise<UserSession> {
    return apiData(api.POST('/api/v1/auth/login', { body: params }));
  },

  loadSession(): Promise<UserSession> {
    return apiData(api.GET('/api/v1/auth/me'));
  },

  logout(): Promise<void> {
    return apiVoid(api.POST('/api/v1/auth/logout'));
  },
};
