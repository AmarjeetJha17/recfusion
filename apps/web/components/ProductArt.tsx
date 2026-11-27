import type { ProductCategory } from "@/lib/catalog";

const artLabels: Record<ProductCategory, string> = {
  laptop: "Laptop illustration",
  headphones: "Headphones illustration",
  smartphone: "Smartphone illustration",
  monitor: "Monitor illustration",
  accessory: "Accessory illustration",
};

export function ProductArt({ category }: { category: ProductCategory }) {
  return (
    <div className={`product-art product-art--${category}`} aria-hidden="true">
      <svg viewBox="0 0 240 160" fill="none" role="img" aria-label={artLabels[category]}>
        {category === "laptop" && (
          <>
            <rect x="62" y="24" width="116" height="82" rx="5" className="art-device" />
            <rect x="69" y="31" width="102" height="67" rx="2" className="art-screen" />
            <path d="M48 116h144l-12 12H60l-12-12Z" className="art-base" />
            <path d="M102 117h36" className="art-detail" />
          </>
        )}
        {category === "smartphone" && (
          <>
            <rect x="88" y="13" width="64" height="134" rx="13" className="art-device" />
            <rect x="94" y="23" width="52" height="111" rx="8" className="art-screen" />
            <circle cx="120" cy="140" r="2" className="art-detail-fill" />
          </>
        )}
        {category === "headphones" && (
          <>
            <path d="M61 91V75a59 59 0 0 1 118 0v16" className="art-outline" />
            <rect x="49" y="78" width="32" height="55" rx="14" className="art-device" />
            <rect x="159" y="78" width="32" height="55" rx="14" className="art-device" />
            <path d="M65 91v28M175 91v28" className="art-detail" />
          </>
        )}
        {category === "monitor" && (
          <>
            <rect x="40" y="24" width="160" height="91" rx="5" className="art-device" />
            <rect x="48" y="32" width="144" height="75" rx="2" className="art-screen" />
            <path d="M120 115v20m-29 5h58" className="art-detail" />
          </>
        )}
        {category === "accessory" && (
          <>
            <rect x="63" y="45" width="114" height="68" rx="12" className="art-device" />
            <path d="M83 66h74M83 81h74M83 96h45" className="art-detail" />
            <circle cx="151" cy="96" r="3" className="art-detail-fill" />
          </>
        )}
      </svg>
      <span className="sr-only">{artLabels[category]}</span>
    </div>
  );
}
