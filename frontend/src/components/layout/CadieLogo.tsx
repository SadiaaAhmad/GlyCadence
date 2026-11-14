import React from "react";

interface CadieLogoProps {
  compact?: boolean;
}

export function CadieLogo({ compact = false }: CadieLogoProps) {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF1F1] border border-[#FF4D4D]/20">
        <svg
          width="28"
          height="28"
          viewBox="0 0 36 36"
          fill="none"
          aria-label="Cadie mascot"
          role="img"
        >
          {/* Rounded blood glucose droplet in #FF4D4D */}
          <path
            d="M18 4.5C18 4.5 9 14.2 9 21.2C9 26.2 13 30.5 18 30.5C23 30.5 27 26.2 27 21.2C27 14.2 18 4.5 18 4.5Z"
            fill="#FF4D4D"
          />
          {/* Curious expressive eyes */}
          <circle cx="15" cy="20.5" r="1.7" fill="#FFFFFF" />
          <circle cx="21" cy="20.5" r="1.7" fill="#FFFFFF" />
          <circle cx="15.3" cy="20.2" r="0.8" fill="#0F172A" />
          <circle cx="21.3" cy="20.2" r="0.8" fill="#0F172A" />
          {/* Gentle smile */}
          <path
            d="M15.8 24C16.5 25 19.5 25 20.2 24"
            stroke="#FFFFFF"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          {/* Guiding 4-point sparkle */}
          <path
            d="M29.5 5.5L30.3 7.7L32.5 8.5L30.3 9.3L29.5 11.5L28.7 9.3L26.5 8.5L28.7 7.7L29.5 5.5Z"
            fill="#0F4C5C"
          />
        </svg>
      </div>
      {!compact && (
        <div className="flex flex-col leading-none">
          <span className="text-lg font-bold tracking-tight">
            <span className="text-[#0F4C5C]">Gly</span>
            <span className="text-[#FF4D4D]">Cadence</span>
          </span>
          <span className="mt-0.5 text-[11px] font-medium text-slate-500">
            Diabetes &amp; Wellbeing
          </span>
        </div>
      )}
    </div>
  );
}
