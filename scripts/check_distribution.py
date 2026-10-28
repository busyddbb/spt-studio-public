"""Fail before sharing if private runtime files or obvious credentials are present.

Checks a fresh source/export folder. Never inspect a person's active browser profile.
"""
from __future__ import annotations
import argparse,json,re,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOKEN_PATTERNS=[
    re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{35,}'),
    re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{28,}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]
BLOCKED_NAMES={'.env','Cookies','Login Data','Web Data','provider.json','settings.local.json'}
BLOCKED_PARTS={'data','edge-profile','chrome-profile','browser-profiles','.venv','venv','__pycache__','.cache','build'}
TEXT_SUFFIXES={'.py','.md','.txt','.js','.cjs','.json','.yaml','.yml','.swift','.html','.css','.bat','.sh','.command'}

def check(root:Path,tracked:bool=False)->list[str]:
    problems=[]
    if tracked:
        out=subprocess.check_output(['git','ls-files','-z'],cwd=root)
        paths=[root/p.decode('utf-8') for p in out.split(b'\0') if p]
    else:
        paths=[p for p in root.rglob('*') if p.is_file() or p.is_symlink()]
    for p in paths:
        rel=p.relative_to(root)
        if '.git' in rel.parts:continue
        if p.is_symlink():
            problems.append(f'{rel}: symbolic link is not allowed in the source release');continue
        if any(part in BLOCKED_PARTS for part in rel.parts) or p.name in BLOCKED_NAMES or p.suffix in {'.sqlite','.sqlite3','.db','.pem','.key','.p12','.pfx'} or p.name.startswith('.env.'):
            problems.append(f'{rel}: private runtime/cache file');continue
        if rel.parts[0]=='工作区' and p.name not in {'README.md','AGENTS.md','.gitkeep'}:
            problems.append(f'{rel}: workspace must be empty');continue
        if p.suffix not in TEXT_SUFFIXES:continue
        text=p.read_text(encoding='utf-8-sig')
        if any(pattern.search(text) for pattern in TOKEN_PATTERNS):problems.append(f'{rel}: credential pattern found')
        personal=[('/Users/'+'Ben'),('/Users/'+'ben'),('Busy'+'爸爸'),('amazing'+'kitchen101'),('623c555c'+'00000000100052a4')]
        if any(value in text for value in personal):problems.append(f'{rel}: private identity/path found')
        if rel.as_posix()=='app/projects.json' and json.loads(text) not in ([],{'projects':[]}):problems.append(f'{rel}: project list is not empty')
        if rel.as_posix()=='spt/server/dashboard_sources.json':
            value=json.loads(text)
            if value.get('news') or value.get('research'):problems.append(f'{rel}: saved private sources are present')
    return problems

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--tracked',action='store_true');args=parser.parse_args()
    problems=check(args.root.resolve(),args.tracked)
    if problems:
        print('\n'.join(problems),file=sys.stderr);return 1
    print('Distribution privacy check passed. No runtime data, personal identities, or credential patterns found.');return 0
if __name__=='__main__':raise SystemExit(main())
