#!/usr/bin/env python3
import sys


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("Zum Starten wird Python 3.11 oder neuer benötigt.")
    from mailresponder.server import main
    main()
