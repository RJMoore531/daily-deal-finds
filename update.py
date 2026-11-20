#!/usr/bin/env python3
"""Rebuild Daily Deal Finds from deals.json, optionally refreshing from public sources.

Daily command:
    python3 update.py

Refresh from public deal roundups, verify ASINs, then rebuild:
    python3 update.py --fetch

Check official Amazon clip coupons, promo codes, and Subscribe & Save
offers, then rebuild (sets coupon true only when a page clearly shows one):
    python3 update.py --check-coupons

This script never invents ASINs or prices. Product links are plain
https://www.amazon.com/dp/<ASIN>?tag=russmoore-20. Exact Amazon prices
and star ratings are not written to the page (no Product Advertising API).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEALS_PATH = ROOT / "deals.json"
INDEX_PATH = ROOT / "index.html"
STYLES_PATH = ROOT / "styles.css"

AFFILIATE_TAG = "russmoore-20"
ZONE = dt.timezone(dt.timedelta(hours=-5), name="ET")  # America/New_York standard; see label
SITE_NAME = "Daily Deal Finds"
SITE_URL = "https://rjmoore531.github.io/daily-deal-finds/"
OG_TITLE = "Black Friday Deals: My Top Picks Are Live! | Daily Deal Finds"
OG_DESCRIPTION = (
    "My top Black Friday picks are live! A family-friendly roundup of deals on "
    "toys, LEGO, tech, tools, home, and holiday gifts."
)
OG_IMAGE = SITE_URL + "og-image.png"
OG_IMAGE_ALT = (
    "Black Friday Deals: My Top Picks Are Live! Daily Deal Finds — "
    "toys, LEGO, tech, tools and more."
)
DISCLOSURE = "As an Amazon Associate I earn from qualifying purchases."

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ROUNDUP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

ASIN_RE = re.compile(
    r"https?://(?:www\.)?amazon\.com/(?:[^\"'\s<>]*?/)?(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})",
    re.I,
)
ASIN_ENC_RE = re.compile(r"(?:/dp/|%2Fdp%2F)([A-Z0-9]{10})", re.I)

# Public deal roundups and storefront-style lists. Add or remove as they change.
SOURCE_URLS = [
    "https://9to5toys.com/2026/11/17/amazon-updates-early-black-friday-new-deals/",
    "https://9to5toys.com/2026/11/17/amazon-new-fire-tv-stick-4k-black-friday-price-live/",
    "https://9to5toys.com/2026/11/10/lego-early-black-friday-star-wars-smart-play-pokemon/",
    "https://www.thebrickfan.com/lego-amazon-early-black-friday-2026-deals-live/",
    "https://www.goodhousekeeping.com/what-to-buy/sales-shopping-news/a74359564/early-black-friday-melissa-and-doug-toy-deals-2026/",
    "https://www.goodhousekeeping.com/what-to-buy/childrens-products/a74272502/amazon-toy-deals-early-black-friday-2026/",
    "https://the-gadgeteer.com/2026/11/16/amazons-early-black-friday-power-tool-deals-reach-61-off-led-by-dewalt-and-greenworks-kits/",
    "https://www.tomsguide.com/home/kitchen-dining/black-friday-thanksgiving-essential-appliance-deals-2026-16-11",
    "https://www.housebeautiful.com/shopping/best-stores/a74359363/amazon-black-friday-home-deals/",
    "https://www.bobvila.com/reviews/amazon-early-black-friday-christmas-trees-nov-2026/",
    "https://www.bargainhunter.com/amazon-black-friday-holiday-decor/",
]

# Keyword hints used only to drop obvious mismatches. Manual deals.json stays authoritative.
KIDS_HINTS = (
    "melissa", "doug", "lego", "play-doh", "play doh", "hot wheels", "paw patrol",
    "peppa", "crayola", "magnatiles", "magna-tiles", "fisher-price", "vtech",
    "leapfrog", "nintendo", "mario", "yoshi", "barbie", "nerf", "tonie",
    "educational insights", "microscope", "wooden", "toddler", "preschool",
)
LEGO_HINTS = ("lego",)
TECH_HINTS = (
    "airpods", "airtag", "macbook", "mac mini", "ipad", "apple watch", "sony",
    "bose", "fire tv", "echo", "kindle", "laptop", "headphones", "earbuds",
    "pixel", "asus", "ring battery", "ipad",
)
HOLIDAY_HINTS = (
    "advent", "christmas", "tree", "yankee", "holiday", "string light",
    "kitchenaid", "ninja", "cuisinart", "blanket", "stocking", "ornament",
    "wreath", "candle",
)

NOT_FOUND_MARKERS = (
    "Page Not Found",
    "Sorry! We couldn't find that page",
    "looking for isn't available",
    "Dogs of Amazon",
    "page could not be found",
)


def now_eastern() -> dt.datetime:
    """Wall-clock time in America/New_York, including DST when available."""
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.now(ZONE)


def format_updated(when: dt.datetime) -> str:
    # Example: Monday, November 16, 2026, 10:20 AM ET
    label = when.strftime("%A, %B ") + str(when.day) + when.strftime(", %Y, %-I:%M %p ")
    tzname = when.tzname() or "ET"
    if tzname in {"EST", "EDT", "ET"}:
        tzname = "ET"
    return label + tzname


def load_data() -> dict:
    data = json.loads(DEALS_PATH.read_text())
    data.setdefault("site_name", SITE_NAME)
    data.setdefault("affiliate_tag", AFFILIATE_TAG)
    data.setdefault("deals", [])
    data.setdefault(
        "sections",
        [
            {"id": "kids", "title": "Kids' Toys", "intro": ""},
            {"id": "lego", "title": "LEGO", "intro": ""},
            {"id": "tech", "title": "Tech", "intro": ""},
            {"id": "tools", "title": "Tools", "intro": ""},
            {"id": "bath", "title": "Toiletries & Bath", "intro": ""},
            {"id": "decor", "title": "Home Decor", "intro": ""},
            {"id": "kitchen", "title": "Kitchen & Small Appliances", "intro": ""},
            {"id": "holiday", "title": "Holiday Deals", "intro": ""},
        ],
    )
    return data


def save_data(data: dict) -> None:
    DEALS_PATH.write_text(json.dumps(data, indent=2) + "\n")


def product_url(asin: str, tag: str = AFFILIATE_TAG) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={tag}"


def fetch_url(url: str, ua: str = ROUNDUP_UA, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.status, raw.decode(charset, errors="ignore")
    except Exception as exc:
        print(f"  fetch failed {url}: {exc}", file=sys.stderr)
        return 0, ""


def extract_asins(text: str) -> list[str]:
    found = []
    seen = set()
    for pat in (ASIN_RE, ASIN_ENC_RE):
        for match in pat.finditer(text or ""):
            asin = match.group(1).upper()
            if re.fullmatch(r"[A-Z0-9]{10}", asin) and asin not in seen:
                seen.add(asin)
                found.append(asin)
    return found


def parse_amazon_title(page: str) -> str:
    product = re.search(r'id="productTitle"[^>]*>(.*?)</', page, re.I | re.S)
    if product:
        title = html.unescape(re.sub(r"\s+", " ", product.group(1))).strip()
        if title:
            return title
    title_tag = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    if not title_tag:
        return ""
    title = html.unescape(re.sub(r"\s+", " ", title_tag.group(1))).strip()
    title = re.sub(r"^Amazon\.com\s*:\s*", "", title)
    title = re.sub(
        r"\s*:\s*(Toys & Games|Electronics|Home & Kitchen|Amazon Devices(?: & Accessories)?|"
        r"Sports & Outdoors|Video Games|Patio, Lawn & Garden|Computers(?: & Accessories)?|"
        r"Cell Phones & Accessories|Tools & Home Improvement|Appliances|Pet Supplies|"
        r"Office Products|Grocery & Gourmet Food|Beauty & Personal Care|Health & Household|"
        r"Arts, Crafts & Sewing|Industrial & Scientific|Clothing, Shoes & Jewelry|"
        r"Movies & TV|CDs & Vinyl|Books|Handmade|Automotive|Software).*$",
        "",
        title,
        flags=re.I,
    )
    return title.strip(" |")


def page_is_missing(page: str) -> bool:
    low = page.lower()
    return any(marker.lower() in low for marker in NOT_FOUND_MARKERS)


def verify_asin(asin: str) -> dict:
    """Confirm a product page exists. Amazon often serves a small captcha to datacenter IPs."""
    url = f"https://www.amazon.com/dp/{asin}"
    status, page = fetch_url(url, ua=USER_AGENT, timeout=25)
    if not page:
        return {"asin": asin, "ok": False, "reason": "fetch_failed", "title": "", "bytes": 0}
    if page_is_missing(page):
        return {"asin": asin, "ok": False, "reason": "not_found", "title": "", "bytes": len(page)}
    if len(page) < 20000 and "captcha" in page.lower():
        return {"asin": asin, "ok": False, "reason": "captcha", "title": "", "bytes": len(page)}
    title = parse_amazon_title(page)
    if title and title not in {"Amazon.com", ""}:
        return {"asin": asin, "ok": True, "reason": "ok", "title": title, "bytes": len(page), "http": status}
    if len(page) > 50000:
        # Large product-like page without a clean title still counts as a live listing.
        return {"asin": asin, "ok": True, "reason": "ok_large", "title": title, "bytes": len(page), "http": status}
    return {"asin": asin, "ok": False, "reason": "captcha_or_unknown", "title": title, "bytes": len(page)}



BOT_MARKERS = (
    "validatecaptcha",
    "enter the characters you see",
    "sorry, we just need to make sure you're not a robot",
    "click the button below to continue shopping",
    "opfcaptcha",
    "/errors/validatecaptcha",
    "robot check",
)

# Visible, product-page wording only. Template strings like
# "Save {number,percent} with coupon" are ignored.
COUPON_VISIBLE_RE = re.compile(
    r"\bapply\s+(?:\$\s*)?\d+(?:\.\d+)?\s*%?\s+(?:off\s+)?coupon\b|"
    r"\bsave\s+(?:\$\s*)?\d+(?:\.\d+)?\s*%?\s+(?:off\s+)?(?:with\s+(?:a\s+)?)?coupon\b|"
    r"\bsave\s+(?:\$\s*)?\d+(?:\.\d+)?\s*%?\s+with\s+(?:a\s+)?promo(?:tional)?\s+code\b|"
    r"\bclip\s+(?:this\s+|the\s+)?coupon\b|"
    r"\byou(?:'ve| have)\s+clipped\s+(?:this\s+)?coupon\b|"
    r"\bsave\s+[^.]{0,40}\s+with\s+promo(?:tional)?\s+code\b",
    re.I,
)


def page_is_blocked(page: str, status: int) -> bool:
    """True when Amazon served a captcha or bot check instead of a product page."""
    if not page or status in {0, 403, 429, 503}:
        return True
    low = page.lower()
    has_title = 'id="producttitle"' in low or "id='producttitle'" in low
    if any(marker in low for marker in BOT_MARKERS):
        if not has_title:
            return True
        if "validatecaptcha" in low or "opfcaptcha" in low:
            return True
    if not has_title and len(page) < 20000 and "captcha" in low:
        return True
    return False


def visible_page_text(page: str) -> str:
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned)


# Buy-box / price-block IDs only. Sponsored carousels, reviews, and
# "similar items" widgets are excluded so another product's coupon is not
# attributed to this listing.
OFFER_FEATURE_IDS = (
    "buybox",
    "desktop_buybox",
    "apex_desktop",
    "corePriceDisplay_desktop_feature_div",
    "couponsInBuybox_feature_div",
    "promoPriceBlockMessage_feature_div",
    "promotionMessageInsideBuyBox_feature_div",
    "promoMessagingDiscountValue_feature_div",
)
OFFER_LIMITS = {
    "buybox": 120000,
    "desktop_buybox": 120000,
    "apex_desktop": 100000,
    "corePriceDisplay_desktop_feature_div": 50000,
}


def extract_offer_html(page: str) -> str:
    """HTML for this product's offer area, truncated before related widgets."""
    parts = []
    for elem_id in OFFER_FEATURE_IDS:
        match = re.search(rf'id="{re.escape(elem_id)}"', page, re.I)
        if not match:
            continue
        limit = OFFER_LIMITS.get(elem_id, 25000)
        chunk = page[match.start() : match.start() + limit]
        for stop in (
            'id="sp_detail',
            'id="reviewsMedley',
            'id="similarities',
            'id="purchase-sims',
            'id="rhf"',
            'id="discover-',
        ):
            idx = chunk.find(stop)
            if idx != -1:
                chunk = chunk[:idx]
        parts.append(chunk)
    return "\n".join(parts)


