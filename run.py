                     
"""
Context Vault - Primary Application Launcher
Unified entry point for both Desktop GUI and CLI.

Usage:
    python run.py                  # Launch the PyWebView Desktop Application
    python run.py desktop          # Launch the PyWebView Desktop Application
    python run.py open <PATH>      # Run CLI command
    python run.py status           # Check active vault status
    python run.py --help           # Show CLI commands
"""

import sys
import os
from pathlib import Path

                                    
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def launch_desktop():
    """Launch the PyWebView Desktop GUI."""
    try:
        from desktop.main import main as desktop_main
        desktop_main()
    except ImportError as e:
        print(f"[Error] Failed to launch desktop application: {e}")
        print("Ensure all dependencies are installed: pip install -e .")
        sys.exit(1)

def launch_cli():
    """Launch the Typer CLI."""
    try:
        from cli.main import app as cli_app
        cli_app()
    except ImportError as e:
        print(f"[Error] Failed to launch CLI: {e}")
        print("Ensure all dependencies are installed: pip install -e .")
        sys.exit(1)

def main():
                                                                           
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1].lower() in ("desktop", "--desktop", "-d", "gui")):
        launch_desktop()
    else:
                               
                                      
        if sys.argv[1].lower() == "cli":
            sys.argv.pop(1)
        launch_cli()

if __name__ == "__main__":
    main()
