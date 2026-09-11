import React from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

interface AuthStatusMessageProps {
  type?: 'error' | 'success' | 'info';
  message: string | null;
  onClose?: () => void;
}

export const AuthStatusMessage: React.FC<AuthStatusMessageProps> = ({
  type = 'error',
  message,
  onClose,
}) => {
  if (!message) return null;

  const isError = type === 'error';
  const isSuccess = type === 'success';

  return (
    <div
      role="alert"
      className={`mb-5 p-3.5 rounded-xl text-xs sm:text-[13px] leading-relaxed flex items-start gap-2.5 transition-all duration-200 border ${
        isError
          ? 'bg-[#FDF3F2] border-[#F8D2CF] text-[#C9362B]'
          : isSuccess
          ? 'bg-[#F0F9F5] border-[#CEEADB] text-[#178557]'
          : 'bg-[#EFF5FC] border-[#D4E4F5] text-[#193B64]'
      }`}
    >
      <div className="flex-shrink-0 mt-0.5">
        {isError && <AlertCircle className="w-4 h-4" strokeWidth={1.8} />}
        {isSuccess && <CheckCircle2 className="w-4 h-4" strokeWidth={1.8} />}
        {!isError && !isSuccess && <Info className="w-4 h-4" strokeWidth={1.8} />}
      </div>
      <div className="flex-1 font-medium">{message}</div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="flex-shrink-0 opacity-70 hover:opacity-100 transition-opacity p-0.5"
          aria-label="Đóng thông báo"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
};
