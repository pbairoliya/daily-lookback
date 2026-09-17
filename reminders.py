"""reminders.py — fetch Calendar + Gmail and render the Reminders section.

Pure-ish fetch + shape, like vault.py. Degrades gracefully if Google is down.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import urllib.error
import urllib.request

from config import (
    BILL_LEAD_DAYS,
    CALENDAR_LOOKAHEAD_DAYS,
    CALENDAR_LOOKBACK_DAYS,
    GMAIL_LOOKBACK_DAYS,
)

GMAIL_MAX_CANDIDATES = 35

TRIP_KEYWORDS = [
    "flight", "fly", "trip", "travel", "airport", "vacation", "hotel",
    "train", "drive to", "visit", "out of town", "ooo", "pto",
]

# Recurring calendar titles — omitted from coach EXTERNAL (still in note Reminders).
ROUTINE_CALENDAR_TITLES = {"work", "workout"}

# Domains excluded in Gmail search + matched post-fetch (retail ads, listings, deal blasts).
NOISE_FROM_DOMAINS = [
    # Listings
    "zillow.com", "trulia.com", "apartments.com", "realtor.com", "streeteasy.com",
    "apartmentlist.com", "rent.com", "hotpads.com", "redfin.com", "loopnet.com",
    # Discount / marketplace spam
    "temu.com", "shein.com", "wish.com", "aliexpress.com", "dhgate.com",
    "wayfair.com", "overstock.com", "houzz.com", "chewy.com", "walmart.com",
    "target.com", "bestbuy.com", "costco.com", "samsclub.com", "kohls.com",
    "macys.com", "nordstrom.com", "gap.com", "oldnavy.com", "nike.com",
    "adidas.com", "uniqlo.com", "asos.com", "hm.com", "forever21.com",
    "groupon.com", "livingsocial.com", "retailmenot.com", "slickdeals.net",
    "rakuten.com", "honey.com", "shopify.com", "klaviyo.com", "braze.com",
    # Food / delivery promos (receipts from same domains are rare in our queries)
    "grubhub.com", "doordash.com", "ubereats.com", "postmates.com",
    # Social / digest platforms
    "facebookmail.com", "linkedin.com", "pinterest.com", "tiktok.com",
    "mailchimp.com", "constantcontact.com", "sendgrid.net", "substack.com",
    # Travel deal blasts (not flight confirmations)
    "expedia.com", "kayak.com", "hotels.com", "booking.com", "priceline.com",
]

# Substring match on From / snippet / subject (catches subdomains and ESP aliases).
NOISE_SENDER_FRAGMENTS = [
    "temu", "shein", "wish.com", "aliexpress", "dhgate",
    "zillow", "trulia", "apartments.com", "realtor.com", "streeteasy",
    "apartmentlist", "rent.com", "hotpads", "redfin",
    "marketing@", "newsletter@", "promo@", "promotions@", "deals@",
    "sale@", "offers@", "noreply@e.", "email@e.", "@e.walmart",
    "shopifyemail", "klaviyo", "braze.com", "mailgun.", "sendgrid.",
    "smartnews", "retailmenot", "slickdeals", "coupon", "flashsale",
    "mcdonalds", "starbucks rewards", "uber promotions",
]

# Mass listing alerts + obvious ad subject lines (not personal housing inquiry).
NOISE_SUBJECT_FRAGMENTS = [
    "rental result", "apartments for rent", "homes for rent",
    "rental listing", "new listings", "price drop", "just listed",
    "% off", "percent off", "likritimited time", "flash sale", "ends tonight",
    "ends today", "last chance", "shop now", "don't miss", "do not miss",
    "exclusive offer", "special offer", "coupon code", "promo code",
    "free shipping", "clearance", "deal of the day", "daily deals",
    "weekly deals", "savings inside", "act now", "hurry",
    "recommended for you", "picked for you", "based on your recent",
    "still interested", "items you viewed", "your cart is waiting",
    "unbeatable prices", "lowest price", "mega sale", "super sale",
]

# Amazon order/shipping mail is useful; Amazon marketing blasts are not.
AMAZON_MARKETING_SUBJECT_FRAGMENTS = [
    "deals for you", "recommendations for you", "based on your browsing",
    "prime day", "today's deals", "for you:", "discover items",
    "keep shopping", "inspired by your", "top picks for you",
]

# Gmail category labels that are almost always ads / digests.
NOISE_GMAIL_LABELS = frozenset({
    "CATEGORY_PROMOTIONS",
    "CATEGORY_FORUMS",
    "SPAM",
    "TRASH",
})

# Housing inquiries are mostly noise right now — surface them ONLY when they come
# from one of these property managers (match on From / subject / snippet). Edit
# this list as the housing search changes.
HOUSING_INQUIRY_ALLOW = ["alcott", "akelius"]

HOUSING_INQUIRY_PHRASES = [
    "apartment inquiry", "inquiry about", "inquiry from", "regarding",
    "your application", "application received", "lease application",
    "tour", "showing", "interested in", "follow-up", "follow up",
]
HOUSING_CONTEXT_WORDS = [
    "apartment", "lease", "rental", "housing", "property", "landlord",
    "leasing", "building", "unit", "parc",
]

CATEGORY_LABELS: dict[str, str] = {
    "bill_rent": "Bill due · rent",
    "bill_cc": "Bill due · card",
    "bill_other": "Bill due",
    "venmo": "Venmo",
    "transfer": "Money · transfer",
    "statement": "Money · statement",
    "housing_inquiry": "Housing inquiry",
    "payment_received": "Money · received",
    "reply": "Reply needed",
    "decision": "Decision",
    "deadline": "Deadline",
    "fyi": "FYI",
    "action_candidate": "Review",
}

# Strict payment-due signals (not "apartment inquiry" or "paid you").
BILL_SUBJECT_KEYWORDS = [
    "payment due", "payment is due", "due date", "minimum payment",
    "statement ready", "statement available", "amount due", "pay your",
    "autopay", "auto-pay", "bill is ready", "rent due", "rent payment",
    "lease payment", "balance due", "pay now", "scheduled payment",
    "past due", "your statement", "credit card statement",
]
BILL_SENDER_HINTS = [
    "@chase.com", "@americanexpress.com", "@amex.com", "@citi.com", "@citibank",
    "@capitalone.com", "@discover.com", "@bankofamerica.com", "@bofa", "@wellsfargo.com",
    "@usbank.com", "@synchrony", "@barclays", "@fifththird.com", "@53.com",
    "@apple.com",  # Apple Card statements via Goldman
    "@goldmansachs", "@marcus.com", "@sofi.com", "@robinhood.com", "@venmo.com",
]

# Apartment / rent-portal senders. Rent emails usually come from a payment-portal
# (not the leasing office), often OMIT the word "rent", and frequently land in
# Gmail's Promotions tab — so they need their own trusted path.
RENT_SENDER_HINTS = [
    "rentcafe", "entrata", "resman", "yardi", "realpage", "appfolio", "buildium",
    "paylease", "clickpay", "zego", "gozego", "domuso", "flexrent", "residentportal",
    "onesite", "activebuilding", "knock", "leasing", "propertymanagement", "rent.",
]

# YOUR specific building(s). Edit this when you move. These match From + subject + snippet.
RENT_COMMUNITY_HINTS = [
    "point at mclean", "the point at mclean", "pointatmclean", "thepointatmclean",
    "point-at-mclean",
]

# Bills/statements often arrive 3-4 weeks before due — look back further than general mail.
BILLS_LOOKBACK_DAYS = 35

# Domain groups for robust, subdomain-safe statement classification. Matching is by
# domain suffix (so eal.bankofamerica.com matches bankofamerica.com) — NOT substring,
# which would let "discover@qrgroup.qa" (a Qatar Airways alias) masquerade as Discover.
CARD_ISSUER_DOMAINS = [
    "chase.com", "discover.com", "americanexpress.com", "amex.com", "capitalone.com",
    "citi.com", "citibank.com", "barclaycardus.com", "barclays.com", "synchrony.com",
    "apple.com", "goldmansachs.com", "marcus.com", "bankofamerica.com", "sofi.com",
]
BANK_BROKERAGE_DOMAINS = [
    "wellsfargo.com", "usbank.com", "fifththird.com", "53.com", "ml.com",
    "merrill.com", "schwab.com", "fidelity.com", "jpmorgan.com", "vanguard.com",
]
STRONG_DUE_PHRASES = [
    "payment due", "payment is due", "amount due", "minimum payment", "balance due",
    "past due", "pay your", "autopay", "auto-pay", "payment reminder", "bill is ready",
    "scheduled payment", "rent due", "rent payment", "lease payment", "due date",
]
STATEMENT_PHRASES = [
    "statement is available", "statement is ready", "new statement", "statement available",
    "statement ready", "e-statement", "credit card statement", "latest statement",
    "monthly statement", "account statement", "new account statement",
    "statement for account", "statement online", "statement is ready to view",
    "your statement", "view your statement",
]
# Airline / hotel loyalty "statements" are not bills.
LOYALTY_NONBILL_HINTS = [
    "privilege club", "skymiles", "rapid rewards", "frequent flyer", "avios",
    "qatar", "airways", "miles statement", "points statement", "loyalty",
]

# Deposit/savings/brokerage account statements — money-ish but NOTHING is owed.
# These come from card-issuer domains too (BoA, Amex issue BOTH cards and deposit
# accounts), so the sender domain can't tell them apart — the account NAME does
# ("SafeBalance", "High Yield Savings", "checking"). Misreading one as a card bill
# produces a "pay" task with no amount, which is exactly the bug we're killing.
DEPOSIT_ACCOUNT_HINTS = [
    "safebalance", "adv plus banking", "advantage banking", "adv safebalance",
    "checking account", "savings account", "high yield savings", "deposit account",
    "money market", "certificate of deposit", "cd account", "new bank statement",
]

# Statement notices that explicitly say nothing is owed (Amex charge-card / autopay
# "Statement Ready" mails omit the balance and state payment isn't required). With no
# amount AND no due date, these are FYI — never a payable task with a blank price.
NO_PAYMENT_DUE_HINTS = [
    "payment is not required", "no payment is required", "no payment due",
    "no minimum payment due", "does not require payment",
]

INCOMING_PAYMENT_PHRASES = [
    "paid you", "sent you", "you received", "money received",
    "deposit to your", "credited to your",
]

# Money MOVEMENT alerts (Zelle/wire/transfer/deposit) → "money talks", NOT a bill due.
# Keep these SPECIFIC: broad fragments like "payment of $" wrongly match a card
# statement's "minimum payment of $35", hiding a real bill.
TRANSFER_PHRASES = [
    "zelle", "has been sent", "you sent", "money sent", "wire transfer",
    "transfer to", "transfer from", "as a zelle recipient", "added you as a",
    "direct deposit", "deposit posted", "ach credit", "ach debit",
]

# Apartment community newsletters/events/ops notices (from the building, NOT rent
# and NOT a personal reply). Low-signal — surfaced at most as FYI, never a task.
COMMUNITY_BLAST_FRAGMENTS = [
    "daily digest", "weekly digest", "happy hour", "newsletter", "resident event",
    "community event", "amenity", "pool party", "raffle", "giveaway", "food truck",
    "rsvp", "join us", "this weekend", "tomorrow at", "celebrate", "social",
    "internet outage", "outage", "internet issue", "maintenance", "work order",
    "package room", "fire alarm", "water shut", "elevator", "single digits",
    "is back on", "pool opening", "pool is open", "office hours", "office closed",
    "holiday hours", "announcement", "now leasing", "renew your lease early",
]

VIP_OR = ""

def _gmail_noise_exclude_clause(max_domains: int = 32) -> str:
    """Build -from:domain clauses for Gmail (length-limited; rest filtered post-fetch)."""
    return "".join(f" -from:{d}" for d in NOISE_FROM_DOMAINS[:max_domains])


GMAIL_NOISE_EXCLUDE = _gmail_noise_exclude_clause()

GMAIL_CATEGORY_EXCLUDE = " -category:promotions -category:social -category:forums "

GMAIL_QUERY_GENERAL = (
    f"newer_than:{GMAIL_LOOKBACK_DAYS}d {GMAIL_CATEGORY_EXCLUDE}"
    f"{GMAIL_NOISE_EXCLUDE}"
    f"(is:important OR is:starred OR (is:unread to:me){VIP_OR})"
)

# NOTE: deliberately NO category/noise exclude here — credit-card statements and
# rent-portal emails routinely land in Promotions, so excluding it hides the bills.
# Subject-DRIVEN (real statements/bills say "statement"/"payment due"), so promo
# blasts from card-issuer aliases don't flood it. Sender clause is rent-portals only.
#
# Do NOT add the building name as a bare subject term — "point at mclean" matched
# every community Daily Digest / service-request blast, and that flood (10+/week)
# crowded real card statements past the fetch cap so they were never pulled. Real
# rent bills still match via the statement/payment-due terms or the rent-portal
# from: clause; the building's digests are excluded outright below.
GMAIL_QUERY_BILLS = (
    f"newer_than:{BILLS_LOOKBACK_DAYS}d "
    "(subject:(statement OR \"payment due\" OR \"amount due\" OR \"minimum payment\" "
    "OR \"balance due\" OR \"due date\" OR autopay OR \"payment reminder\" "
    "OR \"bill is ready\" OR invoice OR e-statement) "
    "OR from:(rentcafe OR entrata OR resman OR yardi OR realpage OR appfolio OR clickpay "
    "OR paylease OR zego OR domuso)) "
    "-subject:digest -subject:\"service request\" -subject:newsletter"
)

TRIAGE_PROMPT = """You are an inbox triage assistant. Return STRICT JSON only:
{"actionable":[{"from":str,"subject":str,"why":str,"urgency":"high|med|low","category":"reply|decision|deadline|fyi"}]}
Keep emails needing a reply, decision, or deadline. Drop marketing, ads (Temu, Zillow, retail promos), newsletters.
category: reply | decision | deadline | fyi. "why" max 8 words. No prose."""


def _parse_start(raw: str) -> dt.datetime | None:
    if not raw:
        return None
    try:
        if "T" in raw:
            return dt.datetime.fromisoformat(raw)
        return dt.datetime.fromisoformat(raw + "T00:00:00")
    except ValueError:
        return None


def calendar_events(
    anchor: dt.datetime,
    lookback_days: int = CALENDAR_LOOKBACK_DAYS,
    lookahead_days: int = CALENDAR_LOOKAHEAD_DAYS,
) -> list[dict]:
    import google_auth

    if not google_auth.is_configured():
        return []

    anchor_midnight = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    anchor_date = anchor_midnight.date()
    range_start = anchor_midnight - dt.timedelta(days=lookback_days)
    range_end = anchor_midnight + dt.timedelta(days=lookahead_days + 1)

    try:
        svc = google_auth.calendar_client()
        resp = (
            svc.events()
            .list(
                calendarId="primary",
                timeMin=range_start.astimezone().isoformat(),
                timeMax=range_end.astimezone().isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        print(f"Calendar fetch failed ({e}); skipping events.")
        return []

    out: list[dict] = []
    for e in resp.get("items", []):
        raw = e["start"].get("dateTime", e["start"].get("date", ""))
        when = _parse_start(raw)
        if when is None:
            continue
        summary = e.get("summary", "(no title)")
        text = f"{summary} {e.get('description', '')}".lower()
        event_date = when.date()
        out.append(
            {
                "summary": summary,
                "start": when,
                "all_day": "date" in e["start"],
                "location": e.get("location", ""),
                "is_anchor_day": event_date == anchor_date,
                "days_from_anchor": (event_date - anchor_date).days,
                "is_trip": any(k in text for k in TRIP_KEYWORDS),
                "is_routine": _is_routine_calendar(summary),
            }
        )
    return out


def _is_routine_calendar(summary: str) -> bool:
    return summary.strip().lower() in ROUTINE_CALENDAR_TITLES


def todays_events(now: dt.datetime | None = None) -> list[dict]:
    if now is None:
        now = dt.datetime.now()
    return calendar_events(now)


def _short_from(addr: str) -> str:
    m = re.match(r"^([^<]+)", addr.strip())
    name = (m.group(1) if m else addr).strip().strip('"')
    if "@" in name and " " not in name:
        return name.split("@")[0]
    return name or addr


def _email_text(m: dict) -> str:
    return f"{m.get('subject', '')} {m.get('snippet', '')} {m.get('from', '')}".lower()


def _from_domain(addr: str) -> str:
    m = re.search(r"@([\w.-]+\.\w+)", (addr or "").lower())
    return m.group(1) if m else ""


def _domain_is_noise(domain: str) -> bool:
    if not domain:
        return False
    for d in NOISE_FROM_DOMAINS:
        if domain == d or domain.endswith("." + d):
            return True
    return False


def _is_rent_sender(m: dict) -> bool:
    """From a rent-payment portal OR the user's specific building."""
    text = _email_text(m)
    return any(h in text for h in RENT_SENDER_HINTS) or any(
        h in text for h in RENT_COMMUNITY_HINTS
    )


