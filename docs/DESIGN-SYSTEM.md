# DESIGN-SYSTEM — RecFusion UX foundations

**Status:** Proposed visual and interaction direction. Tokens are initial design candidates, not a final brand kit.

## 1. Product experience principles

- **Useful first:** product attributes and explanations must be readable and actionable.
- **Transparent:** label `Historical data`, `Synthetic demo`, or `Verified source (as of date)` on relevant product cards; never show an unsupported “in stock”.
- **Constraint-visible:** category, budget and hard specs are always visible and editable.
- **Trustworthy:** missing product data shown as “Not available”, not invented placeholders.
- **Accessible:** keyboard navigation, meaningful labels, sufficient contrast and screen-reader state announcements.

## 2. Visual direction

Clean modern electronics marketplace; light by default with user-selectable dark mode. High information density where comparing specs, generous whitespace on discovery pages. Do not sacrifice legibility for AI animations.

### Proposed color tokens

| Token | Light | Dark | Purpose |
|---|---|---|---|
| `--background` | `#F8FAFC` | `#0B1220` | app background |
| `--surface` | `#FFFFFF` | `#111C2D` | cards/dialogs |
| `--text` | `#0F172A` | `#E7EEF8` | primary text |
| `--text-muted` | `#475569` | `#AAB8CE` | secondary text |
| `--primary` | `#1D4ED8` | `#60A5FA` | primary actions |
| `--success` | `#15803D` | `#4ADE80` | confirmed positive states |
| `--danger` | `#B91C1C` | `#F87171` | errors |
| `--border` | `#CBD5E1` | `#334155` | dividers |

Validate contrast in implementation; adjust tokens if they fail WCAG AA for rendered text/control combinations. Do not communicate filter validity solely through color.

### Typography and space

- Font stack: `Inter, system-ui, -apple-system, Segoe UI, sans-serif` with graceful fallback; no bundled proprietary font files by default.
- Base text 16px; line height around 1.5; compact metadata 12–14px only if readable.
- Spacing scale: 4, 8, 12, 16, 24, 32, 48 px.
- Radius: 8px controls, 12px cards, 16px dialogs. Focus outlines visible in light/dark modes.

## 3. Core screens

1. Landing/discovery: intent search, popular categories, informed guest prompt.
2. Recommendations: ranked product cards, source/provenance tags, why-this-item, filter chips.
3. Product details: evidence-backed specs, provenance dates, related items, feedback.
4. Comparison: 2–4 selected products, structured table, missing-value indicators, differences.
5. Conversation: chat messages, applied constraint summary, product results, loading/failed tool states.
6. Preferences: inspect/change/remove saved preferences; consent controls.
7. ML Explorer: model/split selection, labeled observed metrics, baseline comparisons, no invented figures.

## 4. Component behavior

**ProductCard:** image (rights-cleared or fallback), title, core attributes, provenance, price/currency only if valid, save/dislike actions, “Why recommended?”. Avoid fake review stars/stock banners.

**BudgetInput:** explicit currency, validation, non-negative values, visible hard/soft distinction.

**RecommendationList:** loading skeleton, results count, strategy/fallback note, empty state with no automatic constraint relaxation.

**ChatPanel:** clear turn progress, cancellable request, bounded input, product citations/structured evidence, retry option.

**CompareTable:** accessible header associations, sticky attribute labels on smaller screens, `unknown` for missing information.

## 5. Accessibility and responsive requirements

Meet WCAG 2.2 AA as an implementation target: 44px-ish touch targets where practical, keyboard-accessible dialogs/menus, semantic headings, focus management, live-region updates for async results, proper error summaries, reduced-motion preference. Test 320px mobile width through desktop. Do not rely on auto-generated alt text for meaningful product specs.

## 6. Content and microcopy

Prefer “Based on your saved preferences” and “From our demonstration catalog” over “AI guarantees the best deal”. For prices use “Historical price” or “Demo price” where applicable, never “Current price” unless reliably sourced and timestamped. If nothing matches: “No products meet all required filters. You can change [specific filter] to see more options.”
