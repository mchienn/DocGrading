import React from 'react';
import { Loader2 } from 'lucide-react';

export interface SubmitButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  isLoading?: boolean;
  loadingText?: string;
  variant?: 'primary' | 'secondary' | 'outline';
}

export const SubmitButton: React.FC<SubmitButtonProps> = ({
  children,
  isLoading = false,
  loadingText,
  disabled,
  variant = 'primary',
  className = '',
  type = 'submit',
  ...props
}) => {
  const isPrimary = variant === 'primary';
  const isSecondary = variant === 'secondary';
  const isOutline = variant === 'outline';

  return (
    <button
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      className={`w-full h-12 px-5 rounded-xl font-medium text-[14px] flex items-center justify-center gap-2 transition-all duration-150 select-none outline-none focus:ring-3 focus:ring-[#2C6EBA]/30 ${
        isPrimary
          ? 'bg-[#193B64] hover:bg-[#102A49] active:bg-[#0c1f36] text-white shadow-[0_1px_2px_rgba(0,0,0,0.06)] disabled:bg-[#193B64]/50 disabled:cursor-not-allowed'
          : isSecondary
          ? 'bg-[#F0F3F7] hover:bg-[#E4E9F0] text-[#172033] disabled:opacity-50 disabled:cursor-not-allowed'
          : isOutline
          ? 'border border-[#D9E0E8] hover:bg-[#F9FAFC] text-[#172033] disabled:opacity-50 disabled:cursor-not-allowed'
          : ''
      } ${className}`}
      {...props}
    >
      {isLoading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>{loadingText || 'Đang xử lý...'}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
};