def _is_trusted_sender(m: dict) -> bool:
    """Senders that should not be dropped as ads even if subject looks promotional."""
    text = _email_text(m)
    if any(h in text for h in BILL_SENDER_HINTS):
        return True
    if _is_venmo(m) or _is_rent_sender(m):
        return True
    trusted = [
        "venmo.com", "paypal.com", "chase.com", "americanexpress.com", "amex.com",
        "citi.com", "citibank.com", "capitalone.com", "discover.com", "bankofamerica.com",
        "wellsfargo.com", "usbank.com", "fifththird.com", "53.com", "synchrony.com",
        "barclaycardus.com", "goldmansachs.com", "marcus.com", "sofi.com",
        "irs.gov", "uscis.gov",
    ]
    domain = _from_domain(m.get("from", ""))
    return any(domain == t or domain.endswith("." + t) for t in trusted)


def _is_amazon_marketing(m: dict) -> bool:
    if _is_trusted_sender(m):
        return False
    text = _email_text(m)
    if "amazon" not in text:
        return False
    return any(p in text for p in AMAZON_MARKETING_SUBJECT_FRAGMENTS)


def _has_noise_gmail_label(m: dict) -> bool:
    labels = m.get("labels") or []
    return bool(NOISE_GMAIL_LABELS.intersection(labels))


