"""Input loading, profiling, raw-file fingerprints and evidence exports."""
from pathlib import Path
import hashlib
import json
import pandas as pd

def load_tables(raw_dir, names):
    """Read only the named CSV tables; original files are never edited."""
    return {name: pd.read_csv(Path(raw_dir) / (name + '.csv')) for name in names}

def input_hashes(raw_dir):
    """Fingerprint all supplied input files so a run can prove byte preservation."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(raw_dir).glob('*') if p.is_file()}

def verify_raw_unchanged(raw_dir, before):
    assert input_hashes(raw_dir) == before, 'An original input file changed.'
    print('Original input bytes preserved.')

def save_evidence(path, findings):
    """Write machine-readable evidence only; never overwrite authored reports."""
    Path(path).write_text(json.dumps(findings,indent=2,allow_nan=False))

def profile(df: pd.DataFrame) -> pd.DataFrame:
    # One row per column: type, completeness, cardinality and an example value.
    return pd.DataFrame({
        "dtype": df.dtypes.astype(str),
        "non_null": df.notna().sum(),
        "null_pct": (df.isna().mean() * 100).round(1),
        "n_unique": df.nunique(dropna=True),
        "example": df.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else None),
    })


def check_table(checks: dict) -> pd.DataFrame:
    # checks = {name: count_of_problem_rows}. ok == True when the count is 0.
    t = pd.Series(checks, name="problem_rows").to_frame()
    t["ok"] = t["problem_rows"] == 0
    return t
