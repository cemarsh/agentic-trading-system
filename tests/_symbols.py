"""OCC option symbols for test fixtures, always with a live expiry.

Fixtures used to hard-code dates like KTOS260904P00052000. Any code path that compares
the expiry to date.today() (the position manager skips DTE < 0) then starts failing
on the calendar rather than on a code change — that is how test_stale_order_reprice
broke after 2026-09-04. Build symbols here instead.
"""

from datetime import date, timedelta


def expiry(days_out: int = 30) -> str:
    """YYMMDD `days_out` days from today."""
    return f"{date.today() + timedelta(days=days_out):%y%m%d}"


def occ(root: str, right: str = "P", strike: float = 52.0, days_out: int = 30) -> str:
    """ROOT + YYMMDD + C/P + strike x1000 as 8 digits, e.g. occ("KTOS") -> KTOS2610..P00052000."""
    return f"{root}{expiry(days_out)}{right}{round(strike * 1000):08d}"
