"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Volume2, VolumeX, Loader2, Play, Pause } from "lucide-react";
import { apiPost } from "@/lib/api";

const API_BASE = "http://localhost:8101";

interface AudioPlayerProps {
  gameId: string;
  nodeId: string;
  narration: string;
}

export function AudioPlayer({ gameId, nodeId, narration }: AudioPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Clean up on node change.
  useEffect(() => {
    setAudioUrl(null);
    setIsPlaying(false);
    setIsGenerating(false);
    setError(null);
    setProgress(0);
  }, [nodeId]);

  const generate = useCallback(async () => {
    if (!narration) return;
    setIsGenerating(true);
    setError(null);
    try {
      const result = await apiPost<{ audio_url: string; status: string }>(
        `/api/tts/${gameId}/${nodeId}/generate`,
        {},
      );
      const url = `${API_BASE}${result.audio_url}`;
      setAudioUrl(url);
      // Auto-play once the audio element mounts with the URL.
      setTimeout(() => {
        audioRef.current?.play();
      }, 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : "TTS generation failed");
    } finally {
      setIsGenerating(false);
    }
  }, [gameId, nodeId, narration]);

  const togglePlay = useCallback(() => {
    if (!audioUrl) {
      generate();
      return;
    }
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
    } else {
      audio.play();
    }
  }, [audioUrl, isPlaying, generate]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => {
      setIsPlaying(false);
      setProgress(0);
    };
    const onTimeUpdate = () => {
      if (audio.duration) {
        setProgress((audio.currentTime / audio.duration) * 100);
      }
    };

    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("timeupdate", onTimeUpdate);

    return () => {
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("timeupdate", onTimeUpdate);
    };
  }, [audioUrl]);

  if (!narration) return null;

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-800 bg-gray-950/30">
      {audioUrl && <audio ref={audioRef} src={audioUrl} preload="auto" />}

      <button
        onClick={togglePlay}
        disabled={isGenerating}
        className="flex items-center justify-center w-8 h-8 rounded-lg bg-cyan-900/30 border border-cyan-700/40 text-cyan-400 hover:bg-cyan-800/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        title={isPlaying ? "Pause" : audioUrl ? "Play" : "Generate & Play narration"}
      >
        {isGenerating ? (
          <Loader2 size={16} className="animate-spin" />
        ) : isPlaying ? (
          <Pause size={16} />
        ) : (
          <Play size={16} className="ml-0.5" />
        )}
      </button>

      {/* Progress bar */}
      <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-cyan-500 rounded-full transition-all duration-200"
          style={{ width: `${progress}%` }}
        />
      </div>

      <span className="text-xs text-gray-500 whitespace-nowrap">
        {isGenerating
          ? "Generating..."
          : isPlaying
            ? "Playing"
            : audioUrl
              ? "Read aloud"
              : "Read aloud"}
      </span>

      {error && (
        <span className="text-xs text-red-400 truncate max-w-[200px]" title={error}>
          {error}
        </span>
      )}
    </div>
  );
}
