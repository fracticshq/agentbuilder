#!/usr/bin/env python3
"""
FastAPI Application Launcher
"""

import sys
import os
from pathlib import Path

# Add local packages to Python path
current_dir = Path(__file__).parent
packages_dir = current_dir.parent.parent / "packages"

for package in ["commons", "memory", "retrieval", "llm"]:
    package_path = packages_dir / package / "src"
    if package_path.exists():
        sys.path.insert(0, str(package_path))

# Now import and run the app
if __name__ == "__main__":
    import uvicorn
    
    # Run with reload disabled since we're importing the app directly
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False  # Disable reload since we're importing directly
    )
