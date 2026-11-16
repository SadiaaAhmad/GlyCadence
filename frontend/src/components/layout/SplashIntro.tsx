"use client";

import React, { useEffect, useState } from "react";

export function SplashIntro() {
  const [visible, setVisible] = useState(false);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    try {
      if (sessionStorage.getItem("gc_splash_shown")) return;
      sessionStorage.setItem("gc_splash_shown", "1");
      setVisible(true);
      const fadeTimer = setTimeout(() => setFading(true), 2900);
      const hideTimer = setTimeout(() => setVisible(false), 3450);
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    } catch {
      return undefined;
    }
  }, []);

  if (!visible) return null;

  return (
    <div
      onClick={() => {
        setFading(true);
        setTimeout(() => setVisible(false), 300);
      }}
      role="status"
      aria-label="Loading GlyCadence"
      className={`fixed inset-0 z-50 flex cursor-pointer flex-col items-center justify-center bg-[var(--bg-page)] transition-opacity duration-500 ${
        fading ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
    >
      <div className="flex flex-col items-center">
        {/* Cute Mascot Drop + Squish Bounce + Happy Hop */}
        <div className="relative flex flex-col items-center">
          <img
            src="/glycadence-logo.png"
            alt="GlyCadence mascot"
            className="animate-gc-mascot h-28 w-28 object-contain select-none"
          />
          <div className="animate-gc-shadow mt-1 h-2.5 w-16 rounded-full bg-[#EF4444]/35 blur-[3px]" />
        </div>

        {/* Clean Wordmark Reveal */}
        <div className="animate-gc-word mt-5 text-center">
          <div className="font-display text-3xl font-bold tracking-tight text-[var(--text-ink)]">
            Gly<span className="text-[#EF4444]">Cadence</span>
          </div>
          <p className="mt-1 text-xs font-medium tracking-wide text-[var(--text-muted)]">
            Your daily diabetes companion
          </p>
        </div>

        {/* Subtle 3-dot Loading Cadence */}
        <div className="animate-gc-word mt-6 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444] animate-bounce [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/70 animate-bounce [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/40 animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
