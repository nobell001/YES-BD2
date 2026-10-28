"""Sample for tests/test_count_read_guard.py: lines 4 and 9 are hand-written counts."""
import re

USED = re.compile(r"(\d+)\s*/\s*(\d+)")
# 不是次数：日期
DATE = re.compile(r"(20\d\d)/(\d{1,2})/(\d{1,2})")
WORD = re.compile(r"次数")
KEY_DIGITS = 2
KEYS = re.match(rf"0[/／]\d{{1,{KEY_DIGITS}}}", "0/10")
