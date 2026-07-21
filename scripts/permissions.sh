#!/usr/bin/env bash
# nb perms [show]            list every permission
# nb perms set <path> <lvl>  e.g. nb perms set email.read_bodies always
set -uo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$R" "$@" <<'PY'
import json,sys
R=sys.argv[1]; args=sys.argv[2:]
cmd=args[0] if args else "show"
p=f"{R}/config/permissions.json"; d=json.load(open(p))
B,D,G,Y,X="\033[1m","\033[2m","\033[32m","\033[33m","\033[31m"
RS="\033[0m"
col={"always":G+"always"+RS,"ask":Y+"ask"+RS,"never":X+"never"+RS}
if cmd=="show":
    print(f"{B}Permissions{RS}  {D}(edit config/permissions.json or: nb perms set <path> <level>){RS}\n")
    for grp,items in d.items():
        if grp.startswith("_"): continue
        print(f"  {B}{grp}{RS}")
        for k,v in items.items():
            if k.startswith("_") or not isinstance(v,dict): continue
            note=v.get("_note","")
            print(f"    {k:<24} {col.get(v.get('level'),v.get('level'))}")
            if note: print(f"      {D}{note[:88]}{RS}")
        print()
elif cmd=="set":
    if len(args)<3: sys.exit("usage: nb perms set <group.key> <always|ask|never>")
    path,lvl=args[1],args[2]
    if lvl not in ("always","ask","never"): sys.exit("level must be always|ask|never")
    g,k=path.split(".",1)
    if g not in d or k not in d[g]: sys.exit(f"unknown permission '{path}'")
    old=d[g][k].get("level"); d[g][k]["level"]=lvl
    json.dump(d,open(p,"w"),indent=2)
    print(f"  {path}: {col.get(old,old)} -> {col.get(lvl,lvl)}")
else: sys.exit("usage: nb perms [show|set]")
PY
