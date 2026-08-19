from solution import stable_groups
x=['ant','ape','bat','bee','cat']
assert stable_groups(x, lambda s:s[0])==[['ant','ape'],['bat','bee'],['cat']]
