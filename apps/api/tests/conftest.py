import os
import sys
from pathlib import Path


# Keep test imports from failing on required production secrets.
os.environ.setdefault("SECRET_KEY", "test-secret-key")

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
for package_src in (REPO_ROOT / "packages").glob("*/src"):
    package_path = str(package_src)
    if package_path not in sys.path:
        sys.path.insert(0, package_path)