def has_official_coupon(page: str) -> tuple[bool, str]:
    """Return (found, reason) for an official Amazon coupon, promo, or S&S offer.

    Only this product's buy box and price block count. Global nav
    'Subscribe & Save' links, empty coupon widget shells, sponsored
    carousels, and reviews are ignored. Discount amounts are not returned.
    """
    offer = extract_offer_html(page)
    visible = visible_page_text(offer)
    for match in COUPON_VISIBLE_RE.finditer(visible):
        snippet = match.group(0)
        if "{" in snippet or "}" in snippet:
            continue
        kind = "promo" if "promo" in snippet.lower() else "coupon"
        return True, kind

    # Rendered Subscribe & Save row in this product's buy box. The same
    # string appears in unused JS layout lists on most pages; the rendered
    # widget carries data-feature-name.
    if re.search(
        r'data-feature-name="snsCaptionAndDiscountPillAbbreviated"',
        page,
        re.I,
    ):
        return True, "sns"

    widget = re.search(
        r'id="(?:vpcButton|couponBadge)"[^>]*>(.*?)</div>',
        offer,
        re.I | re.S,
    )
    if widget:
        inner = visible_page_text(widget.group(1))
        if re.search(r"\b(coupon|promo(?:tional)?\s+code)\b", inner, re.I) and "{" not in inner:
            return True, "coupon-widget"
    return False, ""


