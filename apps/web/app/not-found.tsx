import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page-shell not-found" id="main-content">
      <p className="eyebrow">Nothing at this address</p>
      <h1>We can’t find that fixture.</h1>
      <p>Only products in the local synthetic catalog have detail pages.</p>
      <Link className="button button--primary" href="/">
        Return to discovery
      </Link>
    </main>
  );
}
