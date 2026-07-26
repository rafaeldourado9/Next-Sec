"""Rate limiter compartilhado — singleton usado por main.py e routers."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("ENVIRONMENT", "production") != "testing",
)
