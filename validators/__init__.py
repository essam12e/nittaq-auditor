"""Validator registry. Register new platforms here (see core/services.py)."""

from __future__ import annotations

from validators.base import BaseValidator
from validators.ga4.validator import GA4Validator
from validators.google_ads.validator import GoogleAdsValidator
from validators.gtm.validator import GTMValidator
from validators.merchant.validator import MerchantValidator
from validators.meta.validator import MetaValidator
from validators.snapchat.validator import SnapchatValidator
from validators.tiktok.validator import TikTokValidator

TRACKING_VALIDATORS: dict[str, type[BaseValidator]] = {
    "ga4": GA4Validator,
    "gtm": GTMValidator,
    "google_ads": GoogleAdsValidator,
    "meta": MetaValidator,
    "tiktok": TikTokValidator,
    "snapchat": SnapchatValidator,
}

__all__ = ["TRACKING_VALIDATORS", "MerchantValidator", "BaseValidator"]
