"use client";

import { ImageIcon } from "lucide-react";

interface ImagePanelProps {
  imageUrl: string | null;
  imageStatus: string;
  alt?: string;
}

export function ImagePanel({ imageUrl, imageStatus, alt = "Scene illustration" }: ImagePanelProps) {
  if (imageStatus === "generating") {
    return (
      <div className="w-full aspect-[16/9] bg-gray-900 rounded-lg border border-gray-800 flex items-center justify-center shimmer" style={{ backgroundColor: '#828181' }}>
        <div className="text-center">
          <ImageIcon className="mx-auto mb-2 text-cyan-400 neon-pulse" size={32} />
          <p className="text-sm text-gray-400">Generating illustration...</p>
        </div>
      </div>
    );
  }

  if (!imageUrl) {
    return null;
  }

  return (
    <div className="w-full rounded-lg overflow-hidden border border-gray-800" style={{ backgroundColor: '#828181' }}>
      <img
        src={imageUrl}
        alt={alt}
        className="w-full object-contain"
      />
    </div>
  );
}
