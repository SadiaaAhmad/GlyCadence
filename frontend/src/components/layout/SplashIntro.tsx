"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

export function SplashIntro() {
  const [visible, setVisible] = useState(true);
  const [fading, setFading] = useState(false);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const playSplash = useCallback(() => {
    timersRef.current.forEach(clearTimeout);
    setVisible(true);
    setFading(false);
    const t1 = setTimeout(() => setFading(true), 2700);
    const t2 = setTimeout(() => setVisible(false), 3200);
    timersRef.current = [t1, t2];
  }, []);

  useEffect(() => {
    playSplash();
    const handler = () => playSplash();
    window.addEventListener("gc-show-splash", handler);
    return () => {
      window.removeEventListener("gc-show-splash", handler);
      timersRef.current.forEach(clearTimeout);
    };
  }, [playSplash]);

  if (!visible) return null;

  return (
    <div
      onClick={() => {
        setFading(true);
        setTimeout(() => setVisible(false), 250);
      }}
      role="status"
      aria-label="Loading GlyCadence"
      className={`fixed inset-0 z-50 flex cursor-pointer flex-col items-center justify-center bg-[var(--bg-page)] transition-opacity duration-500 ${
        fading ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
    >
      <div className="flex flex-col items-center">
        <div className="relative flex flex-col items-center">
          <img
            src="/glycadence-logo.png"
            alt="GlyCadence mascot"
            className="animate-gc-mascot h-28 w-28 object-contain select-none"
          />
          <div className="animate-gc-shadow mt-1 h-2.5 w-16 rounded-full bg-[#EF4444]/35 blur-[3px]" />
        </div>

        <div className="animate-gc-word mt-5 text-center">
          <div className="font-display text-3xl font-bold tracking-tight text-[var(--text-ink)]">
            Gly<span className="text-[#EF4444]">Cadence</span>
          </div>
          <p className="mt-1 text-xs font-medium tracking-wide text-[var(--text-muted)]">
            Your daily diabetes companion
          </p>
        </div>

        <div className="animate-gc-word mt-6 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444] animate-bounce [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/70 animate-bounce [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/40 animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
