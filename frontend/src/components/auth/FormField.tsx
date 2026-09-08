import React, { forwardRef } from 'react';

export interface FormFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  rightElement?: React.ReactNode;
  leftIcon?: React.ReactNode;
  isRequired?: boolean;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  (
    {
      id,
      label,
      error,
      hint,
      rightElement,
      leftIcon,
      isRequired,
      className = '',
      type = 'text',
      ...rest
    },
    ref
  ) => {
    const inputId = id || (rest.name ? `field-${rest.name}` : undefined);
    const errorId = inputId ? `${inputId}-error` : undefined;
    const hintId = inputId ? `${inputId}-hint` : undefined;

    return (
      <div className="w-full text-left">
        <div className="flex items-center justify-between mb-1.5">
          <label
            htmlFor={inputId}
            className="block text-[13px] font-medium text-[#172033] select-none"
          >
            {label}
            {isRequired && <span className="text-[#C9362B] ml-1 font-normal">*</span>}
          </label>
          {hint && !error && (
            <span id={hintId} className="text-[12px] text-[#667085]">
              {hint}
            </span>
          )}
        </div>

        <div className="relative">
          {leftIcon && (
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#667085]">
              {leftIcon}
            </div>
          )}

          <input
            ref={ref}
            id={inputId}
            type={type}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : hint ? hintId : undefined}
            className={`w-full h-12 rounded-xl text-[14px] text-[#172033] placeholder-[#667085]/60 bg-white border transition-all duration-150 outline-none ${
              leftIcon ? 'pl-10' : 'pl-3.5'
            } ${rightElement ? 'pr-11' : 'pr-3.5'} ${
              error
                ? 'border-[#C9362B] bg-[#FFFBFB] focus:border-[#C9362B] focus:ring-3 focus:ring-[#C9362B]/15'
                : 'border-[#D9E0E8] hover:border-[#BFC8D4] focus:border-[#2C6EBA] focus:ring-3 focus:ring-[#2C6EBA]/15'
            } ${className}`}
            {...rest}
          />

          {rightElement && (
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center">
              {rightElement}
            </div>
          )}
        </div>

        {/* Error message with minimum reserved height to avoid layout jump */}
        <div className="min-h-[20px] mt-1">
          {error && (
            <p
              id={errorId}
              className="text-[12px] text-[#C9362B] font-medium flex items-center gap-1 transition-opacity duration-150"
            >
              <span>{error}</span>
            </p>
          )}
        </div>
      </div>
    );
  }
);

FormField.displayName = 'FormField';
