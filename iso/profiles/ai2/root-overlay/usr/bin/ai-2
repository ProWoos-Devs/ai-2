#!/bin/sh
# AI-2 CLI wrapper. The ai2 Python package is shipped at /usr/lib/ai2
# (version-independent of the system site-packages).
PYTHONPATH=/usr/lib/ai2 exec /usr/bin/python3 -c "import sys; from ai2.cli import main; sys.exit(main())" "$@"
