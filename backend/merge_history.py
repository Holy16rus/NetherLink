import json
import sys

old = json.load(open(sys.argv[1]))
new = json.load(open(sys.argv[2]))
for k, v in new.items():
    old[k] = (old.get(k, []) + v)[-5:]
old = {k: v for k, v in old.items() if len(v) >= 1}
json.dump(old, open("proxy-history.json", "w"), ensure_ascii=False)
