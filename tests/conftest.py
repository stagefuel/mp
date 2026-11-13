import os
import sys
import tempfile

# keep the tests away from the real config and data directories (set before meikipop is imported)
_tmp = tempfile.mkdtemp(prefix="meikipop-tests-")
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
    os.environ[var] = os.path.join(_tmp, var.lower())

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
