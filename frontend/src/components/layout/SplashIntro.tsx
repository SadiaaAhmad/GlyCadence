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
        <div className="relative flex flex-col items-center">
          {/* Animated faithful SVG of the GlyCadence mascot: bounce -> wink -> arm wave */}
          <svg
            viewBox="0 0 200 210"
            className="animate-gc-mascot h-36 w-36 select-none overflow-visible"
            aria-label="GlyCadence mascot waving and winking"
            role="img"
          >
            {/* Top-right 4-point sparkle */}
            <path
              className="animate-gc-sparkle"
              d="M160 18 L164 31 L177 35 L164 39 L160 52 L156 39 L143 35 L156 31 Z"
              fill="#EF4444"
            />

            {/* Left leg */}
            <path
              d="M84 152 L84 182 Q84 188 72 188 Q66 188 66 183 Q66 178 75 178 L75 152 Z"
              fill="#D93226"
            />
            {/* Right leg */}
            <path
              d="M114 152 L114 182 Q114 188 126 188 Q132 188 132 183 Q132 178 123 178 L123 152 Z"
              fill="#D93226"
            />

            {/* Left arm */}
            <path
              d="M58 118 Q40 132 34 148"
              stroke="#D93226"
              strokeWidth="10"
              strokeLinecap="round"
              fill="none"
            />

            {/* Right arm (waves happily after the wink!) */}
            <g className="animate-gc-wave">
              <path
                d="M142 118 Q160 130 166 146"
                stroke="#EF4444"
                strokeWidth="10"
                strokeLinecap="round"
                fill="none"
              />
            </g>

            {/* Droplet body with subtle left-side shading */}
            <path
              d="M100 18 C100 18 46 74 46 116 C46 146 70 164 100 164 C130 164 154 146 154 116 C154 74 100 18 100 18 Z"
              fill="#EF4444"
            />
            <path
              d="M100 18 C100 18 46 74 46 116 C46 146 70 164 100 164 C80 156 64 138 64 114 C64 82 88 42 100 18 Z"
              fill="#DC2626"
              opacity="0.32"
            />
            {/* Gloss highlight */}
            <path
              d="M112 38 Q125 50 132 64"
              stroke="#FCA5A5"
              strokeWidth="5"
              strokeLinecap="round"
              fill="none"
              opacity="0.7"
            />

            {/* Left eye */}
            <g>
              <ellipse cx="86" cy="108" rx="11" ry="12.5" fill="#FFFFFF" />
              <circle cx="88.5" cy="106.5" r="6.2" fill="#0F172A" />
            </g>

            {/* Right eye (winks!) */}
            <g className="animate-gc-wink">
              <ellipse cx="118" cy="104" rx="11" ry="12.5" fill="#FFFFFF" />
              <circle cx="120.5" cy="102.5" r="6.2" fill="#0F172A" />
            </g>

            {/* Cute smile */}
            <path
              d="M97 121 Q105 128 113 120"
              stroke="#0F172A"
              strokeWidth="3.5"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
          <div className="animate-gc-shadow mt-1 h-2.5 w-16 rounded-full bg-[#EF4444]/35 blur-[3px]" />
        </div>

        <div className="animate-gc-word mt-4 text-center">
          <div className="font-display text-3xl font-bold tracking-tight text-[var(--text-ink)]">
            Gly<span className="text-[#EF4444]">Cadence</span>
          </div>
          <p className="mt-1 text-xs font-medium tracking-wide text-[var(--text-muted)]">
            Your daily diabetes companion
          </p>
        </div>

        <div className="animate-gc-word mt-5 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444] animate-bounce [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/70 animate-bounce [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]/40 animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