def check_deal_coupon(asin: str, retries: int = 1) -> dict:
    """Fetch a product page and look for an official coupon. Never invents a yes."""
    url = f"https://www.amazon.com/dp/{asin}"
    last = {"asin": asin, "coupon": False, "reason": "fetch_failed", "blocked": False}
    for attempt in range(retries + 1):
        status, page = fetch_url(url, ua=ROUNDUP_UA, timeout=30)
        if page_is_blocked(page, status):
            last = {
                "asin": asin,
                "coupon": False,
                "reason": "blocked",
                "blocked": True,
                "http": status,
                "bytes": len(page or ""),
            }
            if attempt < retries:
                time.sleep(8)
                continue
            return last
        found, why = has_official_coupon(page)
        return {
            "asin": asin,
            "coupon": found,
            "reason": why or "none",
            "blocked": False,
            "http": status,
            "bytes": len(page or ""),
        }
    return last


def check_coupons(data: dict, delay: float = 1.8) -> dict:
    """Set coupon true only when the live Amazon page shows an official offer.

    Leaves the field absent when no coupon is found, and unchanged (false/absent)
    when a page is blocked by a bot check.
    """
    summary = {"checked": 0, "blocked": 0, "found": 0, "items": []}
    total = len(data.get("deals") or [])
    for i, deal in enumerate(data["deals"], start=1):
        asin = deal.get("asin") or ""
        title = deal.get("title") or asin
        print(f"[{i}/{total}] {asin} {title[:60]}", flush=True)
        result = check_deal_coupon(asin)
        summary["checked"] += 1
        if result["blocked"]:
            summary["blocked"] += 1
            # Do not clear an existing true, and do not invent a false-positive.
            print(f"  blocked ({result.get('http')}, {result.get('bytes')} bytes)", flush=True)
        elif result["coupon"]:
            deal["coupon"] = True
            summary["found"] += 1
            summary["items"].append({"asin": asin, "title": title, "reason": result["reason"]})
            print(f"  coupon: {result['reason']}", flush=True)
        else:
            deal.pop("coupon", None)
            print("  no official coupon", flush=True)
        if i < total:
            time.sleep(delay)
    return summary


