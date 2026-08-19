from solution import fib
assert [fib(i) for i in range(11)] == [0,1,1,2,3,5,8,13,21,34,55]
try: fib(-1)
except ValueError: pass
else: raise AssertionError('negative')