def _looks_like_housing_inquiry(m: dict) -> bool:
    text = _email_text(m)
    if "inquiry" in text and ("apartment" in text or "regarding" in text):
        return True
    return any(p in text for p in HOUSING_INQUIRY_PHRASES) and any(
        w in text for w in HOUSING_CONTEXT_WORDS
    )


def _is_listing_marketing_only(m: dict) -> bool:
    """Zillow-style blasts — not a personal inquiry thread."""
    domain = _from_domain(m.get("from", ""))
    listing_domains = {
        "zillow.com", "trulia.com", "apartments.com", "realtor.com", "streeteasy.com",
        "apartmentlist.com", "rent.com", "hotpads.com", "redfin.com", "loopnet.com",
    }
    if domain in listing_domains or any(domain.endswith("." + d) for d in listing_domains):
        return True
    text = _email_text(m)
    return any(s in text for s in NOISE_SUBJECT_FRAGMENTS[:6])


def _is_noise_email(m: dict) -> bool:
    if _is_trusted_sender(m) or _is_venmo(m) or _looks_like_housing_inquiry(m):
        return False
    if _has_noise_gmail_label(m):
        return True
    if _is_amazon_marketing(m):
        return True
    domain = _from_domain(m.get("from", ""))
    if _domain_is_noise(domain):
        return True
    text = _email_text(m)
    if any(n in text for n in NOISE_SENDER_FRAGMENTS):
        return True
    return any(n in text for n in NOISE_SUBJECT_FRAGMENTS)


def _is_incoming_payment(m: dict) -> bool:
    text = _email_text(m)
    return any(p in text for p in INCOMING_PAYMENT_PHRASES)


def _is_money_transfer(m: dict) -> bool:
    """Zelle / wire / ACH / deposit alert — money moved, nothing owed."""
    return any(p in _email_text(m) for p in TRANSFER_PHRASES)


def _is_community_blast(m: dict) -> bool:
    """Apartment newsletter/event from the building — not a rent bill."""
    return any(p in _email_text(m) for p in COMMUNITY_BLAST_FRAGMENTS)


def _is_venmo(m: dict) -> bool:
    text = _email_text(m)
    return "venmo" in text or "venmo.com" in (m.get("from") or "").lower()


def _venmo_label(m: dict) -> str:
    text = _email_text(m)
    if any(p in text for p in INCOMING_PAYMENT_PHRASES):
        return "Venmo · paid you"
    if any(p in text for p in ["you paid", "payment to", "you sent", "charged your"]):
        return "Venmo · you paid"
    return CATEGORY_LABELS["venmo"]


def _housing_allowed(m: dict) -> bool:
    """Only keep housing inquiries from the property managers we still care about."""
    return any(h in _email_text(m) for h in HOUSING_INQUIRY_ALLOW)


def _is_housing_inquiry(m: dict) -> bool:
    if _is_listing_marketing_only(m):
        return False
    return _looks_like_housing_inquiry(m)


def _attach_category_label(row: dict) -> dict:
    cat = row.get("category", "")
    if cat == "venmo":
        row["category_label"] = _venmo_label(row)
    else:
        row["category_label"] = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
    return row


def _sender_in(m: dict, domains: list[str]) -> bool:
    """True if the From domain equals or is a subdomain of any listed domain."""
    d = _from_domain(m.get("from", ""))
    return bool(d) and any(d == t or d.endswith("." + t) for t in domains)


def _has_due(m: dict) -> bool:
    return any(p in _email_text(m) for p in STRONG_DUE_PHRASES)


def _has_statement(m: dict) -> bool:
    return any(p in _email_text(m) for p in STATEMENT_PHRASES)


def _is_loyalty_statement(m: dict) -> bool:
    """Airline/hotel 'statement' (miles/points) — money-ish but never a bill."""
    text = _email_text(m)
    return any(h in text for h in LOYALTY_NONBILL_HINTS) and not _sender_in(
        m, CARD_ISSUER_DOMAINS + BANK_BROKERAGE_DOMAINS
    )


def _text_is_deposit(text: str) -> bool:
    return any(h in text for h in DEPOSIT_ACCOUNT_HINTS)


def _text_is_no_payment(text: str) -> bool:
    return any(h in text for h in NO_PAYMENT_DUE_HINTS)


