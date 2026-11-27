"""Read-only, deterministic synthetic electronics catalog and user contexts."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from recfusion_core.contracts import (
    DataSplit,
    Interaction,
    Money,
    SyntheticProduct,
    SyntheticUserContext,
)

SYNTHETIC_CATALOG_ID = "synthetic-electronics-v1"
SYNTHETIC_CATALOG_SCHEMA = "recfusion.synthetic-catalog.v1"
SYNTHETIC_GENERATOR_SCHEMA = "recfusion.synthetic-electronics-generator.v1"
SYNTHETIC_GENERATOR_SEED = 44_041
MAX_SYNTHETIC_CATALOG_SIZE = 50_000
MAX_SYNTHETIC_HISTORY_EVENTS = 1_000


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _item_id(number: int) -> str:
    return f"{SYNTHETIC_CATALOG_ID}:item:{number:06d}"


def _user_id(number: int) -> str:
    return f"{SYNTHETIC_CATALOG_ID}:user:{number:06d}"


def _product(
    number: int,
    *,
    title: str | None,
    category: str | None,
    description: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
    price_usd: str | None = None,
    catalog_eligible: bool = True,
    visible: bool = True,
    seed: int,
) -> SyntheticProduct:
    identity = _item_id(number)
    fingerprint = _sha256(
        _canonical_bytes(
            {
                "catalog_id": SYNTHETIC_CATALOG_ID,
                "seed": seed,
                "item_key": identity,
                "title": title,
                "category": category,
                "description": description,
                "features": features,
                "price_usd": price_usd,
                "catalog_eligible": catalog_eligible,
                "visible": visible,
            }
        )
    )
    return SyntheticProduct(
        item_key=identity,
        title=title,
        category=category,
        description=description,
        features=features,
        price=Money(Decimal(price_usd), "USD") if price_usd else None,
        source_record_fingerprint=fingerprint,
        catalog_eligible=catalog_eligible,
        visible=visible,
    )


def _interaction(
    user_number: int, item_number: int, timestamp: int, rating: str
) -> Interaction:
    user_key = _user_id(user_number)
    item_key = _item_id(item_number)
    fingerprint = _sha256(
        _canonical_bytes(
            {
                "user_key": user_key,
                "item_key": item_key,
                "event_time_ms": timestamp,
                "rating": rating,
                "split": DataSplit.TRAIN.value,
            }
        )
    )
    return Interaction(
        user_key=user_key,
        item_key=item_key,
        event_time_ms=timestamp,
        rating=Decimal(rating),
        split=DataSplit.TRAIN,
        source_event_fingerprint=fingerprint,
    )


@dataclass(frozen=True, slots=True)
class SyntheticCatalogProvider:
    catalog_id: str
    version: str
    seed: int
    generator_schema: str
    catalog_fingerprint: str
    bundle_fingerprint: str
    max_catalog_size: int
    max_history_events: int
    _products: tuple[SyntheticProduct, ...]
    _products_by_id: Mapping[str, SyntheticProduct]
    _contexts: Mapping[str, SyntheticUserContext]
    _training_interactions: tuple[Interaction, ...]
    _collaborative_rankings: Mapping[str, Mapping[str, tuple[str, ...]]]

    def __post_init__(self) -> None:
        if len(self._products) > self.max_catalog_size:
            raise ValueError("Synthetic catalog exceeds the configured bound.")
        if len(self._products_by_id) != len(self._products):
            raise ValueError("Synthetic catalog contains duplicate product IDs.")
        if any(
            len(context.training_history) > self.max_history_events
            for context in self._contexts.values()
        ):
            raise ValueError("Synthetic user history exceeds the configured bound.")
        if any(
            event.split is not DataSplit.TRAIN for event in self._training_interactions
        ):
            raise ValueError(
                "Synthetic inference catalog may contain train events only."
            )

    def list_products(self) -> tuple[SyntheticProduct, ...]:
        return self._products

    def get_product(self, item_key: str) -> SyntheticProduct | None:
        return self._products_by_id.get(item_key)

    def get_user_context(self, user_key: str) -> SyntheticUserContext:
        context = self._contexts.get(user_key)
        if context is None:
            raise KeyError("Unknown synthetic user.")
        return context

    def get_training_interactions(self) -> tuple[Interaction, ...]:
        return self._training_interactions

    @property
    def train_known_item_keys(self) -> frozenset[str]:
        return frozenset(event.item_key for event in self._training_interactions)

    def get_collaborative_rankings(
        self, user_key: str
    ) -> Mapping[str, tuple[str, ...]]:
        rankings = self._collaborative_rankings.get(user_key)
        if rankings is None:
            raise KeyError("Synthetic collaborative source is unavailable.")
        return rankings


def build_synthetic_catalog(
    *, seed: int = SYNTHETIC_GENERATOR_SEED
) -> SyntheticCatalogProvider:
    """Prepare a small invented catalog; this never reads external files."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Synthetic generator seed must be a non-negative integer.")
    rng = random.Random(seed)
    product_rows = [
        _product(
            1,
            title="Synthetic laptop 16GB RAM 512GB SSD",
            category="laptop",
            description=("invented electronics catalog example",),
            features=("16GB memory", "512GB SSD", "USB-C"),
            price_usd="999.99",
            seed=seed,
        ),
        _product(
            2,
            title="Synthetic laptop 8GB RAM 256GB SSD",
            category="laptop",
            description=("invented portable computer example",),
            features=("8GB memory", "256GB SSD", "USB-C"),
            price_usd="699.99",
            seed=seed,
        ),
        _product(
            3,
            title="Synthetic smartphone OLED 128GB",
            category="smartphone",
            description=("invented mobile device example",),
            features=("OLED display", "128GB storage", "USB-C"),
            price_usd="499.99",
            seed=seed,
        ),
        _product(
            4,
            title="Synthetic wireless headphones",
            category="audio",
            description=("invented listening device example",),
            features=("wireless audio", "over-ear", "USB-C"),
            price_usd="149.99",
            seed=seed,
        ),
        _product(
            5,
            title="Synthetic desktop monitor 27 inch",
            category="monitor",
            description=("invented display example",),
            features=("27 inch display", "USB-C", "high refresh"),
            price_usd="349.99",
            seed=seed,
        ),
        _product(
            6,
            title="Synthetic laptop 16GB RAM 1TB SSD",
            category="laptop",
            description=("invented portable computer example",),
            features=("16GB memory", "1TB SSD", "USB-C"),
            price_usd="1299.99",
            seed=seed,
        ),
        _product(
            7,
            title="Synthetic wireless earbuds USB-C",
            category="audio",
            description=("invented listening device example",),
            features=("wireless audio", "in-ear", "USB-C"),
            price_usd="89.99",
            seed=seed,
        ),
        _product(
            8,
            title=None,
            category=None,
            price_usd=None,
            seed=seed,
        ),
        _product(
            9,
            title="Synthetic conflicted product",
            category="laptop",
            description=("invented conflict fixture",),
            features=("conflicting metadata fixture",),
            price_usd="100.00",
            catalog_eligible=False,
            seed=seed,
        ),
        _product(
            10,
            title="Synthetic hidden product",
            category="accessory",
            description=("invented visibility fixture",),
            features=("hidden catalog fixture",),
            price_usd="25.00",
            visible=False,
            seed=seed,
        ),
    ]
    rng.shuffle(product_rows)
    products = tuple(sorted(product_rows, key=lambda product: product.item_key))
    products_by_id = MappingProxyType(
        {product.item_key: product for product in products}
    )

    all_events = tuple(
        sorted(
            (
                _interaction(1, 1, 1_000, "5"),
                _interaction(1, 2, 2_000, "2"),
                _interaction(1, 3, 3_000, "5"),
                _interaction(2, 4, 1_100, "5"),
                _interaction(2, 5, 1_900, "3"),
            ),
            key=lambda event: (
                event.event_time_ms,
                event.user_key,
                event.item_key,
                event.source_event_fingerprint,
            ),
        )
    )
    prediction_times = {1: 2_000, 2: 2_500, 3: 1_000}
    contexts = MappingProxyType(
        {
            _user_id(number): SyntheticUserContext(
                user_key=_user_id(number),
                prediction_time_ms=prediction_times[number],
                training_history=tuple(
                    event for event in all_events if event.user_key == _user_id(number)
                ),
            )
            for number in prediction_times
        }
    )
    collaborative_rankings = MappingProxyType(
        {
            _user_id(1): MappingProxyType(
                {
                    "synthetic_item_cf": (
                        _item_id(6),
                        _item_id(4),
                        _item_id(2),
                        _item_id(5),
                    ),
                    "synthetic_bpr_control": (_item_id(5), _item_id(3), _item_id(1)),
                }
            ),
            _user_id(2): MappingProxyType(
                {
                    "synthetic_item_cf": (_item_id(3), _item_id(1), _item_id(5)),
                    "synthetic_bpr_control": (_item_id(2), _item_id(4), _item_id(1)),
                }
            ),
            _user_id(3): MappingProxyType(
                {
                    "synthetic_item_cf": (_item_id(4), _item_id(1), _item_id(2)),
                    "synthetic_bpr_control": (_item_id(5), _item_id(3), _item_id(2)),
                }
            ),
        }
    )

    product_records = [
        {
            "item_key": product.item_key,
            "title": product.title,
            "category": product.category,
            "description": product.description,
            "features": product.features,
            "price": (
                [str(product.price.amount), product.price.currency]
                if product.price is not None
                else None
            ),
            "catalog_eligible": product.catalog_eligible,
            "visible": product.visible,
            "fingerprint": product.source_record_fingerprint,
        }
        for product in products
    ]
    catalog_fingerprint = _sha256(_canonical_bytes(product_records))
    bundle_records = {
        "schema_version": SYNTHETIC_CATALOG_SCHEMA,
        "generator_schema": SYNTHETIC_GENERATOR_SCHEMA,
        "catalog_id": SYNTHETIC_CATALOG_ID,
        "version": "1",
        "seed": seed,
        "catalog_fingerprint": catalog_fingerprint,
        "training_interactions": [
            {
                "user_key": event.user_key,
                "item_key": event.item_key,
                "event_time_ms": event.event_time_ms,
                "rating": str(event.rating),
                "fingerprint": event.source_event_fingerprint,
            }
            for event in all_events
        ],
        "collaborative_rankings": {
            user: {source: items for source, items in sources.items()}
            for user, sources in collaborative_rankings.items()
        },
    }
    bundle_fingerprint = _sha256(_canonical_bytes(bundle_records))
    return SyntheticCatalogProvider(
        catalog_id=SYNTHETIC_CATALOG_ID,
        version="1",
        seed=seed,
        generator_schema=SYNTHETIC_GENERATOR_SCHEMA,
        catalog_fingerprint=catalog_fingerprint,
        bundle_fingerprint=bundle_fingerprint,
        max_catalog_size=MAX_SYNTHETIC_CATALOG_SIZE,
        max_history_events=MAX_SYNTHETIC_HISTORY_EVENTS,
        _products=products,
        _products_by_id=products_by_id,
        _contexts=contexts,
        _training_interactions=all_events,
        _collaborative_rankings=collaborative_rankings,
    )
