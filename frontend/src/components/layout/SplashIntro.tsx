"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

export function SplashIntro() {
  const [visible, setVisible] = useState(true);
  const [fading, setFading] = useState(false);
  const [animKey, setAnimKey] = useState(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const playSplash = useCallback(() => {
    timersRef.current.forEach(clearTimeout);
    setAnimKey((k) => k + 1);
    setVisible(true);
    setFading(false);
    const t1 = setTimeout(() => setFading(true), 2950);
    const t2 = setTimeout(() => setVisible(false), 3450);
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
      <div key={animKey} className="flex flex-col items-center">
        {/* Exact original logo PNG kept completely still, with 1:1 eye-wink & upward-hand-wave overlay */}
        <div className="relative h-32 w-32 select-none">
          <img
            src="/glycadence-logo.png"
            alt="GlyCadence"
            className="h-full w-full object-contain"
          />
          <svg
            viewBox="0 0 300 305"
            className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
            aria-hidden="true"
          >
            {/* Gentle single wink over the right eye */}
            <g className="animate-gc-wink-once">
              <ellipse cx="188" cy="129" rx="16" ry="16" fill="rgb(249, 80, 65)" />
              <path
                d="M 175 131 Q 188 121 200 131"
                stroke="#18181B"
                strokeWidth="4.2"
                strokeLinecap="round"
                fill="none"
              />
            </g>

            {/* Hide static lower right arm and raise a matching arm upwards to wave */}
            <g className="animate-gc-wave-show">
              <rect x="217" y="177" width="32" height="50" rx="10" fill="var(--bg-page)" />
              <g className="animate-gc-hand-up">
                <path
                  d="M 220 178 Q 246 156 254 132"
                  stroke="rgb(223, 56, 35)"
                  strokeWidth="15"
                  strokeLinecap="round"
                  fill="none"
                />
              </g>
            </g>
          </svg>
        </div>

        <div className="animate-gc-word mt-4 text-center">
          <div className="font-display text-3xl font-bold tracking-tight text-[var(--text-ink)]">
            Gly<span className="text-[#EF4444]">Cadence</span>
          </div>
          <p className="mt-1 text-xs font-medium tracking-wide text-[var(--text-muted)]">
            Your daily diabetes companion
          </p>
        </div>
      </div>
    </div>
  );
}
