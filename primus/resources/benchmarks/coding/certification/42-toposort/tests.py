from solution import topo_sort
assert topo_sort(['c','a','b'], [('a','c'),('b','c')])==['a','b','c']
try: topo_sort(['a','b'], [('a','b'),('b','a')])
except ValueError: pass
else: raise AssertionError('cycle')
