"""Run from inside your metfraa-portal folder:   python APPLY.py

Adds the "Main Dashboard" button to all 9 EHS page headers.
Only touches app/static/ehs/ — no Python files, no CSS, no database.
Safe to run more than once.
"""
import pathlib, shutil, sys

here = pathlib.Path(__file__).resolve().parent
repo = pathlib.Path.cwd()
if not (repo / "app" / "main.py").is_file():
    sys.exit(f"ERROR: {repo} is not the metfraa-portal folder. cd into it first.")

src, dest = here / "ehs-static", repo / "app" / "static" / "ehs"
if src.resolve() == dest.resolve():
    sys.exit("ERROR: don't extract this zip inside app/static/ehs. Extract it elsewhere.")
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(src, dest)

n = sum('app-header__btn--home' in p.read_text(encoding='utf-8') for p in dest.glob('*.html'))
print(f"  {len(list(dest.glob('*.html')))} pages installed, {n} carry the new button")
print("\nOK — now:\n  git add -A\n"
      '  git commit -m "EHS: add Main Dashboard button to header"\n  git push'
      if n == 9 else "\nSomething is off — send Claude this output.")
