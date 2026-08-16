from solution import normalize_words
assert normalize_words('  Hello   WORLD  ') == 'hello world'
assert normalize_words('') == ''