def guess_section(title: str) -> str | None:
    t = title.lower()
    if any(h in t for h in LEGO_HINTS) and ("advent" in t):
        return "holiday"
    if any(h in t for h in LEGO_HINTS):
        return "lego"
    if any(h in t for h in HOLIDAY_HINTS) and not any(h in t for h in TECH_HINTS):
        return "holiday"
    if any(h in t for h in TECH_HINTS):
        return "tech"
    if any(h in t for h in KIDS_HINTS):
        return "kids"
    return None


def fetch_new_deals(data: dict, limit_per_section: int = 15) -> tuple[int, int]:
    """Pull ASINs from public roundups, verify them, and add new ones to empty slots."""
    found: OrderedDict[str, str] = OrderedDict()
    for url in SOURCE_URLS:
        print(f"Fetching {url}")
        status, page = fetch_url(url)
        asins = extract_asins(page)
        print(f"  HTTP {status}, {len(asins)} ASINs")
        for asin in asins:
            found.setdefault(asin, url)

    existing = {d["asin"] for d in data["deals"]}
    added = 0
    dropped = 0
    # Verify existing deals; drop only clear 404s. Keep listings if Amazon serves a captcha.
    kept = []
    for deal in data["deals"]:
        result = verify_asin(deal["asin"])
        if result["reason"] == "not_found":
            print(f"  drop 404 {deal['asin']} {deal.get('title', '')}")
            dropped += 1
            continue
        if result["ok"] and result.get("title") and len(result["title"]) > 8:
            # Keep our curated short title; only fill if missing.
            deal.setdefault("verified_title", result["title"][:180])
        kept.append(deal)
        print(f"  keep {deal['asin']} ({result['reason']})")
    data["deals"] = kept

    counts = {s["id"]: sum(1 for d in data["deals"] if d["section"] == s["id"]) for s in data["sections"]}
    for asin, source in found.items():
        if asin in existing:
            continue
        if all(counts[s] >= limit_per_section for s in counts):
            break
        result = verify_asin(asin)
        if not result["ok"]:
            print(f"  skip {asin} ({result['reason']})")
            continue
        title = result["title"]
        section = guess_section(title)
        if not section or counts.get(section, 0) >= limit_per_section:
            print(f"  skip {asin} section={section}")
            continue
        data["deals"].append(
            {
                "asin": asin,
                "section": section,
                "title": title[:140],
                "blurb": "Found in a current public deal roundup. Check the live Amazon price before you buy.",
                "badge": "On sale now",
                "source": source,
            }
        )
        counts[section] += 1
        existing.add(asin)
        added += 1
        print(f"  add {section} {asin} {title[:80]}")
    return added, dropped


