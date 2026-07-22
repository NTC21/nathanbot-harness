#!/bin/bash
# <xbar.title>nathanbot</xbar.title>
# <xbar.desc>nathanbot — glanceable status + the few actions that matter</xbar.desc>
# <xbar.version>1.1</xbar.version>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
#
# Actions route through /bin/bash -c: handing a .sh path to bash= lets macOS
# open it with the default .sh handler (Script Editor). Deep views live in the
# nathanbot app, not here — this menu stays small on purpose.
export PATH="/opt/homebrew/bin:/usr/bin:/bin"
R="$HOME/Projects/nathanbot"
NB="$R/bin/nb"
OPEN="$R/tasks/open"

decide=0; ready=0; blocked=0
dtitles=()
for f in "$OPEN"/*.md; do
  [ -e "$f" ] || continue
  st=$(grep -m1 '^status:' "$f" | sed 's/status: *//')
  ti=$(grep -m1 '^title:' "$f" | sed 's/title: *//;s/^"//;s/"$//')
  case "$st" in
    needs-decision) decide=$((decide+1)); dtitles+=("$ti") ;;
    ready)          ready=$((ready+1)) ;;
    blocked)        blocked=$((blocked+1)) ;;
  esac
done

# ── menu-bar title: arc mark + count of things needing you ──
if [ "$decide" -gt 0 ]; then
  echo "◆ $decide | color=#c9922f"
else
  echo "◆ | color=#9a9a9a"
fi

echo "---"
echo "nathanbot | size=11 color=#8a8a8a"
echo "$decide awaiting you · $ready ready · $blocked held | size=12"
echo "---"
echo "⚡ Capture a thought | bash=\"/bin/bash\" param1=\"-c\" param2=\"$R/scripts/capture.sh\" terminal=false"
# speaks + notifies only — Discord/iMessage delivery stays on the 07:30 schedule
echo "🔊 Brief me | bash=\"/bin/bash\" param1=\"-c\" param2=\"$NB brief --quiet --speak\" terminal=false"

if [ "$decide" -gt 0 ]; then
  echo "---"
  echo "Waiting on you | size=11 color=#c9922f"
  for t in "${dtitles[@]}"; do echo "-- $t | length=46"; done
  echo "Resolve decisions… | bash=\"/bin/bash\" param1=\"-c\" param2=\"$NB decide\" terminal=true"
fi

echo "---"
echo "Open nathanbot | bash=\"/bin/bash\" param1=\"-c\" param2=\"open -a nathanbot || open $HOME/Applications/nathanbot.app\" terminal=false"
echo "Refresh | refresh=true"
