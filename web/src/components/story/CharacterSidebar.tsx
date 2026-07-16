"use client";

import { useState } from "react";
import type { Character } from "@/lib/api";
import { User, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { API_BASE } from "@/lib/config";

interface CharacterSidebarProps {
  characters: Character[];
  gameId?: string;
  onCharacterClick?: (character: Character) => void;
}

export function CharacterSidebar({ characters, gameId, onCharacterClick }: CharacterSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (characters.length === 0) return null;

  return (
    <div
      className={`flex-shrink-0 border-r border-gray-800 bg-gray-950/50 flex flex-col transition-all duration-200 ${
        collapsed ? "w-10" : "w-56"
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-2 border-b border-gray-800">
        {!collapsed && (
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-1">
            Characters
          </h3>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-gray-800/60 transition-colors"
          title={collapsed ? "Expand characters" : "Collapse characters"}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>

      {/* Character list */}
      {!collapsed && (
        <div className="overflow-y-auto flex-1 p-2">
          <div className="space-y-1">
            {characters.map((char) => (
              <button
                key={char.id}
                onClick={() => onCharacterClick?.(char)}
                className="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-gray-800/60 transition-colors text-left"
              >
                {char.portrait_path && gameId ? (
                  <div className="w-10 h-10 rounded-lg overflow-hidden border border-gray-700 flex-shrink-0" style={{ backgroundColor: '#828181' }}>
                    <img
                      src={`${API_BASE}/api/images/${gameId}/portrait/${char.id}`}
                      alt={char.name}
                      className="w-full h-full object-contain"
                    />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
                    <User size={18} className="text-gray-500" />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-200 truncate">
                    {char.name}
                  </p>
                  {char.backstory_summary && (
                    <p className="text-xs text-gray-500 truncate">
                      {char.backstory_summary}
                    </p>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Collapsed: just portraits stacked */}
      {collapsed && (
        <div className="overflow-y-auto flex-1 p-1.5 flex flex-col items-center gap-1.5">
          {characters.map((char) => (
            <button
              key={char.id}
              onClick={() => onCharacterClick?.(char)}
              className="w-7 h-7 rounded-md overflow-hidden border border-gray-700 flex-shrink-0"
              style={{ backgroundColor: '#828181' }}
              title={char.name}
            >
              {char.portrait_path && gameId ? (
                <img
                  src={`${API_BASE}/api/images/${gameId}/portrait/${char.id}`}
                  alt={char.name}
                  className="w-full h-full object-contain"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-gray-800">
                  <User size={12} className="text-gray-500" />
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
