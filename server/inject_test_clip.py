import shutil
from pathlib import Path

# Repo-relative paths (no hardcoded user/home paths)
ROOT = Path(__file__).resolve().parent.parent
data_dir = ROOT / "server" / "data" / "jobs"
dummy_mp4 = ROOT / "dummy.mp4"

# Find first job with clips
for job_dir in data_dir.iterdir():
    if not job_dir.is_dir():
        continue

    clips_dir = job_dir / "clips"
    if not clips_dir.exists():
        continue

    review_dir = clips_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    # Copy dummy clip
    dest = review_dir / "clip_99_test_review.mp4"
    shutil.copy(str(dummy_mp4), str(dest))

    print(f"✅ Injected test clip into {job_dir.name} -> review/clip_99_test_review.mp4")
    break
else:
    print("❌ No valid processing jobs found to inject a clip into.")
