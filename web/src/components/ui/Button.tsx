"use client";

import { type ButtonHTMLAttributes, forwardRef } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "neon";
  size?: "sm" | "md" | "lg";
}

const variants = {
  primary:
    "bg-cyan-600 hover:bg-cyan-500 text-white border border-cyan-500/30",
  secondary:
    "bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-600/50",
  ghost:
    "bg-transparent hover:bg-gray-800/50 text-gray-300 border border-transparent",
  danger:
    "bg-red-900/50 hover:bg-red-800/50 text-red-300 border border-red-700/50",
  neon: "bg-transparent text-cyan-400 border border-cyan-400/60 hover:bg-cyan-400/10 hover:border-cyan-400 neon-border-cyan",
};

const sizes = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-base",
  lg: "px-6 py-3 text-lg",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", className = "", children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={`
          inline-flex items-center justify-center rounded-lg font-medium
          transition-all duration-200 cursor-pointer
          disabled:opacity-40 disabled:cursor-not-allowed
          focus:outline-none focus:ring-2 focus:ring-cyan-500/50
          ${variants[variant]}
          ${sizes[size]}
          ${className}
        `}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
