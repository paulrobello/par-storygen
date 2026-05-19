"use client";

import type { ReactNode } from "react";
import { Header } from "./Header";

interface GameLayoutProps {
  children: ReactNode;
}

export function GameLayout({ children }: GameLayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100 overflow-hidden">
      <Header />
      <main className="flex-1 flex flex-col overflow-hidden">{children}</main>
    </div>
  );
}
