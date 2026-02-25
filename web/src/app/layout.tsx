import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Gridlock — Fix America's Cities",
  description: "Real-world city transit simulation game",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
