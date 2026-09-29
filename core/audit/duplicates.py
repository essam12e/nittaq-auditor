"""Cross-platform / cross-implementation duplicate & conflict detection.

Same-platform duplicate hits are detected by each validator. This engine
looks *across* implementations and platforms. It never removes anything; it
only reports with evidence.
"""

from __future__ import annotations

from collections import defaultdict

from core.discovery.observation import AuditContext
from core.models import Certainty, Evidence, EvidenceSource, Finding, Severity

PURCHASE_NAMES = {"ga4": ("purchase",), "meta": ("Purchase",), "tiktok": ("Purchase", "CompletePayment"), "snapchat": ("PURCHASE",)}
VALUE_KEY = {"ga4": "value", "meta": "value", "tiktok": "value", "snapchat": "price"}


def detect_cross_platform(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []

    # GA4 configured directly (gtag.js?id=G-) while a GTM container is also present,
    # and the same property got >1 page_view in one page load.
    direct = {ld.tracking_id for ld in ctx.loaders_for("ga4") if ld.tracking_id}
    gtm_ids = ctx.ids_for("gtm")
    if direct and gtm_ids:
        pv: dict[tuple[str | None, int | None], int] = defaultdict(int)
        for e in ctx.events_for("ga4"):
            if e.name == "page_view":
                pv[(e.tracking_id, e.page_load_id)] += 1
        dup_ids = sorted({str(t) for (t, _), n in pv.items() if n > 1 and t in direct})
        if dup_ids:
            out.append(
                Finding(
                    "cross_platform",
                    "ga4_direct_and_gtm",
                    Severity.HIGH,
                    Certainty.INFERRED,
                    [Evidence(EvidenceSource.NETWORK, f"gtag.js loads {dup_ids} directly, GTM {sorted(gtm_ids)} present, duplicate page_view observed")],
                    params={"ids": dup_ids, "containers": sorted(gtm_ids)},
                    recommended_action="ga4.fix_duplicate_events",
                )
            )

    # Meta: same pixel config loaded more than once in a page load.
    cfg: dict[tuple[str | None, int | None], int] = defaultdict(int)
    for ld in ctx.loaders_for("meta"):
        if ld.tracking_id and ld.source == EvidenceSource.NETWORK:
            cfg[(ld.tracking_id, ld.page_load_id)] += 1
    for (pid, _pl), n in cfg.items():
        if n > 1:
            out.append(
                Finding("cross_platform", "meta_pixel_loaded_twice", Severity.MEDIUM, Certainty.INFERRED,
                        [Evidence(EvidenceSource.NETWORK, f"pixel {pid} configuration requested {n} times in one page load")],
                        params={"pixel": pid, "count": n}, recommended_action="meta.fix_duplicate_events")
            )
            break

    # Purchase value / currency consistency across platforms in the same page load.
    by_load: dict[int | None, dict[str, tuple[float | None, str | None]]] = defaultdict(dict)
    for platform, names in PURCHASE_NAMES.items():
        for e in ctx.events_for(platform):
            if e.name in names:
                v = e.params.get(VALUE_KEY[platform])
                by_load[e.page_load_id][platform] = (
                    float(v) if isinstance(v, (int, float)) else None,
                    str(e.params.get("currency")) if e.params.get("currency") else None,
                )
    for _pl, per in by_load.items():
        if len(per) < 2:
            continue
        values = {p: v for p, (v, _c) in per.items() if v is not None}
        currencies = {p: c for p, (_v, c) in per.items() if c}
        if len(set(currencies.values())) > 1:
            out.append(Finding("cross_platform", "cross_platform_currency_mismatch", Severity.HIGH, Certainty.OBSERVED,
                               [Evidence(EvidenceSource.NETWORK, f"purchase currency per platform: {currencies}")],
                               params={"currencies": currencies}))
        if values:
            lo, hi = min(values.values()), max(values.values())
            if hi > 0 and (hi - lo) / hi > 0.01:
                out.append(Finding("cross_platform", "cross_platform_value_mismatch", Severity.MEDIUM, Certainty.OBSERVED,
                                   [Evidence(EvidenceSource.NETWORK, f"purchase value per platform: {values}")],
                                   params={"values": values}))
    return out
