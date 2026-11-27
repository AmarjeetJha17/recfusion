import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProductDetail } from "@/components/ProductDetail";
import { catalog, getProductByRouteId, getProductRouteId, getSimilarProducts } from "@/lib/catalog";

export const metadata: Metadata = { title: "Synthetic Product — RecFusion" };

export function generateStaticParams() {
  return catalog.map((product) => ({ id: getProductRouteId(product) }));
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = getProductByRouteId(id);
  if (!product) notFound();
  return <ProductDetail product={product} similarProducts={getSimilarProducts(product.id)} />;
}
