import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GridPulse SCADA — Real-Time Campus Energy Telemetry",
  description: "Ultra-fast Next.js Operations Portal for high-frequency IoT streaming analytics, 5-minute sliding windows, and automated peak-shaving dispatch.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-[#090D16] text-slate-100 selection:bg-amber-400/30 selection:text-amber-200">
        {children}
      </body>
    </html>
  );
}
