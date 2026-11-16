"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export function BackToMoreButton() {
  return (
    <Link
      href="/more"
      className="inline-flex items-center gap-2 rounded-full border border-[var(--border-clay)] bg-[var(--bg-card)] px-4 py-2 text-sm font-semibold text-[var(--text-main)] shadow-sm transition hover:border-[#FF4D4D] hover:text-[#FF4D4D]"
    >
      <ArrowLeft className="h-4 w-4" />
      <span>Back to More</span>
    </Link>
  );
}
