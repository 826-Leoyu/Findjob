from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "findjob.db"
PROFILES_DIR = ROOT / "profiles"
RESUME_DIR = ROOT / "resume"
MASTER_RESUME = RESUME_DIR / "master.yaml"
OUTPUT_DIR = ROOT / "output"
