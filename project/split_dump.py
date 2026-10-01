import os, re, time

SRC = r"H:\kanishka\Cafeteria Order Data.sql"
OUT = r"H:\kanishka\split"
os.makedirs(OUT, exist_ok=True)

pat = re.compile(rb"^-- (Table structure for table|Structure for view|Stand-in structure for view) `(.+)`")

sizes = {}
name = "_header"
cur = open(os.path.join(OUT, name + ".sql"), "wb")
t0 = time.time()

with open(SRC, "rb", buffering=16 * 1024 * 1024) as f:
    for line in f:
        m = pat.match(line)
        if m:
            cur.close()
            kind, tbl = m.group(1).decode(), m.group(2).decode()
            name = ("view_" if "view" in kind else "") + tbl
            cur = open(os.path.join(OUT, name + ".sql"), "ab")
            print(f"[{time.time()-t0:6.0f}s] {name}", flush=True)
        elif line.startswith(b"-- Indexes for dumped tables"):
            cur.close()
            name = "_tail"
            cur = open(os.path.join(OUT, name + ".sql"), "ab")
        cur.write(line)
        sizes[name] = sizes.get(name, 0) + len(line)
cur.close()

print("\n=== TABLE SIZES (MB), largest first ===")
for k, v in sorted(sizes.items(), key=lambda x: -x[1]):
    print(f"{v/1e6:10.1f}  {k}")