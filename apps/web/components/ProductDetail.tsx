import Link from "next/link";
import { ProductArt } from "@/components/ProductArt";
import { ProductCard } from "@/components/ProductCard";
import { getSimilarProducts, type Product } from "@/lib/catalog";

export function ProductDetail({
  product,
  similarProducts = getSimilarProducts(product.id),
}: {
  product: Product;
  similarProducts?: Product[];
}) {
  return (
    <main className="page-shell product-detail-page" id="main-content">
      <nav aria-label="Breadcrumb" className="breadcrumbs">
        <Link href="/">Discover</Link>
        <span aria-hidden="true">/</span>
        <span>{product.category ?? "Category unavailable"}</span>
      </nav>
      <section className="product-detail">
        <div className="product-detail__visual">
          <ProductArt category={product.category} />
          <span className="synthetic-stamp">Synthetic fixture</span>
        </div>
        <div className="product-detail__copy">
          <p className="eyebrow">{product.category ?? "Category unavailable"} · invented example</p>
          <h1>{product.name ?? "Title unavailable"}</h1>
          {product.description && (
            <p className="product-detail__description">{product.description}</p>
          )}
          <p className="product-id">
            <span>Fixture ID</span>
            <code>{product.id}</code>
          </p>
          <div className="detail-summary">
            <span>{product.catalogEligible ? "Catalog eligible" : "Not catalog eligible"}</span>
            <span>Not a real listing · no price or availability data</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="features-heading" className="spec-section">
        <div className="spec-section__heading">
          <div>
            <p className="eyebrow">Available fixture fields</p>
            <h2 id="features-heading">Recorded features</h2>
          </div>
          <p>Invented attributes for layout and contract testing.</p>
        </div>
        <ul className="spec-list">
          {product.features.map((feature) => (
            <li className="spec-row" key={feature}>
              {feature}
            </li>
          ))}
        </ul>
        {product.features.length === 0 && (
          <p className="missing-summary" role="note">
            No feature details are recorded for this item. No values have been inferred.
          </p>
        )}
      </section>

      <section aria-labelledby="similar-heading" className="similar-section">
        <div className="catalog-heading-row">
          <div>
            <p className="eyebrow">Static, deterministic example</p>
            <h2 id="similar-heading">Similar synthetic products</h2>
          </div>
          <p className="results-note">Fixture suggestions · not a live model result</p>
        </div>
        {similarProducts.length ? (
          <div className="product-grid product-grid--compact">
            {similarProducts.map((similar) => (
              <ProductCard key={similar.id} product={similar} />
            ))}
          </div>
        ) : (
          <p className="empty-state" role="status">
            No similar-product fixtures are available for this item.
          </p>
        )}
      </section>
    </main>
  );
}
