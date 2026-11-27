import type { Metadata } from "next";
import { SiteHeader } from "@/components/SiteHeader";
import "./styles.css";

export const metadata: Metadata = {
  title: "RecFusion — Synthetic Electronics Discovery",
  description: "A local-only interface demonstration using invented electronics fixtures.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        {children}
        <footer className="site-footer">
          <div className="page-shell site-footer__inner">
            <span>
              RecFusion <span aria-hidden="true">·</span> Synthetic interface checkpoint
            </span>
            <span>Invented devices only · local demonstration</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
