import type { components } from '../api/schema';

export type UserSession = components['schemas']['UserResponse'];

export interface LoginParams {
  email: string;
  password: string;
}
