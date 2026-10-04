"""PyInstaller entry point for the bundled (AppImage) build."""
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller points LD_LIBRARY_PATH at the bundle. That's only needed by this
    # process (already loaded), and it breaks child programs like Java, xdg-open
    # and the Forge installer, so give children the user's original environment.
    orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        os.environ["LD_LIBRARY_PATH"] = orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

else:
    # running from source (e.g. an instance shortcut): make the jace package importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jace.ui.app import main  # noqa: E402

main()
