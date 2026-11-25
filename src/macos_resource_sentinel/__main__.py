"""Allow running the CLI with ``python -m macos_resource_sentinel``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
