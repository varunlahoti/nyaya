import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nyaya — AI Legal Research for Indian Advocates",
  description:
    "Type the facts of a case. Get the most relevant Supreme Court and High Court judgments, with source links.",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, title: "Nyaya", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  themeColor: "#233043",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        {children}
        <script
          dangerouslySetInnerHTML={{
            __html: `if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}`,
          }}
        />
      </body>
    </html>
  );
}
