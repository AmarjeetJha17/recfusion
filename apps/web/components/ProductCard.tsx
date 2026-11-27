import Link from "next/link";
import { ProductArt } from "@/components/ProductArt";
import { getProductRouteId, type Product } from "@/lib/catalog";

const categoryLabel = {
  laptop: "Laptop",
  audio: "Headphones",
  smartphone: "Smartphone",
  monitor: "Monitor",
  accessory: "Accessory",
} as const;

export function ProductCard({ product }: { product: Product }) {
  const title = product.name ?? "Title unavailable";
  const availableSpecs = product.features.length;
  return (
    <article className="product-card">
      <Link
        aria-label={`View details for ${title}`}
        className="product-card__main-link"
        href={`/products/${getProductRouteId(product)}`}
      >
        <ProductArt category={product.category} />
        <div className="product-card__body">
          <div className="product-card__eyebrow">
            <span>
              {product.category ? categoryLabel[product.category] : "Category unavailable"}
            </span>
            <span>Synthetic item</span>
          </div>
          <h3>{title}</h3>
          {product.description && <p>{product.description}</p>}
          <div className="product-card__footer">
            <span>{availableSpecs} features recorded</span>
            <span className="product-card__arrow" aria-hidden="true">
              ↗
            </span>
          </div>
        </div>
      </Link>
    </article>
  );
}
