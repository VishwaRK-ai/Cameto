import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DigitalScam | Real-Time Fact-Verification & Deepfake Audit Engine",
  description: "AI-powered factual reasoning and synthetic image detection engine analyzing viral social media claims against ChromaDB ground truth.",
  manifest: "/manifest.json",
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#06b6d4" />
      </head>
      <body className="min-h-screen bg-[#070b14] text-slate-100 antialiased selection:bg-cyan-500/30 selection:text-cyan-200">
        {children}
      </body>
    </html>
  );
}

