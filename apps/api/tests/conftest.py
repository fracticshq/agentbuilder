import os
import sys
from pathlib import Path


# Keep test imports from failing on required production secrets.
os.environ.setdefault("SECRET_KEY", "test-secret-key")

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
