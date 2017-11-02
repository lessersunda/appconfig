# helpers.py - one-trick ponies

import os
import sys
import datetime

import pytz

__all__ = ['caller_dirname', 'duplicates', 'strfnow']


def caller_dirname(steps=1):
    frame = sys._getframe(steps + 1)

    try:
        path = os.path.dirname(frame.f_code.co_filename)
    finally:
        del frame

    return os.path.basename(path)


def duplicates(iterable):
    """Return duplicated (hashable) items from iterable preservig order.

    >>> duplicates([1, 2, 2, 3, 1])
    [2, 1]
    """
    seen = set()
    return [i for i in iterable if i in seen or seen.add(i)]


def strfnow(add_hours=0, timezone='Europe/Berlin', format_='%Y-%m-%d %H:%M %Z%z'):
    """

    >>> assert strfnow() < strfnow(add_hours=2)
    """
    dt = datetime.datetime.utcnow()
    if add_hours:
        dt += datetime.timedelta(hours=add_hours)
    local_dt = pytz.utc.localize(dt).astimezone(pytz.timezone(timezone))
    return local_dt.strftime(format_)