def render(data: dict) -> str:
    tag = data.get("affiliate_tag") or AFFILIATE_TAG
    site = html.escape(data.get("site_name") or SITE_NAME)
    updated = html.escape(data.get("last_updated_label") or format_updated(now_eastern()))
    sections = data.get("sections") or []
    deals = data.get("deals") or []
    by_section: dict[str, list[dict]] = {s["id"]: [] for s in sections}
    for deal in deals:
        if deal.get("section") in by_section and deal.get("asin"):
            by_section[deal["section"]].append(deal)

    nav = "\n".join(
        f'<a href="#{html.escape(s["id"])}">{html.escape(s["title"])}</a>' for s in sections
    )
    coupon_count = sum(1 for d in deals if d.get("coupon") is True)
    if coupon_count:
        nav = nav + '\n<a href="#deals" class="filter-coupons" data-filter="coupons">Coupons</a>'
    coupon_note = ""
    if coupon_count:
        coupon_note = (
            '<p class="note coupon-note">Coupon badges mean Amazon showed a clip-on coupon '
            "or promo on the product page when we checked; clip it on Amazon at checkout. "
            "Coupons can end anytime.</p>"
        )
    coupon_script = ""
    if coupon_count:
        coupon_script = """
  <script>
  (function () {
    var chip = document.querySelector("[data-filter='coupons']");
    if (!chip) return;
    var on = false;
    function apply() {
      chip.classList.toggle("is-active", on);
      chip.setAttribute("aria-pressed", on ? "true" : "false");
      document.querySelectorAll(".card").forEach(function (card) {
        card.hidden = on && card.getAttribute("data-coupon") !== "true";
      });
      document.querySelectorAll(".section").forEach(function (section) {
        var any = section.querySelector(".card:not([hidden])");
        section.hidden = on && !any;
      });
    }
    chip.setAttribute("role", "button");
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", function (e) {
      e.preventDefault();
      on = !on;
      apply();
    });
    document.querySelectorAll('.nav a:not([data-filter="coupons"])').forEach(function (link) {
      link.addEventListener("click", function () {
        if (on) {
          on = false;
          apply();
        }
      });
    });
  })();
  </script>"""
    parts = []
    for section in sections:
        cards = []
        for deal in by_section.get(section["id"], []):
            asin = re.sub(r"[^A-Z0-9]", "", deal["asin"].upper())
            if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                continue
            url = html.escape(product_url(asin, tag), quote=True)
            title = html.escape(deal.get("title") or f"Amazon product {asin}")
            blurb = html.escape(deal.get("blurb") or "On sale now. Check the current price on Amazon.")
            badge = html.escape(deal.get("badge") or "On sale now")
            coupon_html = ""
            coupon_attr = ""
            if deal.get("coupon") is True:
                coupon_html = '<span class="coupon-badge">Coupon available on Amazon</span>'
                coupon_attr = ' data-coupon="true"'
            cards.append(
                f"""
        <article class="card"{coupon_attr}>
          <div class="badge-row">
            <span class="badge">{badge}</span>
            {coupon_html}
          </div>
          <h3>{title}</h3>
          <p>{blurb}</p>
          <a class="btn" href="{url}" target="_blank" rel="nofollow sponsored">Check price on Amazon</a>
        </article>"""
            )
        count = len(cards)
        intro = html.escape(section.get("intro") or "")
        grid = "\n".join(cards) if cards else '<p class="empty">No deals in this section yet. Check back tomorrow.</p>'
        parts.append(
            f"""
    <section id="{html.escape(section['id'])}" class="section">
      <div class="section-head">
        <h2>{html.escape(section['title'])}</h2>
        <p class="count">{count} find{'s' if count != 1 else ''}</p>
      </div>
      <p class="intro">{intro}</p>
      <div class="grid">
{grid}
      </div>
    </section>"""
        )

    body_sections = "\n".join(parts)
    og_url = html.escape(SITE_URL, quote=True)
    og_title = html.escape(OG_TITLE, quote=True)
    og_desc = html.escape(OG_DESCRIPTION, quote=True)
    og_image = html.escape(OG_IMAGE, quote=True)
    og_alt = html.escape(OG_IMAGE_ALT, quote=True)
    og_site = html.escape(data.get("site_name") or SITE_NAME, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{site} — Toys, LEGO, tech, tools, home, kitchen, and holiday finds</title>
  <link rel="canonical" href="{og_url}">
  <meta name="description" content="A family-friendly daily roundup of Amazon deals on kids' toys, LEGO, tech, tools, bath, home decor, kitchen, and holiday gifts. As an Amazon Associate I earn from qualifying purchases.">
  <meta name="robots" content="index,follow">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{og_url}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:image" content="{og_image}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{og_alt}">
  <meta property="og:site_name" content="{og_site}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{og_desc}">
  <meta name="twitter:image" content="{og_image}">
  <meta name="twitter:image:alt" content="{og_alt}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="styles.css">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232a6f62'/%3E%3Cpath d='M18 36c8-14 20-14 28 0' fill='none' stroke='%23f7f1e8' stroke-width='5' stroke-linecap='round'/%3E%3Ccircle cx='32' cy='22' r='5' fill='%23e07a3d'/%3E%3C/svg%3E">
</head>
<body>
  <a class="skip" href="#deals">Skip to deals</a>
  <header class="hero">
    <div class="wrap">
      <p class="eyebrow">A family-friendly daily deals desk</p>
      <h1>{site}</h1>
      <p class="lede">Hand-picked Amazon finds in kids' toys, LEGO, tech, tools, toiletries &amp; bath, home decor, kitchen, and holiday gifts. Updated daily, with a short note on why each one made the list.</p>
      <p class="updated">Last updated {updated}</p>
      <p class="disclosure">{html.escape(DISCLOSURE)}</p>
      <nav class="nav" aria-label="Deal categories">
        {nav}
      </nav>
    </div>
  </header>
  <main id="deals" class="wrap">
    <p class="note">Prices change throughout the day, so we don't list Amazon prices or star ratings here. Open a product to see the current offer. Every link goes straight to Amazon and includes our affiliate tag.</p>
    {coupon_note}
    {body_sections}
  </main>
  <footer class="footer">
    <div class="wrap">
      <p>{html.escape(DISCLOSURE)}</p>
      <p>{site} is an independent deals guide. It is not affiliated with, endorsed by, or sponsored by Amazon or its affiliates, other than through the Amazon Associates program.</p>
      <p>Product availability and discounts can change or sell out. Please review the live listing, shipping details, and age guidance on Amazon before you buy.</p>
    </div>
  </footer>
  {coupon_script}
</body>
</html>
"""


def write_index(data: dict) -> None:
    INDEX_PATH.write_text(render(data))
    if not STYLES_PATH.exists():
        raise SystemExit(f"Missing {STYLES_PATH}; styles were not written.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the Daily Deal Finds static site.")
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch public deal roundups, verify ASINs, and add new verified deals before rendering.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-verify ASINs already in deals.json and drop only clear 404s.",
    )
    parser.add_argument(
        "--check-coupons",
        action="store_true",
        help="Check each deal's Amazon page for an official clip coupon, promo code, or Subscribe & Save offer.",
    )
    args = parser.parse_args()

    data = load_data()
    data["affiliate_tag"] = data.get("affiliate_tag") or AFFILIATE_TAG
    data["site_name"] = data.get("site_name") or SITE_NAME

    if args.fetch:
        added, dropped = fetch_new_deals(data)
        print(f"Fetch complete: added {added}, dropped {dropped}")
    elif args.check_coupons:
        summary = check_coupons(data)
        print(
            f"Coupon check complete: checked {summary['checked']}, "
            f"blocked {summary['blocked']}, badges {summary['found']}"
        )
        for item in summary["items"]:
            print(f"  badge: {item['title']} ({item['asin']})")
    elif args.verify:
        kept = []
        dropped = 0
        for deal in data["deals"]:
            result = verify_asin(deal["asin"])
            if result["reason"] == "not_found":
                print(f"drop 404 {deal['asin']}")
                dropped += 1
                continue
            kept.append(deal)
            print(f"keep {deal['asin']} ({result['reason']})")
        data["deals"] = kept
        print(f"Verify complete: kept {len(kept)}, dropped {dropped}")

    when = now_eastern()
    data["last_updated"] = when.isoformat()
    data["last_updated_label"] = format_updated(when)
    save_data(data)
    write_index(data)

    counts = {}
    for deal in data["deals"]:
        counts[deal["section"]] = counts.get(deal["section"], 0) + 1
    print(f"Wrote {INDEX_PATH}")
    print("Deals by section:", counts)
    print("Total deals:", sum(counts.values()))
    print("Last updated:", data["last_updated_label"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