def _is_deposit_statement(m: dict) -> bool:
    """Checking/savings/deposit-account statement — nothing owed, FYI only."""
    if _has_due(m):  # a real amount-due overrides; a deposit account never has one
        return False
    return _text_is_deposit(_email_text(m))


def _is_no_payment_notice(m: dict) -> bool:
    """A statement that explicitly says no payment is required (and shows no due)."""
    if _has_due(m):
        return False
    return _text_is_no_payment(_email_text(m))


def _is_strict_rent_bill(m: dict) -> bool:
    if _is_incoming_payment(m) or _is_money_transfer(m) or _is_community_blast(m):
        return False
    text = _email_text(m)
    # From the building/portal: rent ONLY with a real statement/payment signal, so
    # digests and event invites from the building don't get flagged as bills.
    if _is_rent_sender(m) and (
        _has_due(m) or _has_statement(m) or any(w in text for w in ["balance", "ledger", "amount due"])
    ):
        return True
    if _is_noise_email(m) or any(n in text for n in NOISE_SUBJECT_FRAGMENTS):
        return False
    strong = ["rent due", "rent payment", "lease payment", "landlord", "property management"]
    if any(s in text for s in strong):
        return True
    return (_has_due(m) or any(k in text for k in BILL_SUBJECT_KEYWORDS)) and any(
        w in text for w in ["rent", "lease"]
    )


def _is_strict_credit_card_bill(m: dict) -> bool:
    if _is_money_transfer(m) or _is_incoming_payment(m) or _is_strict_rent_bill(m):
        return False
    if _is_loyalty_statement(m):
        return False
    text = _email_text(m)
    if "credit card statement" in text:
        return True
    # A statement or payment-due from an actual card-issuer domain (subdomain-safe).
    if _sender_in(m, CARD_ISSUER_DOMAINS) and (_has_due(m) or _has_statement(m)):
        return True
    # Explicit payment-due that names a card, from any sender.
    return _has_due(m) and any(w in text for w in ["credit card", "card ending", "card account"])


def _is_bank_statement_fyi(m: dict) -> bool:
    """Brokerage/checking statement with nothing due — informational money, not a bill."""
    if _has_due(m) or _is_loyalty_statement(m):
        return False
    return _sender_in(m, BANK_BROKERAGE_DOMAINS) and _has_statement(m)


def _is_strict_bill_other(m: dict) -> bool:
    if _is_money_transfer(m) or _is_incoming_payment(m):
        return False
    if _is_strict_rent_bill(m) or _is_strict_credit_card_bill(m) or _is_bank_statement_fyi(m):
        return False
    if _is_noise_email(m):
        return False
    return _has_due(m) or any(k in _email_text(m) for k in BILL_SUBJECT_KEYWORDS)


def classify_email(m: dict) -> dict:
    """Add category + flags; noise mails should be dropped before triage."""
    row = dict(m)
    if _is_venmo(m):
        row["category"] = "venmo"
        row["is_bill"] = False
        row["actionable"] = False
        return _attach_category_label(row)
    # Apartment newsletters/events from the building — not rent, not actionable.
    if _is_rent_sender(m) and _is_community_blast(m) and not _is_strict_rent_bill(m):
        row["category"] = "noise"
        row["is_bill"] = False
        row["actionable"] = False
        return row
    if _is_incoming_payment(m):
        row["category"] = "payment_received"
        row["is_bill"] = False
        row["actionable"] = False
        return _attach_category_label(row)
    # Zelle/wire/ACH/deposit alerts → "money talks" (money moved), not a bill.
    if _is_money_transfer(m):
        row["category"] = "transfer"
        row["is_bill"] = False
        row["actionable"] = False
        return _attach_category_label(row)
    # Brokerage/checking statement with nothing due → informational, not a bill.
    if _is_bank_statement_fyi(m):
        row["category"] = "statement"
        row["is_bill"] = False
        row["actionable"] = False
        return _attach_category_label(row)
    # Deposit/savings statement (SafeBalance, HY Savings) OR an explicit "no payment
    # required" notice (Amex Statement Ready) from ANY issuer → FYI, never a card bill.
    if _is_deposit_statement(m) or _is_no_payment_notice(m):
        row["category"] = "statement"
        row["is_bill"] = False
        row["actionable"] = False
        return _attach_category_label(row)
    if _is_housing_inquiry(m):
        # Drop housing inquiries unless they're from an allowlisted manager
        # (Alcott / Akelius) — everything else is noise for now.
        if not _housing_allowed(m):
            row["category"] = "noise"
            row["is_bill"] = False
            row["actionable"] = False
            return row
        row["category"] = "housing_inquiry"
        row["is_bill"] = False
        row["actionable"] = True
        return _attach_category_label(row)
    if _is_noise_email(m):
        row["category"] = "noise"
        row["is_bill"] = False
        row["actionable"] = False
        return row
    if _is_strict_rent_bill(m):
        row["category"] = "bill_rent"
        row["is_bill"] = True
        row["is_rent"] = True
        row["is_credit_card"] = False
        row["actionable"] = True
        return _attach_category_label(row)
    if _is_strict_credit_card_bill(m):
        row["category"] = "bill_cc"
        row["is_bill"] = True
        row["is_rent"] = False
        row["is_credit_card"] = True
        row["actionable"] = True
        return _attach_category_label(row)
    if _is_strict_bill_other(m):
        row["category"] = "bill_other"
        row["is_bill"] = True
        row["is_rent"] = False
        row["is_credit_card"] = False
        row["actionable"] = True
        return _attach_category_label(row)
    row["category"] = "action_candidate"
    row["is_bill"] = False
    row["is_rent"] = False
    row["is_credit_card"] = False
    row["actionable"] = True
    return _attach_category_label(row)


def _gmail_list(svc, query: str, max_n: int) -> list[str]:
    try:
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_n).execute()
        return [m["id"] for m in resp.get("messages", [])]
    except Exception:
        return []


# Friendly payee names by sender domain (subdomain-safe).
ISSUER_NAMES: dict[str, str] = {
    "chase.com": "Chase", "discover.com": "Discover", "americanexpress.com": "Amex",
    "amex.com": "Amex", "capitalone.com": "Capital One", "citi.com": "Citi",
    "citibank.com": "Citi", "bankofamerica.com": "Bank of America",
    "wellsfargo.com": "Wells Fargo", "usbank.com": "US Bank", "fifththird.com": "Fifth Third",
    "53.com": "Fifth Third", "synchrony.com": "Synchrony", "barclaycardus.com": "Barclays",
    "apple.com": "Apple Card", "marcus.com": "Marcus", "goldmansachs.com": "Apple Card",
    "ml.com": "Merrill", "merrill.com": "Merrill", "sofi.com": "SoFi",
}

