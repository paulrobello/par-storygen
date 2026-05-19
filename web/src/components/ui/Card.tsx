"use client";

import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  neon?: boolean;
}

export function Card({ children, className = "", onClick, neon = false }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={`
        rounded-xl border p-4
        bg-gray-900/80 border-gray-700/50
        ${neon ? "neon-border-cyan border-cyan-800/50" : ""}
        ${onClick ? "cursor-pointer hover:border-gray-600/70 hover:bg-gray-800/80 transition-all duration-200" : ""}
        ${className}
      `}
    >
      {children}
    </div>
  );
}
