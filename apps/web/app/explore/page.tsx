import type { Metadata } from "next";
import { RecommendationExplorer } from "@/features/recommendations/RecommendationExplorer";

export const metadata: Metadata = {
  title: "Recommendation Lab — RecFusion",
};

export default function ExplorePage() {
  return (
    <main className="page-shell explore-page" id="main-content">
      <div className="page-intro">
        <p className="eyebrow">A transparent demo environment</p>
        <h1>
          Recommendation lab<span className="brand__period">.</span>
        </h1>
        <p>
          Choose a synthetic context to inspect how the versioned recommendation contract is
          presented. Results come from fixed fixtures; no model runs in your browser.
        </p>
      </div>
      <div className="explorer-callout" role="note">
        <span aria-hidden="true">✳</span>
        <p>
          <strong>Fixture-backed until API integration.</strong> No HTTP request is made. Synthetic
          user histories stay inside the provider and are never displayed.
        </p>
      </div>
      <RecommendationExplorer />
    </main>
  );
}
