import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DiscoveryCatalog } from "@/components/DiscoveryCatalog";
import { ProductDetail } from "@/components/ProductDetail";
import { catalog, getSimilarProducts } from "@/lib/catalog";

describe("catalog and product presentation", () => {
  it("renders a labelled search, category filters, and synthetic product cards", () => {
    render(<DiscoveryCatalog />);

    expect(
      screen.getByRole("searchbox", { name: /search synthetic electronics/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accessories/i })).toBeInTheDocument();
    expect(screen.getByText(/invented examples · no live listings/i)).toBeInTheDocument();
    expect(screen.getAllByRole("article").length).toBeGreaterThan(5);
  });

  it("updates search and category results with keyboard-operable controls", async () => {
    const user = userEvent.setup();
    render(<DiscoveryCatalog />);

    const search = screen.getByRole("searchbox", { name: /search synthetic electronics/i });
    await user.type(search, "usb-c");
    await user.click(screen.getByRole("button", { name: /accessories/i }));

    expect(screen.getByText(/results/i)).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("article")
        .every((article) => within(article).getByText("Accessory", { exact: true })),
    ).toBe(true);
  });

  it("shows a clear empty-search message", async () => {
    const user = userEvent.setup();
    render(<DiscoveryCatalog />);
    await user.type(
      screen.getByRole("searchbox", { name: /search synthetic electronics/i }),
      "missing device",
    );

    expect(screen.getByRole("status")).toHaveTextContent(/no products match/i);
  });

  it("links cards to product details and displays unavailable values honestly", () => {
    const product = catalog.find((item) => Object.values(item.specifications).includes(null));
    if (!product) throw new Error("The synthetic fixture must include missing specifications.");

    render(<ProductDetail product={product} similarProducts={getSimilarProducts(product.id)} />);

    expect(
      screen.getByRole("heading", { level: 1, name: product.name ?? /title unavailable/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/not available in this synthetic fixture/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /similar synthetic products/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/customer reviews|star rating|buy now|in stock/i),
    ).not.toBeInTheDocument();
  });
});
