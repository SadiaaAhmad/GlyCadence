import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import "./globals.css";
import { PatientProvider } from "@/components/providers/PatientProvider";
import { AppShell } from "@/components/layout/AppShell";
import { SplashIntro } from "@/components/layout/SplashIntro";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["600", "700"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "GlyCadence | Warm, Evidence-Grounded Diabetes Companion",
  description:
    "Empathetic Type 2 diabetes companion with personalised meal insights, Ramadan support, and doctor visit prep.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${fraunces.variable} ${inter.variable} h-full antialiased`}>
      <body className="min-h-full">
        <SplashIntro />
        <PatientProvider>
          <AppShell>{children}</AppShell>
        </PatientProvider>
      </body>
    </html>
  );
}
