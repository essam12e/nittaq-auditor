"""Service registry.

Adding a platform = add a ServiceInfo entry here, a validator package under
``validators/`` registered in ``validators/__init__.py``, knowledge rules in
``knowledge/rules.json`` and Arabic strings in ``reports/templates``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceInfo:
    id: str
    display_name: str  # shown to users (brand names stay in English)
    aliases: tuple[str, ...]  # words users may type (Arabic + English), lowercase
    order: int  # required processing order
    group: str  # "google" | "social" | "merchant"
    sensitive: bool = False  # separate approval workflow (Merchant Center)


SERVICES: tuple[ServiceInfo, ...] = (
    ServiceInfo(
        "ga4",
        "Google Analytics 4",
        ("ga4", "google analytics", "analytics", "جوجل أناليتكس", "جوجل انالتكس", "أناليتكس", "انالتكس", "التحليلات"),
        1,
        "google",
    ),
    ServiceInfo(
        "gtm",
        "Google Tag Manager",
        ("gtm", "tag manager", "google tag manager", "تاغ مانجر", "تاج مانجر", "مدير العلامات"),
        2,
        "google",
    ),
    ServiceInfo(
        "google_ads",
        "Google Ads",
        ("google ads", "adwords", "جوجل ادز", "جوجل آدز", "إعلانات جوجل", "اعلانات جوجل"),
        3,
        "google",
    ),
    ServiceInfo(
        "meta",
        "Meta Pixel",
        ("meta", "facebook", "fb", "instagram", "ميتا", "فيسبوك", "فيس بوك", "انستقرام", "إنستغرام"),
        4,
        "social",
    ),
    ServiceInfo(
        "tiktok",
        "TikTok Pixel",
        ("tiktok", "tik tok", "تيك توك", "تيكتوك"),
        5,
        "social",
    ),
    ServiceInfo(
        "snapchat",
        "Snapchat Pixel",
        ("snapchat", "snap", "سناب", "سناب شات", "سنابشات"),
        6,
        "social",
    ),
    ServiceInfo(
        "merchant",
        "Google Merchant Center",
        ("merchant", "merchant center", "gmc", "ميرشنت", "مرشنت", "ميرتشنت", "جوجل ميرشنت"),
        9,
        "merchant",
        sensitive=True,
    ),
)

SERVICE_BY_ID: dict[str, ServiceInfo] = {s.id: s for s in SERVICES}

# Tracking services audited in the main pass (Merchant is always separate & last).
TRACKING_SERVICE_IDS: tuple[str, ...] = tuple(
    s.id for s in sorted(SERVICES, key=lambda s: s.order) if not s.sensitive
)
GOOGLE_TRACKING_IDS: tuple[str, ...] = ("ga4", "gtm", "google_ads")

# Words that refer to a group rather than one service ("جوجل" = several services).
GROUP_WORDS: dict[str, tuple[str, ...]] = {
    "google": ("جوجل", "قوقل", "google"),
    "pixels": ("البيكسلات", "البكسلات", "البيكسل", "بيكسل", "pixels", "pixel"),
}


def display_name(service_id: str) -> str:
    return SERVICE_BY_ID[service_id].display_name


def ordered(service_ids: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    return sorted(set(service_ids), key=lambda s: SERVICE_BY_ID[s].order)
