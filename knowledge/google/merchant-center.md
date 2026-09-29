# Google Merchant Center

| Field | Value |
|---|---|
| Sources | https://support.google.com/merchants/answer/7052112 (product data specification) · https://support.google.com/merchants/answer/6098334 |
| Date checked | 2026-09-29 (web search excerpts) |
| Validator | `validators/merchant/validator.py` |
| Workflow | `workflows/merchant.md` (separate, last, two approvals) |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `merchant.required_attributes` | required attributes (id, title, link, image_link, availability, price, identifiers where applicable) or the product can't serve | confirmed |
| `merchant.landing_page_match` | Google crawls landing pages / structured data and flags mismatched price or availability ("Mismatched value (page crawl)") | unconfirmed (official article text not readable) |

## Root-cause mapping used in reports
| Issue category | Where the fix usually belongs |
|---|---|
| price / availability mismatch | Salla product data or feed sync (variant URLs, structured data) |
| landing page not working | Salla store (product page) |
| identifiers (GTIN/MPN/brand) | Salla product data |
| shipping | Merchant Center settings |
| policy / misrepresentation | Merchant Center review |

Never assume a Merchant problem is fixable inside Merchant Center. Product re-review by Google can take time;
the engine reports `unable_to_verify` until statuses update.
