#!/usr/bin/env bash
# Start Jace Launcher (creates the virtualenv on first run).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv 2>/dev/null || { python3 -m venv --without-pip .venv && curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python; }
  .venv/bin/python -m pip install -r requirements.txt
fi

# Qt 6.5+ needs libxcb-cursor0 on X11. If it isn't installed system-wide, fetch
# the Debian/Ubuntu package into .venv/syslibs (no root needed) and use that.
if [ "$(uname)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libxcb-cursor.so.0; then
  LIBDIR="$PWD/.venv/syslibs"
  if [ ! -e "$LIBDIR/libxcb-cursor.so.0" ] && command -v apt-get >/dev/null; then
    echo "libxcb-cursor0 missing - downloading a local copy (or run: sudo apt install libxcb-cursor0)"
    TMP="$(mktemp -d)"
    (cd "$TMP" && apt-get download libxcb-cursor0 >/dev/null && dpkg-deb -x libxcb-cursor0_*.deb root)
    mkdir -p "$LIBDIR"
    cp -P "$TMP"/root/usr/lib/*/libxcb-cursor.so.0* "$LIBDIR"/
    rm -rf "$TMP"
  fi
  export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec .venv/bin/python -m jace "$@"
