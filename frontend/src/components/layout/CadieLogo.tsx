import React from "react";

interface CadieLogoProps {
  compact?: boolean;
}

export function CadieLogo({ compact = false }: CadieLogoProps) {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <img
        src="/glycadence-logo.png"
        alt="GlyCadence mascot"
        className="h-10 w-10 shrink-0 object-contain"
      />
      {!compact && (
        <div className="flex flex-col leading-none">
          <span className="text-lg font-bold tracking-tight text-[var(--text-ink)]">
            Gly<span className="text-[#EF4444]">Cadence</span>
          </span>
          <span className="mt-0.5 text-[11px] font-medium text-[var(--text-muted)]">
            Diabetes &amp; Wellbeing
          </span>
        </div>
      )}
    </div>
  );
}
