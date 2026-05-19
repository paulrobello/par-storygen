"use client";

import Link from "next/link";
import { BookOpen, FolderOpen, Settings, Sparkles, Users } from "lucide-react";

const menuItems = [
  {
    href: "/wizard",
    icon: BookOpen,
    label: "📖  New Story",
    description: "Create a new adventure",
    accent: "text-cyan-400 border-cyan-400/30 hover:border-cyan-400/60 hover:bg-cyan-400/5",
  },
  {
    href: "/presets",
    icon: Sparkles,
    label: "⚡  Quick Start",
    description: "Pick a preset & play",
    accent: "text-purple-400 border-purple-400/30 hover:border-purple-400/60 hover:bg-purple-400/5",
  },
  {
    href: "/load",
    icon: FolderOpen,
    label: "📂  Load Story",
    description: "Continue an existing game",
    accent: "text-fuchsia-400 border-fuchsia-400/30 hover:border-fuchsia-400/60 hover:bg-fuchsia-400/5",
  },
  {
    href: "/settings",
    icon: Settings,
    label: "⚙️  Settings",
    description: "Configure providers & preferences",
    accent: "text-amber-400 border-amber-400/30 hover:border-amber-400/60 hover:bg-amber-400/5",
  },
  {
    href: "/characters",
    icon: Users,
    label: "👤  Characters",
    description: "Browse your character library",
    accent: "text-green-400 border-green-400/30 hover:border-green-400/60 hover:bg-green-400/5",
  },
];

export default function MenuPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-950 px-4">
      {/* Title */}
      <div className="mb-16 text-center">
        <h1 className="text-5xl font-bold tracking-tight mb-3">
          <span className="neon-glow-cyan text-cyan-400">Story</span>
          <span className="text-gray-100">Gen</span>
        </h1>
        <p className="text-gray-500 text-lg">
          AI-Powered Choose Your Own Adventure
        </p>
      </div>

      {/* Menu Buttons */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-lg">
        {menuItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`
              flex flex-col items-center gap-3 p-6 rounded-xl border
              transition-all duration-300 group
              bg-gray-900/50 ${item.accent}
            `}
          >
            <item.icon size={28} className="opacity-80 group-hover:opacity-100 transition-opacity" />
            <span className="text-lg font-semibold">{item.label}</span>
            <span className="text-xs text-gray-500">{item.description}</span>
          </Link>
        ))}
      </div>

      {/* Footer */}
      <div className="mt-16 text-gray-600 text-xs">
        Powered by AI •{" "}
        <span className="text-gray-500">par-storygen</span>
      </div>
    </div>
  );
}
