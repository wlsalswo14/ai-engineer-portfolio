from solution import roman_to_int
assert roman_to_int('MCMXCIV')==1994
assert roman_to_int('III')==3
for x in ('IIII','IC',''):
 try: roman_to_int(x)
 except ValueError: pass
 else: raise AssertionError(x)
