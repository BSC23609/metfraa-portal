"""Run this from inside your metfraa-portal folder:  python INSTALL.py

Puts every file exactly where it belongs, then checks it. This exists because
copying by hand put the frontend at <repo>/ehs-static/ instead of
<repo>/app/static/ehs/, which crashed the whole portal on boot.
"""
import pathlib, shutil, sys

here = pathlib.Path(__file__).resolve().parent
repo = pathlib.Path.cwd()

if not (repo / "app" / "main.py").is_file():
    sys.exit(f"ERROR: {repo} is not the metfraa-portal folder (no app/main.py).\n"
             "cd into the repo first, then run this again.")

# 1. Frontend -> app/static/ehs/
dest = repo / "app" / "static" / "ehs"
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(here / "ehs-static", dest)

# 2. Python files
for rel in ("app/main.py", "app/routes/ehs_ui.py", "app/routes/ehs.py"):
    shutil.copy2(here / rel, repo / rel)

# 3. Clean up a previous bad copy at the repo root
stray = repo / "ehs-static"
if stray.is_dir():
    shutil.rmtree(stray)
    print("Removed stray ehs-static/ from the repo root")

# 4. Verify
ok = True
for sub in ("css", "js", "img"):
    n = len(list((dest / sub).glob("*")))
    print(f"  app/static/ehs/{sub}/  {n} files")
    if n == 0:
        ok = False
html = len(list(dest.glob("*.html")))
print(f"  app/static/ehs/       {html} html pages")
if html != 9:
    ok = False
print("\nOK — now: git add -A && git commit -m 'EHS parity: fix asset location' && git push"
      if ok else "\nSOMETHING IS WRONG — tell Claude what this printed.")
