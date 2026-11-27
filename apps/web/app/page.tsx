import Link from "next/link";
import { DiscoveryCatalog } from "@/components/DiscoveryCatalog";

export default function DiscoverPage() {
  return (
    <main className="page-shell" id="main-content">
      <section className="hero" aria-labelledby="page-title">
        <div className="hero__copy">
          <p className="hero__kicker">
            <span className="hero__kicker-line" /> ELECTRONICS, REIMAGINED
          </p>
          <h1 id="page-title">
            Find your next
            <br />
            <em>setup idea.</em>
          </h1>
          <p className="hero__lede">
            Explore a small, thoughtfully made catalog of invented devices. Browse by the details
            that matter to your setup.
          </p>
          <div className="hero__actions">
            <a className="button button--primary" href="#catalog-heading">
              Browse the catalog <span aria-hidden="true">↓</span>
            </a>
            <Link className="hero__text-link" href="/explore">
              Open recommendation lab <span aria-hidden="true">↗</span>
            </Link>
          </div>
          <p className="hero__scope">A UI prototype with static fixtures. No products for sale.</p>
        </div>
        <div className="hero__visual" aria-hidden="true">
          <div className="hero-orbit hero-orbit--outer" />
          <div className="hero-orbit hero-orbit--inner" />
          <div className="hero-product hero-product--display">
            <div className="hero-product__screen">
              <span />
              <span />
              <span />
            </div>
            <div className="hero-product__stand" />
          </div>
          <div className="hero-product hero-product--phone">
            <span />
          </div>
          <div className="hero-product hero-product--earcup" />
          <div className="hero-art-caption">
            <span>01 / 05</span>
            <span>Objects for another world</span>
          </div>
        </div>
        <div className="hero__index">
          <span>01</span>
          <span>Explore</span>
        </div>
      </section>

      <div className="demo-banner" role="note">
        <span className="demo-banner__icon" aria-hidden="true">
          ✳
        </span>
        <p>
          <strong>Everything here is synthetic.</strong> Product names, specifications, eligibility,
          and recommendation order are invented fixtures.
        </p>
        <span className="demo-banner__tag">DEMO ONLY</span>
      </div>

      <DiscoveryCatalog />
    </main>
  );
}
