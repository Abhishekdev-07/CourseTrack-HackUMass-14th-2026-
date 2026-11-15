"""Point the app at a throw-away data folder BEFORE app.py is imported."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["COURSETRACK_DATA"] = tempfile.mkdtemp(prefix="coursetrack-test-")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
SAMPLES = os.path.join(ROOT, "samples")
