import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { type ReactNode } from "react";
import { AuthProvider } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/layout/app-shell";
import { QueryProvider } from "@/components/providers/query-provider";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter"
});

export const metadata: Metadata = {
  title: {
    default: "Renewi Access",
    template: "%s | Renewi Access"
  },
  description:
    "Local manager demo for contractor and visitor site access assurance."
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

// PUBLIC_INTERFACE
/**
 * Defines the document shell and shared providers for every application route.
 */
export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <QueryProvider>
          <AuthProvider>
            <AppShell>{children}</AppShell>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
