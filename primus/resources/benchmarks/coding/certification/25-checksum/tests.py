from solution import luhn_valid
assert luhn_valid('4539 1488 0343 6467') is True
assert luhn_valid('8273 1232 7352 0569') is False
assert luhn_valid('7') is False
assert luhn_valid('12x') is False
