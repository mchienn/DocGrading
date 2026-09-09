import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { FormField } from '../components/auth/FormField';
import { PasswordField } from '../components/auth/PasswordField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { UserSession } from '../types/auth';
import { Mail, Lock } from 'lucide-react';

const loginSchema = z.object({
  email: z
    .string()
    .min(1, 'Vui lòng nhập địa chỉ email')
    .email('Định dạng email không hợp lệ'),
  password: z
    .string()
    .min(1, 'Vui lòng nhập mật khẩu')
    .min(6, 'Mật khẩu phải chứa ít nhất 6 ký tự'),
  rememberMe: z.boolean(),
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
    defaultValues: {
      email: '',
      password: '',
      rememberMe: true,
    },
  });

  const onSubmit = async (data: LoginFormValues) => {
    setServerError(null);
    setIsSubmitting(true);
    try {
      const response = await authService.login(data);
      if (response.success && response.data) {
        success('Đăng nhập thành công. Đang tải không gian làm việc...');
        onLoginSuccess(response.data);
      } else {
        setServerError(response.message);
      }
    } catch {
      setServerError('Kết nối bị gián đoạn. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };


  return (
    <AuthFormCard>
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-[24px] sm:text-[26px] font-semibold text-[#172033] tracking-tight">
          Đăng nhập hệ thống DocGrading
        </h2>
        <p className="text-[14px] text-[#667085] mt-1.5 leading-relaxed">
          Đăng nhập bằng tài khoản được cấp phát (Giảng viên, Sinh viên hoặc Quản trị viên).
        </p>
      </div>

      {/* Server error banner */}
      <AuthStatusMessage
        type="error"
        message={serverError}
        onClose={() => setServerError(null)}
      />


      {/* Form */}
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <FormField
          id="login-email"
          label="Email doanh nghiệp hoặc cá nhân"
          type="email"
          autoComplete="email"
          placeholder="name@company.vn"
          leftIcon={<Mail className="w-4 h-4" />}
          error={errors.email?.message}
          isRequired
          {...register('email')}
        />

        <div>
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
        </div>

        {/* Remember session */}
        <label className="flex items-center gap-2 cursor-pointer select-none w-fit">
          <input
            type="checkbox"
            className="w-4 h-4 rounded border-[#D9E0E8] text-[#193B64] focus:ring-[#2C6EBA]/30 accent-[#193B64]"
            {...register('rememberMe')}
          />
          <span className="text-[13px] text-[#172033] font-normal">Duy trì đăng nhập</span>
        </label>

        <SubmitButton isLoading={isSubmitting} loadingText="Đang xác thực...">
          Đăng nhập
        </SubmitButton>
      </form>

    </AuthFormCard>
  );
};
