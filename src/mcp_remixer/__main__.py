"""Allow running mcp-remixer as a module: python -m mcp_remixer"""

import sys

from mcp_remixer.cli import main

if __name__ == "__main__":
    sys.exit(main())
