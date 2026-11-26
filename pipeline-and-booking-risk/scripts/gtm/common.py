"""Shared helpers: number parsing, display formatting, the number register that
gives every figure in generated prose a provenance path, path resolution over
the payload, and hashing."""
import datetime as dt
import hashlib
import json
import math
import re

MINUS = "−"


class BuildError(Exception):
    pass


# ----------------------------------------------------------------- parsing

def to_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v).strip()[:10])


def to_num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    t = str(v).strip().replace(",", "")
    if t == "" or t.lower() in ("none", "null", "nan"):
        return None
    return float(t)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def safe_div(a, b):
    if is_num(a) and is_num(b) and b != 0:
        return a / b
    return None


def r2(v):
    return None if v is None else round(v, 2)


def r4(v):
    """Fractions (percentages, shares, margins) keep four decimals."""
    return None if v is None else round(v, 4)


def month_add(d, n):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, 1)


def month_end(d):
    return month_add(d, 1) - dt.timedelta(days=1)


# ----------------------------------------------------------------- fiscal calendar
# Yes Energy's fiscal year is the calendar year, 1 January to 31 December, named by that year:
# January to December 2026 is FY2026. Fiscal Q1 = Jan-Mar, Q2 = Apr-Jun, Q3 = Jul-Sep, Q4 = Oct-Dec.
FY_START_MONTH = 1


def fy_of(d):
    """Fiscal year of a date, named by the year it ends."""
    return d.year + 1 if FY_START_MONTH > 1 and d.month >= FY_START_MONTH else d.year


def fy_start(d):
    """First month of the fiscal year containing d."""
    return dt.date(fy_of(d) - (1 if FY_START_MONTH > 1 else 0), FY_START_MONTH, 1)


def fiscal_quarter(d):
    return (d.month - FY_START_MONTH) % 12 // 3 + 1


def qstart(d):
    """First month of the fiscal quarter containing d."""
    return month_add(dt.date(d.year, d.month, 1), -((d.month - FY_START_MONTH) % 3))


def qlabel(d):
    """Fiscal quarter label, sortable as text: FY2026-Q3 (July to September 2026)."""
    return f"FY{fy_of(d)}-Q{fiscal_quarter(d)}"


def is_quarter_end(d):
    return (d.month - FY_START_MONTH) % 3 == 2


def slug(s):
    # "+" is meaningful in product names: "Product+" must not collide with "Product"
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower().replace("+", " plus ")).strip("-") or "x"


# ---------------------------------------------------------------- formatting
# Display conventions (shared with the renderer): money below $1m as $NNNk,
# $1m to $10m as $N.NNmm, above as $N.Nmm; negatives use U+2212; signed forms
# carry an explicit "+". Percent one decimal; basis points as integers.

def money(v, sign=False, prefix="$"):
    if not is_num(v):
        return "n/a"
    a = abs(v)
    if a < 1000:
        s = f"{prefix}{a:,.0f}"
    elif a < 10_000:
        s = f"{prefix}{a / 1e3:.1f}k"
    elif a < 1e6:
        s = f"{prefix}{a / 1e3:,.0f}k"
    elif a < 10e6:
        s = f"{prefix}{a / 1e6:.2f}mn"
    elif a < 100e6:
        s = f"{prefix}{a / 1e6:.1f}mn"
    else:
        s = f"{prefix}{a / 1e6:,.0f}mn"
    if v < 0 and s not in (f"{prefix}0", f"{prefix}0k", f"{prefix}0.0k"):
        return MINUS + s
    return ("+" + s) if (sign and v > 0) else s


def pct(v, sign=False, dec=1):
    """v is a fraction (0.123 -> 12.3%)."""
    if not is_num(v):
        return "n/a"
    s = f"{abs(v) * 100:.{dec}f}%"
    if v < 0 and float(s[:-1]) != 0:
        return MINUS + s
    return ("+" + s) if (sign and v > 0) else s


def bps(v):
    """v is a fraction difference (0.0123 -> +123 bps)."""
    if not is_num(v):
        return "n/a"
    b = round(v * 10000)
    return (("+" if b > 0 else MINUS if b < 0 else "") + f"{abs(b):,} bps")


def count(n):
    return f"{int(n):,}"


# --------------------------------------------------------- number register

