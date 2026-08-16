from solution import parse_duration
assert parse_duration('2h 3m 4s')==7384
assert parse_duration('45m')==2700
for x in ('', '3x', '-1s'):
 try: parse_duration(x)
 except ValueError: pass
 else: raise AssertionError(x)
