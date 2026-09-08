import React, { useRef, useEffect } from 'react';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  hasError?: boolean;
  disabled?: boolean;
  onComplete?: (code: string) => void;
}

export const OtpInput: React.FC<OtpInputProps> = ({
  value,
  onChange,
  length = 6,
  hasError = false,
  disabled = false,
  onComplete,
}) => {
  const inputsRef = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    // Focus first input on mount if empty
    if (!disabled && value.length === 0) {
      inputsRef.current[0]?.focus();
    }
  }, [disabled, value.length]);

  const digits = value.split('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>, index: number) => {
    const rawVal = e.target.value;
    // Allow only single numeric digit
    const digit = rawVal.replace(/\D/g, '').slice(-1);

    const newDigits = [...digits];
    // Pad array to target length if needed
    while (newDigits.length < length) {
      newDigits.push('');
    }
    newDigits[index] = digit;
    const nextVal = newDigits.join('').slice(0, length);
    onChange(nextVal);

    if (digit && index < length - 1) {
      inputsRef.current[index + 1]?.focus();
    }

    if (nextVal.length === length && !nextVal.includes('')) {
      onComplete?.(nextVal);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, index: number) => {
    if (e.key === 'Backspace') {
      if (!digits[index] && index > 0) {
        // Move to previous
        inputsRef.current[index - 1]?.focus();
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      inputsRef.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < length - 1) {
      inputsRef.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData('text').trim();
    const cleanNumbers = pastedData.replace(/\D/g, '').slice(0, length);
    if (cleanNumbers) {
      onChange(cleanNumbers);
      const nextFocusIndex = Math.min(cleanNumbers.length, length - 1);
      inputsRef.current[nextFocusIndex]?.focus();

      if (cleanNumbers.length === length) {
        onComplete?.(cleanNumbers);
      }
    }
  };

  return (
    <div className="flex items-center justify-between gap-2 sm:gap-2.5">
      {Array.from({ length }).map((_, index) => {
        const char = digits[index] || '';
        return (
          <input
            key={index}
            ref={(el) => {
              inputsRef.current[index] = el;
            }}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d*"
            maxLength={1}
            disabled={disabled}
            value={char}
            onChange={(e) => handleChange(e, index)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            onPaste={handlePaste}
            className={`w-11 sm:w-12 h-12 sm:h-13 text-center text-lg sm:text-xl font-semibold rounded-xl border transition-all duration-150 outline-none select-none ${
              hasError
                ? 'border-[#C9362B] bg-[#FFFBFB] text-[#C9362B] focus:ring-3 focus:ring-[#C9362B]/15'
                : char
                ? 'border-[#193B64] bg-white text-[#172033] focus:ring-3 focus:ring-[#2C6EBA]/15'
                : 'border-[#D9E0E8] bg-white text-[#172033] hover:border-[#BFC8D4] focus:border-[#2C6EBA] focus:ring-3 focus:ring-[#2C6EBA]/15'
            } disabled:bg-[#F5F7FA] disabled:opacity-50`}
            aria-label={`Số thứ ${index + 1}`}
          />
        );
      })}
    </div>
  );
};
