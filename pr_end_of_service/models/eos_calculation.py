from dateutil.relativedelta import relativedelta


MIN_EOS_SERVICE_YEARS = 1.0
FIRST_TIER_YEARS = 5.0
FIRST_TIER_MONTHS_PER_YEAR = 0.5
SECOND_TIER_MONTHS_PER_YEAR = 1.0


def get_service_duration(start_date, end_date):
    if not start_date or not end_date or end_date < start_date:
        return {
            "years": 0,
            "months": 0,
            "days": 0,
            "service_years": 0.0,
            "period_display": "0 years, 0 months, 0 days",
        }

    diff = relativedelta(end_date, start_date)
    service_years = diff.years + (diff.months / 12.0) + (diff.days / 365.0)
    return {
        "years": diff.years,
        "months": diff.months,
        "days": diff.days,
        "service_years": service_years,
        "period_display": "%s years, %s months, %s days" % (diff.years, diff.months, diff.days),
    }


def get_eosb_breakdown(monthly_salary, service_years, completed_years=None):
    monthly_salary = monthly_salary or 0.0
    service_years = service_years or 0.0
    completed_years = int(completed_years if completed_years is not None else service_years)
    if monthly_salary <= 0.0:
        return {
            "eligible": False,
            "amount": 0.0,
            "status": "not_eligible",
            "message": "Monthly salary is required before EOSB can be calculated.",
            "formula": "EOSB = 0 because monthly salary is not set.",
            "completed_years_used": completed_years,
        }
    if completed_years < MIN_EOS_SERVICE_YEARS:
        return {
            "eligible": False,
            "amount": 0.0,
            "status": "not_eligible",
            "message": "Employee is not eligible for EOSB before completing 1 full year of service.",
            "formula": "EOSB = 0 because no full service year is completed.",
            "completed_years_used": completed_years,
        }
    if completed_years <= FIRST_TIER_YEARS:
        amount = monthly_salary * FIRST_TIER_MONTHS_PER_YEAR * completed_years
        formula = "%.2f x 0.5 x %s completed year(s)" % (monthly_salary, completed_years)
    else:
        remaining_years = completed_years - int(FIRST_TIER_YEARS)
        amount = (
            monthly_salary * FIRST_TIER_MONTHS_PER_YEAR * FIRST_TIER_YEARS
            + monthly_salary * SECOND_TIER_MONTHS_PER_YEAR * remaining_years
        )
        formula = "(%.2f x 0.5 x 5) + (%.2f x %s completed year(s) after 5)" % (
            monthly_salary,
            monthly_salary,
            remaining_years,
        )
    return {
        "eligible": True,
        "amount": amount,
        "status": "eligible",
        "message": "Employee is eligible for EOSB.",
        "formula": formula,
        "completed_years_used": completed_years,
    }
