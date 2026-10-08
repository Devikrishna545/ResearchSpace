import type { Metadata } from "next";
import { AuthShell } from "@/features/auth/components/auth-shell";
import { ThemeProvider } from "@/components/ui/theme-provider";
import { themeBootstrapScript } from "@/lib/utils/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "R.Space",
  description: "A local-first space for grounded research"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} /></head>
      <body><ThemeProvider><AuthShell>{children}</AuthShell></ThemeProvider></body>
    </html>
  );
}
