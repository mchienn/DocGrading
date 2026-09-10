import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Mail, Lock } from 'lucide-react';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { FormField } from '../components/auth/FormField';
import { PasswordField } from '../components/auth/PasswordField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { getErrorMessage } from '../api/client';
import type { UserSession } from '../types/auth';

const loginSchema = z.object({
  email: z.string().min(1, 'Vui lòng nhập địa chỉ email').email('Định dạng email không hợp lệ'),
  password: z.string().min(1, 'Vui lòng nhập mật khẩu'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

interface LoginPageProps {
  onLoginSuccess: (user: UserSession) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const { success } = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = async (data: LoginFormValues) => {
    setServerError(null);
    setIsSubmitting(true);
    try {
      const user = await authService.login(data);
      success('Đăng nhập thành công. Đang tải không gian làm việc...');
      onLoginSuccess(user);
    } catch (error) {
      setServerError(getErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthFormCard>
      <div className="mb-6">
        <h2 className="text-[24px] sm:text-[26px] font-semibold text-[#172033] tracking-tight">
          Đăng nhập hệ thống DocGrading
        </h2>
        <p className="text-[14px] text-[#667085] mt-1.5 leading-relaxed">
          Dùng tài khoản được quản trị viên cấp.
        </p>
      </div>

      <AuthStatusMessage type="error" message={serverError} onClose={() => setServerError(null)} />

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <FormField
          id="login-email"
          label="Email"
          type="email"
          autoComplete="email"
          placeholder="name@example.edu.vn"
          leftIcon={<Mail className="w-4 h-4" />}
          error={errors.email?.message}
          isRequired
          {...register('email')}
        />
        <PasswordField
          id="login-password"
          label="Mật khẩu"
          autoComplete="current-password"
          placeholder="••••••••"
          leftIcon={<Lock className="w-4 h-4" />}
          error={errors.password?.message}
          isRequired
          {...register('password')}
        />
        <SubmitButton isLoading={isSubmitting} loadingText="Đang xác thực...">
          Đăng nhập
        </SubmitButton>
      </form>
    </AuthFormCard>
  );
};
