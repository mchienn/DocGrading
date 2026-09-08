import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { FormField } from '../components/auth/FormField';
import { PasswordField } from '../components/auth/PasswordField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { SocialLoginButton } from '../components/auth/SocialLoginButton';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { Check, Mail, Lock } from 'lucide-react';

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
  onNavigate: (screen: string) => void;
  onLoginSuccess?: (user: unknown) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onLoginSuccess }) => {
  const { success, error: toastError } = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
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
        onLoginSuccess?.(response.data);
      } else {
        setServerError(response.message);
        if (response.errorCode === 'UNVERIFIED_ACCOUNT') {
          authService.setPendingEmail(data.email);
        }
      }
    } catch {
      setServerError('Kết nối bị gián đoạn. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleGoogleLogin = async () => {
    setServerError(null);
    setIsGoogleLoading(true);
    try {
      const response = await authService.loginWithGoogle();
      if (response.success && response.data) {
        success('Đăng nhập bằng Google thành công.');
        onLoginSuccess?.(response.data);
      } else {
        setServerError(response.message);
      }
    } catch {
      toastError('Không thể kết nối đến máy chủ xác thực Google.');
    } finally {
      setIsGoogleLoading(false);
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

      {serverError === 'Tài khoản này chưa được xác minh.' && (
        <div className="mb-4 -mt-2 p-2.5 rounded-lg bg-[#F5F7FA] border border-[#D9E0E8] flex items-center justify-between text-xs">
          <span className="text-[#667085]">Bạn muốn xác minh email ngay?</span>
          <button
            type="button"
            onClick={() => onNavigate('verify-email')}
            className="font-semibold text-[#193B64] hover:underline"
          >
            Nhập mã OTP →
          </button>
        </div>
      )}

      {/* Social Login Button */}
      <div className="mb-5">
        <SocialLoginButton
          onClick={handleGoogleLogin}
          isLoading={isGoogleLoading}
          text="Tiếp tục với Google"
        />
      </div>

      {/* Divider with Left-Aligned Text */}
      <div className="relative my-5">
        <div className="absolute inset-0 flex items-center" aria-hidden="true">
          <div className="w-full border-t border-[#D9E0E8]" />
        </div>
        <div className="relative flex justify-start">
          <span className="bg-white pr-3 text-[12px] text-[#667085] uppercase tracking-wider font-medium select-none whitespace-nowrap">
            Hoặc với email
          </span>
        </div>
      </div>

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

        {/* Remember me & Forgot password */}
        <div className="flex items-center justify-between pt-0.5 pb-1">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-[#D9E0E8] text-[#193B64] focus:ring-[#2C6EBA]/30 accent-[#193B64]"
              {...register('rememberMe')}
            />
            <span className="text-[13px] text-[#172033] font-normal">Duy trì đăng nhập</span>
          </label>

          <button
            type="button"
            onClick={() => onNavigate('forgot-password')}
            className="text-[13px] font-medium text-[#2C6EBA] hover:text-[#193B64] hover:underline focus:outline-none transition-colors"
          >
            Quên mật khẩu?
          </button>
        </div>

        <SubmitButton isLoading={isSubmitting} loadingText="Đang xác thực...">
          Đăng nhập
        </SubmitButton>
      </form>

      {/* Footer link to Register */}
      <div className="mt-6 pt-5 border-t border-[#D9E0E8] text-center text-[13px] text-[#667085]">
        <span>Chưa kích hoạt tài khoản? </span>
        <button
          type="button"
          onClick={() => onNavigate('register')}
          className="font-semibold text-[#193B64] hover:text-[#102A49] hover:underline transition-colors focus:outline-none"
        >
          Kích hoạt bằng mã mời / ủy quyền
        </button>
      </div>
    </AuthFormCard>
  );
};
