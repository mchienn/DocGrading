import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { PasswordField } from '../components/auth/PasswordField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { PasswordRequirements } from '../components/auth/PasswordRequirements';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { Lock, CheckCircle2, ArrowRight } from 'lucide-react';

const resetPasswordSchema = z
  .object({
    newPassword: z
      .string()
      .min(8, 'Mật khẩu phải có tối thiểu 8 ký tự')
      .regex(/[a-z]/, 'Cần ít nhất một chữ cái viết thường')
      .regex(/[A-Z]/, 'Cần ít nhất một chữ cái viết hoa')
      .regex(/\d/, 'Cần ít nhất một chữ số')
      .regex(/[^A-Za-z0-9]/, 'Cần ít nhất một ký tự đặc biệt'),
    confirmPassword: z.string().min(1, 'Vui lòng xác nhận mật khẩu mới'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: 'Mật khẩu xác nhận không khớp',
    path: ['confirmPassword'],
  });

type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

interface ResetPasswordPageProps {
  onNavigate: (screen: string) => void;
}

export const ResetPasswordPage: React.FC<ResetPasswordPageProps> = ({ onNavigate }) => {
  const { success } = useToast();
  const [isSuccess, setIsSuccess] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: {
      newPassword: '',
      confirmPassword: '',
    },
    mode: 'onTouched',
  });

  const currentPassword = watch('newPassword');

  const onSubmit = async (data: ResetPasswordFormValues) => {
    setServerError(null);
    setIsSubmitting(true);

    try {
      const response = await authService.resetPassword({
        email: authService.getPendingEmail(),
        newPassword: data.newPassword,
        confirmPassword: data.confirmPassword,
      });

      if (response.success) {
        setIsSuccess(true);
        success('Cập nhật mật khẩu thành công!');
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
    <AuthFormCard
      backTo={{
        label: 'Quay lại đăng nhập',
        onClick: () => onNavigate('login'),
      }}
    >
      {!isSuccess ? (
        <>
          <div className="mb-6">
            <div className="w-10 h-10 rounded-xl bg-[#193B64]/10 border border-[#193B64]/20 flex items-center justify-center text-[#193B64] mb-3.5">
              <Lock className="w-5 h-5" />
            </div>

            <h2 className="text-[24px] sm:text-[26px] font-semibold text-[#172033] tracking-tight">
              Đặt lại mật khẩu mới
            </h2>
            <p className="text-[14px] text-[#667085] mt-1.5 leading-relaxed">
              Thiết lập mật khẩu mạnh mới cho tài khoản để bảo vệ quyền truy cập dữ liệu.
            </p>
          </div>

          <AuthStatusMessage
            type="error"
            message={serverError}
            onClose={() => setServerError(null)}
          />

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            <PasswordField
              id="reset-new-password"
              label="Mật khẩu mới"
              autoComplete="new-password"
              placeholder="••••••••"
              leftIcon={<Lock className="w-4 h-4" />}
              error={errors.newPassword?.message}
              isRequired
              {...register('newPassword')}
            />

            <PasswordRequirements password={currentPassword || ''} className="my-1.5" />

            <PasswordField
              id="reset-confirm-password"
              label="Xác nhận mật khẩu mới"
              autoComplete="new-password"
              placeholder="••••••••"
              leftIcon={<Lock className="w-4 h-4" />}
              error={errors.confirmPassword?.message}
              isRequired
              {...register('confirmPassword')}
            />

            <div className="pt-2">
              <SubmitButton isLoading={isSubmitting} loadingText="Đang cập nhật...">
                Cập nhật mật khẩu
              </SubmitButton>
            </div>
          </form>
        </>
      ) : (
        /* SUCCESS STATE */
        <div className="text-left animate-in fade-in duration-200">
          <div className="w-12 h-12 rounded-xl bg-[#F0F9F5] border border-[#CEEADB] flex items-center justify-center text-[#178557] mb-5">
            <CheckCircle2 className="w-6 h-6" strokeWidth={2} />
          </div>

          <h2 className="text-[22px] font-semibold text-[#172033] tracking-tight">
            Mật khẩu đã được cập nhật!
          </h2>

          <p className="text-[14px] text-[#667085] mt-2 leading-relaxed">
            Mật khẩu cho tài khoản của bạn đã được thay đổi thành công. Tất cả các phiên đăng nhập cũ trên các thiết bị khác đã được hủy để đảm bảo an toàn.
          </p>

          <div className="mt-6">
            <button
              type="button"
              onClick={() => onNavigate('login')}
              className="w-full h-12 rounded-xl bg-[#193B64] hover:bg-[#102A49] text-white text-[14px] font-medium flex items-center justify-center gap-2 transition-colors shadow-sm"
            >
              <span>Đăng nhập với mật khẩu mới</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Footer Support */}
      <div className="mt-6 pt-5 border-t border-[#D9E0E8] text-center text-[13px] text-[#667085]">
        <span>Bạn gặp sự cố tài khoản? </span>
        <a
          href="#security"
          onClick={(e) => e.preventDefault()}
          className="font-semibold text-[#193B64] hover:underline"
        >
          Trung tâm An ninh RPA
        </a>
      </div>
    </AuthFormCard>
  );
};
