"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function SiteHeader() {
  const path = usePathname();
  const active = path === "/explore" ? "explore" : "discover";
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header__inner">
          <Link aria-label="RecFusion home" className="brand" href="/">
            <span aria-hidden="true" className="brand__mark">
              rf
            </span>
            <span className="brand__name">
              RecFusion<span className="brand__period">.</span>
            </span>
          </Link>
          <nav aria-label="Main navigation" className="site-nav">
            <Link aria-current={active === "discover" ? "page" : undefined} href="/">
              Discover
            </Link>
            <Link aria-current={active === "explore" ? "page" : undefined} href="/explore">
              Recommendation lab
            </Link>
          </nav>
          <span className="demo-indicator">
            <span aria-hidden="true" /> Demo mode
          </span>
        </div>
      </header>
    </>
  );
}
