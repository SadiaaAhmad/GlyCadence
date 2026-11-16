"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export function BackToMoreButton() {
  return (
    <Link
      href="/more"
      className="inline-flex items-center gap-2 rounded-full border border-[#E9DCCB] bg-white px-4 py-2 text-sm font-semibold text-[#2B1E2F] shadow-sm transition hover:border-[#FF4D4D] hover:bg-[#FFF5F4] hover:text-[#FF4D4D]"
    >
      <ArrowLeft className="h-4 w-4" />
      <span>Back to More</span>
    </Link>
  );
}
