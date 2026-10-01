"""Profile loader. The regulatory crosswalk, rule thresholds and citations are content, not code.

Carried over from governed-data-platform: a profile is a file that is hashed, so
"which rules and which clause numbers governed this datasheet" is answerable
afterwards. ``clinical_gcp.yaml`` ships with the package; a GMP profile would be
a second file in the same shape with no code change.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .ledger import canonical, sha256

PROFILE_DIR = Path(__file__).parent / "profiles"
DEFAULT_PROFILE = PROFILE_DIR / "clinical_gcp.yaml"


def load_profile(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_PROFILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("meta", "rules", "crosswalk", "alcoa", "touchpoints"):
        if key not in data:
            raise ValueError(f"profile {path} is missing required section {key!r}")
    data["_path"] = str(path)
    data["_fingerprint"] = sha256(canonical({k: v for k, v in data.items() if not k.startswith("_")}))
    return data


def profile_version(profile: dict) -> str:
    return f"{profile['meta']['name']} v{profile['meta']['version']}"
