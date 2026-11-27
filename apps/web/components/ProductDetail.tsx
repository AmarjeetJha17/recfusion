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
  const missing = Object.entries(product.specifications).filter(([, value]) => value === null);
  return (
    <main className="page-shell product-detail-page" id="main-content">
      <nav aria-label="Breadcrumb" className="breadcrumbs">
        <Link href="/">Discover</Link>
        <span aria-hidden="true">/</span>
        <span>{product.category}</span>
      </nav>
      <section className="product-detail">
        <div className="product-detail__visual">
          <ProductArt category={product.category} />
          <span className="synthetic-stamp">Synthetic fixture</span>
        </div>
        <div className="product-detail__copy">
          <p className="eyebrow">{product.category} · invented example</p>
          <h1>{product.name ?? "Title unavailable"}</h1>
          <p className="product-detail__description">{product.description}</p>
          <p className="product-id">
            <span>Fixture ID</span>
            <code>{product.id}</code>
          </p>
          <div className="detail-summary">
            <span className={`cohort cohort--${product.cohort}`}>
              {product.cohort === "unknown"
                ? "Eligibility unknown"
                : `${product.cohort} item fixture`}
            </span>
            <span>Not a real listing · no price or availability data</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="specifications-heading" className="spec-section">
        <div className="spec-section__heading">
          <div>
            <p className="eyebrow">Available fixture fields</p>
            <h2 id="specifications-heading">Specifications</h2>
          </div>
          <p>Invented attributes for layout and contract testing.</p>
        </div>
        <dl className="spec-list">
          {Object.entries(product.specifications).map(([name, value]) => (
            <div className="spec-row" key={name}>
              <dt>{name}</dt>
              <dd>
                {value ?? (
                  <span className="missing-value">Not available in this synthetic fixture</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
        {missing.length > 0 && (
          <p className="missing-summary" role="note">
            {missing.length} {missing.length === 1 ? "attribute is" : "attributes are"} unavailable
            in this fixture. No values have been inferred.
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
