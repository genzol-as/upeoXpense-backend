import datetime as dt
from dateutil.relativedelta import relativedelta


WEEK = 'Weekly'; MONTH='Monthly'; YEAR='Yearly'


def period_bounds(period_type: str, ref_date: dt.date) -> tuple[dt.date, dt.date]:
    if period_type == WEEK:
       start = ref_date - dt.timedelta(days=ref_date.weekday()) # Monday start
       end = start + dt.timedelta(days=6)
    elif period_type == MONTH:
       start = ref_date.replace(day=1)
       end = (start + relativedelta(months=1)) - dt.timedelta(days=1)
    else:
        start = ref_date.replace(month=1, day=1)
        end = ref_date.replace(month=12, day=31)
    return start, end