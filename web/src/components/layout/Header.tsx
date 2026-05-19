"use client";

import Link from "next/link";
import { BookOpen, Home } from "lucide-react";

export function Header() {
  return (
    <header className="h-14 border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm flex items-center justify-between px-6 sticky top-0 z-40">
      <Link href="/menu" className="flex items-center gap-2 text-cyan-400 hover:text-cyan-300 transition-colors">
        <BookOpen size={22} />
        <span className="font-bold text-lg tracking-wide neon-glow-cyan">StoryGen</span>
      </Link>
      <nav className="flex items-center gap-4">
        <Link
          href="/menu"
          className="text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1.5 text-sm"
        >
          <Home size={16} />
          Menu
        </Link>
      </nav>
    </header>
  );
}
