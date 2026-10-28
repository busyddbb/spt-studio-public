"""Run the portable UI contracts with the same file list on Windows and macOS."""
from pathlib import Path
import subprocess,sys
root=Path(__file__).resolve().parents[1]
files=sorted((root/'spt/ui/tests').glob('*.test.cjs'))+[root/'tests/frontend_state.test.cjs',root/'tests/desk_browser.test.cjs']
raise SystemExit(subprocess.call(['node','--test',*[str(p) for p in files]],cwd=root))
