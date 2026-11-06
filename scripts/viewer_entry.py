"""PyInstaller entry point; deliberately imports no bot or database modules."""
from archive_viewer.__main__ import main

if __name__ == "__main__":
    main()
