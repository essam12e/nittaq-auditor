"""Interpret the user's Arabic (or English) reply to an approval request.

Principle: when in doubt, ask. Anything that is not a clear, scoped yes is
either a refusal or a request for clarification - never an execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.approval.proposals import Proposal
from core.invocation import detect_services, normalize_ar
from core.services import GROUP_WORDS

APPROVE = "approve"
REJECT = "reject"
AMBIGUOUS = "ambiguous"
MIXED = "mixed"  # some approved, some rejected, all explicit

_POS = (
    "نعم", "ايوه", "ايوا", "اي نعم", "اوافق", "موافق", "موافقه", "وافقت", "تمام", "نفذ", "نفذها", "ابدا", "ابدء",
    "اعتمد", "اكيد", "طيب", "توكل", "اشتغل", "كمل", "yes", "ok", "okay", "approve", "approved", "go ahead", "proceed", "sure",
)
_NEG = (
    "لا", "لأ", "لاء", "ما اوافق", "لا اوافق", "مو موافق", "غير موافق", "ارفض", "رفض", "رافض", "توقف", "وقف", "الغ", "الغاء",
    "لا تنفذ", "لا تلمس", "لا تعدل", "لا تغير", "بدون", "no", "stop", "cancel", "reject", "don't", "dont", "do not",
)
_UNSURE = (
    "ربما", "يمكن", "مدري", "ما ادري", "لا ادري", "لاحقا", "بعدين", "خلني افكر", "افكر", "مو متاكد", "غير متاكد", "مش متاكد",
    "اشرح", "وضح", "ليش", "لماذا", "كيف", "maybe", "later", "not sure", "explain", "why",
)
_ALL = ("الكل", "كلها", "كله", "جميع", "جميعها", "all", "everything", "كل شي", "كل شيء", "كل الاصلاحات", "كل التغييرات")
_EXCEPT = ("ما عدا", "ماعدا", "الا", "باستثناء", "عدا", "except", "but not")

_CLAUSE_SPLIT = re.compile(r"[,،؛;.!\n]| لكن | بس | اما | ولكن | but ")
_PID = re.compile(r"\b([PpMm])\s?(\d{1,3})\b")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    for w in words:
        wn = normalize_ar(w)
        if re.search(rf"(?<![\w]){re.escape(wn)}(?![\w])", text):
            return True
    return False


@dataclass
class ApprovalDecision:
    kind: str
    approved: list[str] = field(default_factory=list)  # proposal ids
    rejected: list[str] = field(default_factory=list)
    needs_destructive_confirmation: list[str] = field(default_factory=list)
    reason: str | None = None  # machine code for the clarification message


def _polarity(clause: str) -> str | None:
    unsure = _has_word(clause, _UNSURE) or "?" in clause or "؟" in clause
    neg = _has_word(clause, _NEG)
    pos = _has_word(clause, _POS)
    if unsure:
        return AMBIGUOUS
    if re.search(r"(لا|ما) (مانع|مشكله|عندي مانع)", clause) and not re.search(r"لا (تنفذ|تلمس|تعدل|تغير)", clause):
        return APPROVE  # "لا مانع" = no objection
    if neg and not pos:
        return REJECT
    if pos and not neg:
        return APPROVE
    if pos and neg:
        return AMBIGUOUS
    return None


def _ids_in(clause: str, offer: list[Proposal]) -> set[str]:
    ids = {p.id for p in offer}
    found = {f"{m.group(1).upper()}{int(m.group(2))}" for m in _PID.finditer(clause.translate(_AR_DIGITS))}
    return found & ids


def parse_approval(text: str, offer: list[Proposal]) -> ApprovalDecision:
    if not offer:
        return ApprovalDecision(AMBIGUOUS, reason="nothing_pending")
    raw = text.translate(_AR_DIGITS)
    norm = normalize_ar(raw)
    if not norm:
        return ApprovalDecision(AMBIGUOUS, reason="empty")

    approved: set[str] = set()
    rejected: set[str] = set()
    general: list[str] = []  # polarities of clauses without explicit scope
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(f" {norm} ") if c.strip()]
    for clause in clauses:
        pol = _polarity(clause)
        if pol == AMBIGUOUS:
            return ApprovalDecision(AMBIGUOUS, reason="uncertain_reply")
        services, merchant = detect_services(clause, expand_groups=False)
        scoped_ids = _ids_in(clause, offer)
        group_only = not services and not scoped_ids and (
            _has_word(clause, GROUP_WORDS["google"]) or _has_word(clause, GROUP_WORDS["pixels"])
        )
        if group_only and pol:
            return ApprovalDecision(AMBIGUOUS, reason="group_scope")
        if merchant and not any(p.merchant for p in offer):
            return ApprovalDecision(AMBIGUOUS, reason="merchant_not_in_offer")
        if services:
            scoped_ids |= {p.id for p in offer if p.service in services}
            if not scoped_ids:
                return ApprovalDecision(AMBIGUOUS, reason="service_not_in_offer")
        except_match = next((w for w in _EXCEPT if normalize_ar(w) in clause), None)
        if except_match and pol == APPROVE:
            head, _, tail = clause.partition(normalize_ar(except_match))
            t_services, _ = detect_services(tail, expand_groups=False)
            excluded = _ids_in(tail, offer) | {p.id for p in offer if p.service in t_services}
            if not excluded:
                return ApprovalDecision(AMBIGUOUS, reason="unclear_exception")
            approved |= {p.id for p in offer} - excluded
            rejected |= excluded
            continue
        if pol is None:
            if scoped_ids:
                # scope without polarity ("GA4 و Meta") - polarity may come from another clause
                general.append("scope:" + ",".join(sorted(scoped_ids)))
            continue
        if scoped_ids:
            (approved if pol == APPROVE else rejected).update(scoped_ids)
        elif _has_word(clause, _ALL) or pol == REJECT:
            (approved if pol == APPROVE else rejected).update(p.id for p in offer)
        else:
            general.append(pol)

    # Scope-only clauses combined with a single general polarity ("GA4 و Meta، موافق").
    pending_scopes = [g for g in general if g.startswith("scope:")]
    pols = [g for g in general if not g.startswith("scope:")]
    if pending_scopes:
        if len(set(pols)) != 1:
            return ApprovalDecision(AMBIGUOUS, reason="scope_without_decision")
        ids = {i for g in pending_scopes for i in g[6:].split(",")}
        (approved if pols[0] == APPROVE else rejected).update(ids)
    elif pols:
        if len(set(pols)) != 1:
            return ApprovalDecision(AMBIGUOUS, reason="conflicting_reply")
        if not approved and not rejected:
            # A plain "yes"/"no" answers exactly the set that was asked about.
            (approved if pols[0] == APPROVE else rejected).update(p.id for p in offer)
        elif pols[0] == APPROVE and rejected and not approved:
            return ApprovalDecision(AMBIGUOUS, reason="conflicting_reply")

    if approved & rejected:
        return ApprovalDecision(AMBIGUOUS, reason="conflicting_reply")
    if not approved and not rejected:
        return ApprovalDecision(AMBIGUOUS, reason="no_decision")

    order = [p.id for p in offer]
    appr = [i for i in order if i in approved]
    rej = [i for i in order if i in rejected]
    destructive = [p.id for p in offer if p.id in approved and p.destructive]
    kind = APPROVE if appr and not rej else REJECT if rej and not appr else MIXED
    return ApprovalDecision(kind, appr, rej, destructive)


def parse_yes_no(text: str) -> str:
    """For unscoped questions (e.g. "start Merchant inspection?"): approve/reject/ambiguous."""
    norm = normalize_ar(text.translate(_AR_DIGITS))
    pol = _polarity(norm) if norm else None
    return pol or AMBIGUOUS