# Amounts attached to an "owed" keyword. FULL balance first (the real amount due),
# minimum payment only as a labeled fallback — never prefer the minimum.
_DUE_AMOUNT_RES = [
    re.compile(
        r"(?:statement balance|new balance|ending balance|total balance|outstanding balance|"
        r"balance due|total (?:amount )?due|amount due|current balance|total due|rent due|"
        r"amount enclosed|please pay|payment amount)"
        r"\D{0,40}\$\s?([0-9][0-9,]*\.\d{2})",
        re.I,
    ),
    re.compile(
        r"(?:minimum payment(?: due)?|min(?:imum)? due)\D{0,40}\$\s?([0-9][0-9,]*\.\d{2})",
        re.I,
    ),
]
_ANY_AMOUNT_RE = re.compile(r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
_DUE_DATE_RE = re.compile(
    r"(?:due (?:date|by|on)|payment due(?: date)?|autopay(?:s|ed)?(?: on| date)?|"
    r"scheduled for|drafts? on)\D{0,25}"
    rf"({_MONTH}\.?\s+\d{{1,2}}(?:,?\s*\d{{2,4}})?|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)",
    re.I,
)


def _b64(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""


def _gmail_body_text(svc, msg_id: str) -> str:
    """Full message body as plain text (HTML stripped). Used to read bill amounts."""
    try:
        msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception:  # noqa: BLE001
        return ""
    texts: list[str] = []

    def _strip_html(html: str) -> str:
        # Drop <style>/<script>/<head> wholesale FIRST — their text content is not
        # inside tags, so plain tag-stripping leaves kilobytes of CSS that bury the
        # real numbers past the length cap (and made body reads fall back to snippet).
        html = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", html)
        return re.sub(r"<[^>]+>", " ", html)

    def walk(p: dict) -> None:
        mt = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and mt == "text/plain":
            texts.append(_b64(data))
        elif data and mt == "text/html":
            texts.append(_strip_html(_b64(data)))
        for sub in p.get("parts") or []:
            walk(sub)

    walk(msg.get("payload", {}))
    return re.sub(r"\s+", " ", " ".join(texts))[:8000]


def extract_amount(text: str) -> str:
    """The real amount owed. Prefers the FULL statement balance; if only a minimum
    payment is present it's returned labeled 'min $X' so it isn't mistaken for the total."""
    full = _DUE_AMOUNT_RES[0].search(text)
    if full:
        return "$" + full.group(1)
    minimum = _DUE_AMOUNT_RES[1].search(text)
    if minimum:
        return "min $" + minimum.group(1)
    # Fallback: the largest dollar amount present (often the balance/total).
    amounts = [m.group(1) for m in _ANY_AMOUNT_RE.finditer(text)]
    if amounts:
        biggest = max(amounts, key=lambda a: float(a.replace(",", "")))
        return "$" + biggest
    return ""


def extract_due_date(text: str) -> str:
    m = _DUE_DATE_RE.search(text)
    return m.group(1).strip() if m else ""


_MONTH_NUM = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
# A bare date token: "Jul 14", "Jul 14, 2026", "7/14", "7/14/26". No keyword
# prefix required (unlike _DUE_DATE_RE) — used on already-extracted due strings
# and on bill task lines that read "… due Jul 14)".
_DATE_TOKEN_RE = re.compile(
    rf"({_MONTH})\.?\s+(\d{{1,2}})(?:,?\s*(\d{{4}}))?"
    r"|(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",
    re.I,
)


def parse_due_date(text: str, ref: dt.date) -> dt.date | None:
    """First date token in `text` as a date. When the year is omitted, snap to
    the occurrence nearest `ref` so a "Jan 5" seen in December means next year."""
    if not text:
        return None
    m = _DATE_TOKEN_RE.search(text)
    if not m:
        return None
    if m.group(1):  # month name
        mon = _MONTH_NUM.get(m.group(1).lower()[:3])
        if not mon:
            return None
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else ref.year
        explicit_year = m.group(3) is not None
    else:  # numeric m/d[/y]
        mon, day = int(m.group(4)), int(m.group(5))
        yr = m.group(6)
        if yr:
            year = int(yr) + 2000 if int(yr) < 100 else int(yr)
            explicit_year = True
        else:
            year, explicit_year = ref.year, False
    try:
        due = dt.date(year, mon, day)
    except ValueError:
        return None
    if not explicit_year:
        if (due - ref).days < -180:
            due = due.replace(year=due.year + 1)
        elif (due - ref).days > 180:
            due = due.replace(year=due.year - 1)
    return due


def bill_is_due_soon(text: str, target: dt.date, lead_days: int = BILL_LEAD_DAYS) -> bool:
    """Whether a bill should be surfaced yet. True when the due date is unknown
    (be safe — show it), within `lead_days` ahead, or already past (overdue).
    False only when the due date is clearly more than `lead_days` in the future."""
    due = parse_due_date(text, target)
    if due is None:
        return True
    return (due - target).days <= lead_days


# Auto-generated, date-anchored trip tasks (see trip_prep_tasks / trip_pack_tasks).
# They mean nothing the day after they fire, so they must never carry over — if a
# trip is still upcoming they're re-derived fresh from the calendar.
_TRIP_PREP_TASK_FRAGMENTS = (
    "prep / pack for tomorrow",
    "start packing list for",
    "(in 2 days)",
)


def is_trip_prep_task(text: str) -> bool:
    low = text.lower()
    return any(f in low for f in _TRIP_PREP_TASK_FRAGMENTS)


def extract_minimum(text: str) -> str:
    """The minimum payment, returned as '$X' (separate from the full balance so a
    card line can show both: '$1,234.56 · min $25.00')."""
    m = _DUE_AMOUNT_RES[1].search(text)
    return "$" + m.group(1) if m else ""


# Last 4-5 digits identifying WHICH card/account, so two cards from the same issuer
# (two cards from the same issuer, e.g. …1111 vs …2222) never collapse into one line.
_ACCOUNT_TAIL_RES = [
    re.compile(r"(?:ending(?:\s*in)?|account ending|acct\.?)\D{0,8}(\d{4,5})\b", re.I),
    re.compile(r"(?:[-x*#•·]|\bending\b)\s*(\d{4,5})\b", re.I),
]


def extract_account_tail(*sources: str) -> str:
    for src in sources:
        for rx in _ACCOUNT_TAIL_RES:
            m = rx.search(src or "")
            if m:
                return m.group(1)
    return ""


def _bill_payee(m: dict) -> str:
    """Human payee name (building for rent, issuer for cards) — never 'NoReply'."""
    text = _email_text(m)
    if m.get("category") == "bill_rent" or _is_rent_sender(m):
        if any(c in text for c in RENT_COMMUNITY_HINTS):
            return "The Point at McLean"
    d = _from_domain(m.get("from", ""))
    for dom, name in ISSUER_NAMES.items():
        if d == dom or d.endswith("." + dom):
            return name
    who = _short_from(m.get("from", ""))
    return who if who.lower() not in ("noreply", "no-reply", "no reply", "donotreply") else "Statement"


def _gmail_fetch_one(svc, msg_id: str) -> dict | None:
    try:
        msg = (
            svc.users()
            .messages()
            .get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
    except Exception:
        return None
    h = {x["name"]: x["value"] for x in msg.get("payload", {}).get("headers", [])}
    row = {
        "id": msg_id,
        "from": h.get("From", ""),
        "subject": h.get("Subject", "(no subject)"),
        "date": h.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }
    return classify_email(row)


def candidate_emails(max_n: int = GMAIL_MAX_CANDIDATES) -> list[dict]:
    """Fetch mail, classify, drop noise (Zillow etc.)."""
    import google_auth

    if not google_auth.is_configured():
        return []
    try:
        svc = google_auth.gmail_client()
    except Exception as e:  # noqa: BLE001
        print(f"Gmail fetch failed ({e}); skipping inbox.")
        return []

    # Bills query first (subject-driven, low noise) so real statements are never
    # crowded out by general inbox volume; general query fills the rest. Bills get
    # the larger share: a statement can be 3-4 weeks old, so several may sit behind
    # newer matches and we'd rather over-fetch than miss a real bill.
    bills_cap = max(int(max_n * 0.7), 22)
    general_cap = max(max_n - bills_cap, 12)
    ids: list[str] = []
    seen: set[str] = set()
    for q, cap in ((GMAIL_QUERY_BILLS, bills_cap), (GMAIL_QUERY_GENERAL, general_cap)):
        for mid in _gmail_list(svc, q, cap):
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)
            if len(ids) >= max_n:
                break
        if len(ids) >= max_n:
            break

    out: list[dict] = []
    dropped_noise = 0
    for mid in ids:
        row = _gmail_fetch_one(svc, mid)
        if not row:
            continue
        if row.get("category") == "noise":
            dropped_noise += 1
            continue
        out.append(row)
    if dropped_noise:
        print(f"Gmail: filtered {dropped_noise} noise messages (ads, listings, promos)")

    # For bills only, read the email BODY to pull the amount due + due date (cheap:
    # there are only a handful of bills, and the context is worth the extra fetch).
    for row in out:
        if row.get("is_bill"):
            body = _gmail_body_text(svc, row["id"])
            snippet = row.get("snippet", "")
            amount = extract_amount(body) or extract_amount(snippet)
            due = extract_due_date(body) or extract_due_date(snippet)
            # Safety net: a "bill" whose body yields NO amount and NO due date, and
            # that reads like a deposit statement or a no-payment-required notice, is
            # not payable. Demote to FYI so it never renders as "pay" with a blank
            # price (catches anything the snippet-level check in classify_email missed).
            if not amount and not due and (_text_is_deposit(body) or _text_is_no_payment(body)):
                row["category"] = "statement"
                row["is_bill"] = False
                row["is_credit_card"] = False
                row["actionable"] = False
                _attach_category_label(row)
                continue
            row["amount"] = amount
            row["minimum"] = extract_minimum(body) or extract_minimum(snippet)
            row["due_date"] = due
            row["payee"] = _bill_payee(row)
            row["account_tail"] = extract_account_tail(
                row.get("subject", ""), snippet, body
            )

    out.sort(key=lambda m: (m.get("category", "") != "bill_cc", m.get("subject", "")))
    return out


def triage_emails(
    candidates: list[dict],
    model: str,
    ollama_url: str = "http://localhost:11434/api/generate",
) -> list[dict]:
    if not candidates:
        return []

    bills = [m for m in candidates if str(m.get("category", "")).startswith("bill_")]
    passthrough_cats = ("venmo", "transfer", "statement", "housing_inquiry", "payment_received")
    passthrough = [m for m in candidates if m.get("category") in passthrough_cats]
    to_triage = [m for m in candidates if m.get("category") == "action_candidate"]

    lines = []
    for i, m in enumerate(to_triage[:14], 1):
        lines.append(
            f"{i}. From: {m.get('from', '')}\n"
            f"   Subject: {m.get('subject', '')}\n"
            f"   Snippet: {m.get('snippet', '')[:160]}"
        )
    payload = {
        "model": model,
        "system": TRIAGE_PROMPT,
        "prompt": "\n\n".join(lines) if lines else "(no non-bill mail)",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    triaged: list[dict] = []
    if lines:
        try:
            req = urllib.request.Request(
                ollama_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            raw = body.get("response", "").strip()
            data = json.loads(raw)
            items = data.get("actionable", [])
            if isinstance(items, list):
                for x in items:
                    if isinstance(x, dict):
                        x.setdefault("is_bill", False)
                        x.setdefault("category", x.get("category", "reply"))
                        triaged.append(x)
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            print(f"Email triage failed ({e}); using heuristic fallback.")

    if not triaged and to_triage:
        triaged = [
            {
                "from": m.get("from", ""),
                "subject": m.get("subject", ""),
                "why": (m.get("snippet", "") or "")[:60],
                "urgency": "med",
                "is_bill": False,
                "category": "reply",
            }
            for m in to_triage[:6]
        ]

    out: list[dict] = []
    seen_subj: set[str] = set()

    def _add(m: dict) -> None:
        # Two cards from one issuer share a subject ("Your credit card statement is
        # available") — key on the account tail too so both survive with their own
        # amounts instead of collapsing to a single line.
        key = m.get("subject", "") + "|" + (m.get("account_tail", "") or "")
        if key in seen_subj:
            return
        seen_subj.add(key)
        out.append(m)

    for m in bills:
        cat = m.get("category", "bill_other")
        subj = m.get("subject", "")
        why = {
            "bill_rent": "rent or lease — review and pay",
            "bill_cc": "card statement — review and pay",
            "bill_other": "payment due — review",
        }.get(cat, "payment — review")
        _add(
            {
                "from": m.get("from", ""),
                "subject": subj,
                "why": why,
                "urgency": "high",
                "is_bill": True,
                "is_rent": m.get("is_rent", False),
                "is_credit_card": m.get("is_credit_card", False),
                "category": cat,
                "category_label": m.get("category_label", CATEGORY_LABELS.get(cat, "Bill due")),
                # Preserve body-read enrichment so the amount/due/payee survive triage.
                "amount": m.get("amount", ""),
                "minimum": m.get("minimum", ""),
                "due_date": m.get("due_date", ""),
                "payee": m.get("payee", ""),
                "account_tail": m.get("account_tail", ""),
            }
        )
    passthrough_why = {
        "venmo": "transaction alert — no payment task",
        "transfer": "money moved — FYI, no task",
        "statement": "statement available — FYI, nothing due",
        "housing_inquiry": "lease or listing inquiry — follow up if needed",
        "payment_received": "money in — FYI only",
    }
    for m in passthrough:
        cat = m.get("category", "")
        _add(
            {
                "from": m.get("from", ""),
                "subject": m.get("subject", ""),
                "why": passthrough_why.get(cat, ""),
                "urgency": "med" if cat == "housing_inquiry" else "low",
                "is_bill": False,
                "category": cat,
                "category_label": m.get("category_label", CATEGORY_LABELS.get(cat, cat)),
                "payee": m.get("payee", ""),
            }
        )
    for m in triaged:
        m.setdefault("category_label", CATEGORY_LABELS.get(m.get("category", ""), "Review"))
        _add(m)
    # Bills are _add-ed first, so they're never truncated; raise the cap so a busy
    # inbox doesn't drop a real bill behind a wall of action items.
    return out[:18]


def bill_tasks_from_emails(mails: list[dict], target: dt.date) -> list[str]:
    _ = target
    tasks: list[str] = []
    seen: set[str] = set()
    for m in mails:
        if not m.get("is_bill"):
            continue
        cat = m.get("category", "")
        if cat not in ("bill_rent", "bill_cc", "bill_other"):
            continue
        payee = m.get("payee") or _bill_payee(m)
        subj = m.get("subject", "").strip()[:70]
        tail = m.get("account_tail", "")
        # Tail in the key so two cards from one issuer both produce a task.
        key = f"{payee}:{cat}:{tail}"
        if key in seen:
            continue
        seen.add(key)
        head = {"bill_rent": "Pay rent", "bill_cc": "Pay credit card"}.get(cat, "Pay bill")
        who = f"{payee} …{tail}" if tail and cat == "bill_cc" else payee
        amt, mn, due = m.get("amount", ""), m.get("minimum", ""), m.get("due_date", "")
        if amt or mn or due:
            parts = [amt] if amt else []
            if mn and mn != amt:
                parts.append(f"min {mn}")
            if due:
                parts.append(f"due {due}")
            tasks.append(f"{head} — {who} ({', '.join(parts) or 'amount in email'})")
        else:
            tasks.append(f"{head} — {who}: {subj}")
    return tasks[:8]


def emails_by_category(mails: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {
        "bill_rent": [],
        "bill_cc": [],
        "bill_other": [],
        "venmo": [],
        "transfer": [],
        "statement": [],
        "housing_inquiry": [],
        "payment_received": [],
        "action": [],
    }
    for m in mails:
        cat = m.get("category", "action_candidate")
        if cat == "bill_rent":
            groups["bill_rent"].append(m)
        elif cat == "bill_cc":
            groups["bill_cc"].append(m)
        elif cat == "bill_other" or m.get("is_bill"):
            groups["bill_other"].append(m)
        elif cat == "venmo":
            groups["venmo"].append(m)
        elif cat == "transfer":
            groups["transfer"].append(m)
        elif cat == "statement":
            groups["statement"].append(m)
        elif cat == "housing_inquiry":
            groups["housing_inquiry"].append(m)
        elif cat == "payment_received":
            groups["payment_received"].append(m)
        elif not m.get("is_bill"):
            groups["action"].append(m)
    return groups


def payment_emails(mails: list[dict]) -> list[dict]:
    return [m for m in mails if m.get("is_bill")]


def load_calendar(anchor: dt.datetime, target: dt.date) -> tuple[list[dict], list[str]]:
    events = calendar_events(anchor)
    seeds = trip_journal_seeds(events, target)
    return events, seeds


def load_gmail(
    target: dt.date,
    model: str,
    ollama_url: str,
) -> tuple[list[dict], list[str]]:
    raw = candidate_emails()
    if not raw:
        return [], []
    mails = triage_emails(raw, model, ollama_url)
    return mails, bill_tasks_from_emails(mails, target)


def events_on_date(events: list[dict], day: dt.date) -> list[dict]:
    return [e for e in events if e["start"].date() == day]


def events_in_range(
    events: list[dict],
    start: dt.date,
    end: dt.date,
) -> list[dict]:
    return [e for e in events if start <= e["start"].date() <= end]


def upcoming_trips(
    events: list[dict],
    today: dt.date,
    within_days: int = CALENDAR_LOOKAHEAD_DAYS,
) -> list[dict]:
    end = today + dt.timedelta(days=within_days)
    trips: list[dict] = []
    for e in events:
        if not e.get("is_trip"):
            continue
        d = e["start"].date()
        if today <= d <= end:
            trips.append(e)
    return trips


def trip_prep_tasks(events: list[dict], now: dt.datetime) -> list[str]:
    tomorrow = now.date() + dt.timedelta(days=1)
    tasks: list[str] = []
    for e in events:
        if e["is_trip"] and e["start"].date() == tomorrow:
            tasks.append(f"Prep / pack for tomorrow: {e['summary']}")
    return tasks


def trip_pack_tasks(events: list[dict], today: dt.date) -> list[str]:
    in_two = today + dt.timedelta(days=2)
    tasks: list[str] = []
    for e in events:
        if e["is_trip"] and e["start"].date() == in_two:
            tasks.append(f"Start packing list for {e['summary']} (in 2 days)")
    return tasks


_TRIP_STOPWORDS = {
    "flight", "train", "trip", "travel", "the", "stay", "drive", "car", "bus",
    "return", "from", "airport", "to", "at", "for", "and", "with", "via",
    "dl", "ua", "aa", "wn", "b6", "nk", "as",
}


def _trip_terms(summary: str) -> list[str]:
    """Distinctive words (usually the destination) from a trip's title."""
    return [w for w in re.findall(r"[a-z]{3,}", summary.lower()) if w not in _TRIP_STOPWORDS]


def _recent_journal_text(days: int = 12) -> str:
    """Lowercased recent Journal sections — used to avoid re-prompting a topic
    you've already written about (the journaling 'grace period')."""
    try:
        import vault
    except Exception:  # noqa: BLE001
        return ""
    out: list[str] = []
    for note in vault.recent_notes(days + 2):
        try:
            out.append(vault.extract_section(vault.read_note(note), "📓 Journal"))
        except Exception:  # noqa: BLE001
            continue
    return " ".join(out).lower()


def trip_journal_seeds(events: list[dict], today: dt.date) -> list[str]:
    seeds: list[str] = []
    journal = _recent_journal_text()
    tomorrow = today + dt.timedelta(days=1)
    for e in events:
        if not e.get("is_trip"):
            continue
        # Already journaled about this trip? Don't nag again (grace period).
        terms = _trip_terms(e.get("summary", ""))
        if terms and any(t in journal for t in terms):
            continue
        d = e["start"].date()
        if d == today:
            seeds.append(
                f"JOURNAL_HINT: Trip today — {e['summary']}. "
                "What do you want to remember or feel going in?"
            )
        elif d == tomorrow:
            seeds.append(
                f"JOURNAL_HINT: Tomorrow's trip — {e['summary']}. "
                "What are you looking forward to or nervous about?"
            )
        elif d <= today + dt.timedelta(days=3):
            days_away = (d - today).days
            seeds.append(
                f"JOURNAL_HINT: Trip in {days_away}d — {e['summary']}. "
                "Anything you want to prep mentally?"
            )
    return seeds[:3]


def _coach_calendar_lines(events: list[dict], target: dt.date, max_lines: int) -> list[str]:
    """Calendar lines for coach: today/tomorrow/trips/non-routine — not every Work block."""
    lines: list[str] = []
    today_ev = events_on_date(events, target)
    tomorrow = target + dt.timedelta(days=1)
    tomo_ev = events_on_date(events, tomorrow)

    for e in today_ev:
        if e.get("is_routine"):
            continue
        if e["all_day"]:
            lines.append(f"- Today (all-day): {e['summary']}")
        else:
            loc = f" @ {e['location']}" if e.get("location") else ""
            lines.append(f"- Today: {e['summary']} {e['start']:%I:%M %p}{loc}")

    for e in tomo_ev:
        if e.get("is_routine"):
            continue
        tag = "Tomorrow (trip)" if e.get("is_trip") else "Tomorrow"
        if e["all_day"]:
            lines.append(f"- {tag} (all-day): {e['summary']}")
        else:
            lines.append(f"- {tag}: {e['summary']} {e['start']:%I:%M %p}")

    for e in upcoming_trips(events, target):
        d = e["start"].date()
        if d <= tomorrow:
            continue
        days_away = (d - target).days
        lines.append(f"- Trip in {days_away}d: {e['summary']}")

    future_end = target + dt.timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    notable = [
        e
        for e in events_in_range(events, target + dt.timedelta(days=2), future_end)
        if not e.get("is_trip") and not e.get("is_routine")
    ]
    for e in notable[:5]:
        days_away = (e["start"].date() - target).days
        lines.append(f"- In {days_away}d: {e['summary']}")

    return lines[:max_lines]


def format_coach_context(
    events: list[dict],
    mails: list[dict],
    target: dt.date,
    journal_seeds: list[str] | None = None,
    max_lines: int = 18,
) -> str:
    lines = _coach_calendar_lines(events, target, max_lines=10)
    groups = emails_by_category(mails)

    for m in groups["bill_rent"][:2]:
        who = _short_from(m.get("from", ""))
        lines.append(f'- BILL (rent): {who} — "{m.get("subject", "")}"')
    for m in groups["bill_cc"][:2]:
        who = _short_from(m.get("from", ""))
        lines.append(f'- BILL (card): {who} — "{m.get("subject", "")}"')
    for m in groups["bill_other"][:2]:
        who = _short_from(m.get("from", ""))
        lines.append(f'- BILL: {who} — "{m.get("subject", "")}"')

    for m in groups["housing_inquiry"][:2]:
        who = _short_from(m.get("from", ""))
        lines.append(f'- Housing inquiry: {who} — "{m.get("subject", "")}"')
    for m in groups["venmo"][:2]:
        who = _short_from(m.get("from", ""))
        label = m.get("category_label", "Venmo")
        lines.append(f'- {label}: {who} — "{m.get("subject", "")}"')
    for m in groups["payment_received"][:1]:
        who = _short_from(m.get("from", ""))
        lines.append(f'- Payment received: {who} — "{m.get("subject", "")}"')

    for m in groups["action"][:4]:
        who = _short_from(m.get("from", ""))
        label = m.get("category_label") or m.get("category", "reply")
        why = m.get("why", "")
        extra = f" — {why}" if why else ""
        lines.append(f'- Email [{label}]: {who} — "{m.get("subject", "")}"{extra}')

    if journal_seeds:
        lines.extend(f"- {s}" for s in journal_seeds)

    if not lines:
        return ""
    capped = lines[:max_lines]
    return (
        "EXTERNAL (Calendar −14d/+7d, Gmail 14d — ground journal_prompts and tomorrow; "
        "bill tasks only if in REQUIRED):\n" + "\n".join(capped)
    )


def _render_mail_line(m: dict) -> str:
    who = m.get("payee") or _short_from(m.get("from", ""))
    tail = m.get("account_tail", "")
    if tail and m.get("category") == "bill_cc":
        who = f"{who} …{tail}"
    subj = m.get("subject", "")
    label = m.get("category_label") or CATEGORY_LABELS.get(
        m.get("category", ""), m.get("category", "Review")
    )
    # Bills lead with the numbers read from the body: balance, then minimum, then due.
    if m.get("is_bill"):
        amt, mn, due = m.get("amount", ""), m.get("minimum", ""), m.get("due_date", "")
        parts = [amt] if amt else []
        if mn and mn != amt:
            parts.append(f"min {mn}")
        if due:
            parts.append(f"due {due}")
        # Never silently fall back to just the title — say the number is missing so
        # it's obvious the statement must be opened, not that the bill is free.
        money = ", ".join(parts) if parts else "amount not in email — open statement"
        extra = f" — **{money}**"
    else:
        why = m.get("why", "")
        extra = f" — {why}" if why else ""
    return f'- [ ] **{who}** [{label}] — "{subj}"{extra}'


def render_reminders_markdown(
    events: list[dict],
    mails: list[dict],
    target: dt.date,
    extra_lines: list[str] | None = None,
    ignored: set[tuple[str, str]] | None = None,
    receipt_lines: list[str] | None = None,
) -> str:
    # Honor the "ignore" convention: drop mail the user told us to stop showing.
    n_before = len(mails)
    if ignored:
        from rules import is_ignored_mail

        mails = [m for m in mails if not is_ignored_mail(m, ignored)]
    n_ignored = n_before - len(mails)

    lines = [
        f"> Calendar −{CALENDAR_LOOKBACK_DAYS}d / +{CALENDAR_LOOKAHEAD_DAYS}d · "
        f"Gmail {GMAIL_LOOKBACK_DAYS}d. Regenerated each run."
        + (f" {n_ignored} ignored." if n_ignored else ""),
        "",
    ]
    today_ev = events_on_date(events, target)
    tomorrow = target + dt.timedelta(days=1)
    tomo_ev = events_on_date(events, tomorrow)

    past_start = target - dt.timedelta(days=min(7, CALENDAR_LOOKBACK_DAYS))
    past_ev = [
        e
        for e in events_in_range(events, past_start, target - dt.timedelta(days=1))
        if not e.get("is_routine")
    ]
    if past_ev:
        lines.append("**📆 Past week (notable)**")
        for e in past_ev[-8:]:
            lines.append(f"- {e['start'].strftime('%a %b %d')}  {e['summary']}")
        lines.append("")

    if today_ev:
        lines.append("**📅 Today**")
        for e in today_ev:
            if e["all_day"]:
                lines.append(f"- ⏳ All-day: {e['summary']}")
            else:
                loc = f" — {e['location']}" if e.get("location") else ""
                t = e["start"].strftime("%H:%M")
                tag = " (routine)" if e.get("is_routine") else ""
                lines.append(f"- {t}  {e['summary']}{loc}{tag}")
        lines.append("")

    groups = emails_by_category(mails)
    bill_all = groups["bill_rent"] + groups["bill_cc"] + groups["bill_other"]
    # Only show bills inside the lead window (or overdue/undated) — a statement that
    # landed three weeks early stays quiet until it's actually worth paying.
    bill_all = [m for m in bill_all if bill_is_due_soon(m.get("due_date", ""), target)]
    if bill_all:
        lines.append("**💳 Bills due**")
        for m in bill_all:
            lines.append(_render_mail_line(m))
        lines.append("")

    if groups["housing_inquiry"]:
        lines.append("**🏠 Housing inquiries**")
        for m in groups["housing_inquiry"]:
            lines.append(_render_mail_line(m))
        lines.append("")

    money_talks = (
        groups["venmo"] + groups["transfer"] + groups["statement"] + groups["payment_received"]
    )
    if money_talks:
        lines.append("**💸 Money talks (transfers, Venmo, deposits)**")
        for m in money_talks:
            lines.append(_render_mail_line(m))
        lines.append("")

    if groups["action"]:
        lines.append("**📬 Needs a reply / action**")
        for m in groups["action"]:
            lines.append(_render_mail_line(m))
        lines.append("")

    if tomo_ev:
        lines.append("**🗓 Tomorrow (heads-up)**")
        for e in tomo_ev:
            when = "All-day" if e["all_day"] else e["start"].strftime("%H:%M")
            trip = " [trip]" if e.get("is_trip") else ""
            lines.append(f"- {when}  {e['summary']}{trip}")
        lines.append("")

    trips = upcoming_trips(events, target)
    future_trips = [t for t in trips if t["start"].date() > tomorrow]
    if future_trips:
        lines.append("**✈️ Upcoming trips**")
        for e in future_trips:
            d = e["start"].date()
            days_away = (d - target).days
            when = e["start"].strftime("%a %b %d") if not e["all_day"] else d.strftime("%a %b %d")
            lines.append(f"- In {days_away}d ({when}): {e['summary']}")
        lines.append("")

    future_end = target + dt.timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    upcoming = [
        e
        for e in events_in_range(events, target + dt.timedelta(days=2), future_end)
        if not e.get("is_trip") and not e.get("is_routine")
    ]
    if upcoming:
        lines.append(f"**📅 Coming up (next {CALENDAR_LOOKAHEAD_DAYS}d)**")
        for e in upcoming[:10]:
            days_away = (e["start"].date() - target).days
            when = e["start"].strftime("%a %H:%M") if not e["all_day"] else e["start"].strftime("%a")
            lines.append(f"- In {days_away}d ({when}): {e['summary']}")
        lines.append("")

    if extra_lines:
        lines.append("**💬 From your messages**")
        for line in extra_lines:
            lines.append(f"- {line}")
        lines.append("")

    if receipt_lines:
        lines.append("**🧾 Recent receipts**")
        lines.extend(receipt_lines)
        lines.append("")

    body = "\n".join(lines).strip()
    return body or "- (nothing pulled — connect Google or check credentials.json)"


if __name__ == "__main__":
    now = dt.datetime.now()
    print(
        f"Calendar: −{CALENDAR_LOOKBACK_DAYS}d / +{CALENDAR_LOOKAHEAD_DAYS}d "
        f"| Gmail: {GMAIL_LOOKBACK_DAYS}d"
    )
    for ev in calendar_events(now):
        tag = ev["start"].date().isoformat()
        trip = " [TRIP]" if ev["is_trip"] else ""
        print(f"[{tag}]{trip} {ev['start']:%a %H:%M}  {ev['summary']}")
    print("---")
    raw = candidate_emails(10)
    print(f"Candidates after noise filter: {len(raw)}")
    for m in raw[:8]:
        print(f"  [{m.get('category')}] {_short_from(m['from'])} — {m['subject'][:50]}")
