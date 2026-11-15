"""Print the quality metrics of every photo in a folder, so the thresholds in
rxcore/config.py can be chosen from real data instead of guessed.

    python tools/calibrate_quality.py data/samples
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rxcore.quality import assess_quality, load_image  # noqa: E402


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/samples")
    print("%-40s %6s %6s %8s %6s  warnings" % ("file", "bright", "contr", "blur", "glare"))
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        q = assess_quality(load_image(path.read_bytes()))
        m = q["metrics"]
        print("%-40s %6.1f %6.1f %8.1f %6.3f  %s" % (path.name[:40], m["brightness_mean"], m["contrast_std"],
              m["blur_laplacian_var"], m["glare_fraction"], "; ".join(q["reject_reasons"] + q["warnings"])))


if __name__ == "__main__":
    main()
