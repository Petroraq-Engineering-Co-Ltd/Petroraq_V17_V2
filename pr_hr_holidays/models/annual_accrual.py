"""Calendar-day entitlement calculations, independent of remaining leave."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta


def next_anniversary(start, anchor=None):
    anchor = anchor or start
    return anchor + relativedelta(years=start.year - anchor.year + 1)


def earned_entitlement(start, end, target, entitlement, earning_days, gain_time):
    # End-of-period credits are available the following morning.
    elapsed = (min(target, end + timedelta(days=1)) - start).days
    if gain_time == "start" and target <= end:
        elapsed += 1
    return entitlement * min(max(elapsed, 0), earning_days) / earning_days


def lifetime_entitlement(start, end, target, entitlement, earning_days, gain_time):
    """Gross earned across repeating service years; end is an inclusive cutoff."""
    credit_until = target + timedelta(days=1 if gain_time == "start" else 0)
    if end:
        credit_until = min(credit_until, end + timedelta(days=1))
    if credit_until <= start:
        return 0.0
    years = max(credit_until.year - start.year, 0)
    anniversary = start + relativedelta(years=years)
    if anniversary > credit_until:
        years -= 1
        anniversary = start + relativedelta(years=years)
    elapsed = (credit_until - anniversary).days
    return entitlement * years + entitlement * min(elapsed, earning_days) / earning_days