MONEY_RE = re.compile(r"[+−-]?\$[\d,]+(?:\.\d+)?(?:k|mn|mm|m|bn)?")
PCT_RE = re.compile(r"[+−-]?\d+(?:\.\d+)?%")
BPS_RE = re.compile(r"[+−-]?[\d,]+ bps")
EXEMPT_RE = re.compile(
    r"\b(19|20)\d{2}-\d{2}\b|\b(19|20)\d{2}\b|\bQ[1-4]\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (19|20)\d{2}\b"
    r"|\b\d{1,2} (of|in) \d{1,2}\b|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
    r"|\b\d{1,2}[- ](month|months|periods?|accounts?|lines?|drivers?|items?|subsidiar(y|ies)|days?)\b"
    r"|\bL[1-6]\b|\btop[- ]\d\b|\b\d{1,2} (worse|better|favourable|adverse)\b")


class Register:
    """Collects every figure placed in generated text with its payload path, so
    the validator can strip registered displays from the text and refuse any
    numeric token that remains. Mirrors the provenance discipline of the
    NetSuite variance analyzer's `numbers[]` register."""

    def __init__(self):
        self.numbers = []
        self._seen = set()

    def _put(self, display, value, kind, source):
        key = (display, source)
        if key not in self._seen:
            self._seen.add(key)
            self.numbers.append({"display": display, "value": round(value, 6) if is_num(value) else value, "kind": kind, "source": source})
        return display

    def m(self, value, source, sign=False):
        return self._put(money(value, sign), value, "money", source)

    def p(self, value, source, sign=False, dec=1):
        return self._put(pct(value, sign, dec), value, "pct", source)

    def b(self, value, source):
        return self._put(bps(value), value, "bps", source)

    def c(self, value, source):
        return self._put(count(value), value, "count", source)

    def lit(self, text, source="literal"):
        """A data string whose digits are exempt (account names, labels)."""
        return self._put(str(text), str(text), "literal", source)


def strip_registered(text, numbers):
    t = text
    for n in sorted(numbers, key=lambda x: -len(str(x["display"]))):
        t = t.replace(str(n["display"]), " ")
    return t


def unregistered_tokens(text, numbers):
    """Return money / percent / bps tokens in `text` that no register entry covers."""
    t = strip_registered(text, numbers)
    t = EXEMPT_RE.sub(" ", t)
    found = MONEY_RE.findall(t) + PCT_RE.findall(t) + BPS_RE.findall(t)
    return [f for f in found if f.strip("+-−$,") not in ("", "0")]


# ------------------------------------------------------------ path resolve

PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[([^\]]+)\]")


def resolve_path(obj, path):
    """Resolve `a.b[c].d[3]` over nested dicts/lists. `[x]` on a list picks the
    element whose `id` equals x, or the integer index when x is an integer."""
    cur = obj
    for m in PATH_TOKEN.finditer(path):
        key = m.group(1) if m.group(1) is not None else m.group(2)
        if isinstance(cur, dict):
            if key in cur:
                cur = cur[key]
            else:
                raise KeyError(path)
        elif isinstance(cur, list):
            hit = [x for x in cur if isinstance(x, dict) and str(x.get("id")) == key]
            if hit:
                cur = hit[0]
            elif re.fullmatch(r"-?\d+", key):
                cur = cur[int(key)]
            else:
                raise KeyError(path)
        else:
            raise KeyError(path)
    return cur


def json_dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def sha256_of(obj):
    return hashlib.sha256(json_dumps(obj).encode("utf-8")).hexdigest()


def mean(xs):
    xs = [x for x in xs if is_num(x)]
    return sum(xs) / len(xs) if xs else None


def median(xs):
    xs = sorted(x for x in xs if is_num(x))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def stdev(xs):
    xs = [x for x in xs if is_num(x)]
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def ols_slope(ys):
    """Least-squares slope and intercept over equally spaced points."""
    ys = [y for y in ys if is_num(y)]
    n = len(ys)
    if n < 3:
        return None, None
    xm = (n - 1) / 2
    ym = sum(ys) / n
    sxx = sum((i - xm) ** 2 for i in range(n))
    sxy = sum((i - xm) * (y - ym) for i, y in enumerate(ys))
    slope = sxy / sxx if sxx else 0.0
    return slope, ym - slope * xm
