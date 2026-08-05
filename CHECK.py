"""Run from inside your metfraa-portal folder:   python CHECK.py

Finishes the install and verifies it. Safe to run more than once.
Handles the case where the zip was extracted into the repo folder itself.
"""
import pathlib, shutil, sys

repo = pathlib.Path.cwd()
if not (repo / "app" / "main.py").is_file():
    sys.exit(f"ERROR: {repo} is not the metfraa-portal folder. cd into it first.")

dest = repo / "app" / "static" / "ehs"
stray = repo / "ehs-static"

# 1. If the frontend is still only at the repo root, move it into place.
if stray.is_dir() and not (dest / "css").is_dir():
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(stray, dest)
    print("Copied ehs-static/ -> app/static/ehs/")

# 2. Remove the stray copy at the repo root.
if stray.is_dir():
    shutil.rmtree(stray)
    print("Removed stray ehs-static/ from the repo root")

# 3. Verify everything the app needs at boot.
print("\n--- verification ---")
ok = True
for sub, want in (("css", 6), ("js", 8), ("img", 1)):
    n = len(list((dest / sub).glob("*"))) if (dest / sub).is_dir() else 0
    print(f"  app/static/ehs/{sub:4}  {n} files (expect {want})")
    ok &= n == want
html = len(list(dest.glob("*.html"))) if dest.is_dir() else 0
print(f"  app/static/ehs/       {html} html pages (expect 9)")
ok &= html == 9

for f, needle in (("app/routes/ehs_ui.py", "Slices 3-5"),
                  ("app/main.py", "EHS static dir missing")):
    p = repo / f
    good = p.is_file() and needle in p.read_text(encoding="utf-8", errors="ignore")
    print(f"  {f:26} {'up to date' if good else 'OLD OR MISSING'}")
    ok &= good

print("\nAll good. Now run:\n"
      "  git add -A\n"
      '  git commit -m "EHS parity: fix asset location, guard static mounts"\n'
      "  git push" if ok else
      "\nSomething is off — send Claude everything printed above.")
