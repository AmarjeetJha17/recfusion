"use client";

import { useMemo, useState } from "react";
import { ProductCard } from "@/components/ProductCard";
import {
  type CategoryFilter,
  type ProductCategory,
  type ProductSort,
  searchCatalog,
  sortProducts,
} from "@/lib/catalog";

const categories: { id: CategoryFilter; label: string }[] = [
  { id: "all", label: "All devices" },
  { id: "laptop", label: "Laptops" },
  { id: "headphones", label: "Audio" },
  { id: "smartphone", label: "Phones" },
  { id: "monitor", label: "Displays" },
  { id: "accessory", label: "Accessories" },
];

export function DiscoveryCatalog() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [sort, setSort] = useState<ProductSort>("featured");
  const products = useMemo(
    () => sortProducts(searchCatalog(query, category), sort),
    [query, category, sort],
  );

  return (
    <section aria-labelledby="catalog-heading" className="catalog-section">
      <div className="catalog-heading-row">
        <div>
          <p className="eyebrow">A small world of made-up devices</p>
          <h2 id="catalog-heading">Explore the catalog</h2>
        </div>
        <label className="sort-control">
          <span>Sort by</span>
          <select
            aria-label="Sort products"
            onChange={(event) => setSort(event.target.value as ProductSort)}
            value={sort}
          >
            <option value="featured">Featured order</option>
            <option value="name">Name, A to Z</option>
            <option value="category">Category</option>
          </select>
        </label>
      </div>

      <div className="catalog-controls">
        <label className="search-field">
          <span className="search-field__icon" aria-hidden="true">
            ⌕
          </span>
          <span className="sr-only">Search synthetic electronics</span>
          <input
            aria-label="Search synthetic electronics"
            autoComplete="off"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search devices, features, or connectors"
            type="search"
            value={query}
          />
          <kbd>⌘ K</kbd>
        </label>
      </div>

      <div aria-label="Product categories" className="category-filter" role="group">
        {categories.map((item) => (
          <button
            aria-pressed={category === item.id}
            className={category === item.id ? "filter-chip is-active" : "filter-chip"}
            key={item.id}
            onClick={() => setCategory(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="results-toolbar">
        <p aria-live="polite" className="results-count">
          <strong>{products.length}</strong> {products.length === 1 ? "result" : "results"}
        </p>
        <p className="results-note">Invented examples · no live listings</p>
      </div>

      {products.length ? (
        <div className="product-grid">
          {products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      ) : (
        <div className="empty-state" role="status">
          <span className="empty-state__mark" aria-hidden="true">
            ⌕
          </span>
          <h3>No products match that search</h3>
          <p>Try a different device name or clear the selected category.</p>
          <button
            className="button button--secondary"
            onClick={() => {
              setQuery("");
              setCategory("all");
            }}
            type="button"
          >
            Clear filters
          </button>
        </div>
      )}
    </section>
  );
}

export type { ProductCategory };
