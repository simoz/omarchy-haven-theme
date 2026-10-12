"""Validate Haven's palette, shell, collection and optional Omarchy templates.

Usage: python3 scripts/check_theme.py [path/to/omarchy/default/themed]
Requires Python 3.11+ and Pillow. Templates are read, never executed.
"""

import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

from PIL import Image


root = Path(__file__).resolve().parents[1]
palette = tomllib.loads((root / "colors.toml").read_text())
shell = tomllib.loads((root / "shell.toml").read_text())
assert palette["mode"] == "light"
for key, value in palette.items():
    if key != "mode":
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), key


def luminance(value):
    channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return sum((c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) * w
               for c, w in zip(channels, (0.2126, 0.7152, 0.0722)))


def contrast(first, second):
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def require_contrast(label, foreground, background):
    ratio = contrast(foreground, background)
    assert ratio >= 4.5, f"{label}: {ratio:.2f}:1 is below 4.5:1"
    return ratio


surfaces = ("background", "dark_background", "darker_background", "lighter_background")
text_colors = [key for key in palette if key not in (*surfaces, "mode", "selection")]
ratios = []
for text in text_colors:
    for surface in surfaces:
        ratios.append(require_contrast(f"{text}/{surface}", palette[text], palette[surface]))
for text in ("foreground", "bright_foreground"):
    require_contrast(f"{text}/selection", palette[text], palette["selection"])
print(f"Palette: {len(ratios)} text/surface pairs pass 4.5:1; minimum {min(ratios):.2f}:1")
for first, second in (("foreground", "background"), ("foreground", "selection"),
                      ("muted", "lighter_background"), ("accent", "lighter_background")):
    print(f"  {first}/{second}: {contrast(palette[first], palette[second]):.2f}:1")

for section, values in shell.items():
    for key, value in values.items():
        if key.endswith("alpha"):
            assert 0 <= value <= 1, (section, key, value)
        if isinstance(value, str) and value.startswith("#"):
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), (section, key)
    if "background" in values:
        assert values["background-alpha"] == 1.0, section
        for key in ("text", "placeholder", "text-error", "accent", "countdown", "active"):
            if key in values:
                require_contrast(f"shell.{section}.{key}", values[key], values["background"])
    if "selected-background" in values:
        assert values["selected-background-alpha"] == 1.0
        require_contrast(f"shell.{section}.selected", values["selected-text"], values["selected-background"])
require_contrast("shell.lock.selection", shell["lock"]["text"], shell["lock"]["selection"])
print("Shell: opaque cards, selections, secondary text and error states pass")

records = json.loads((root / "docs/backgrounds.json").read_text())
assert len(records) == 12
assert [r["file"] for r in records] == sorted(r["file"] for r in records)
assert {r["file"] for r in records} == {str(p.relative_to(root)) for p in (root / "backgrounds").glob("*.webp")}
for record in records:
    path = root / record["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], path
    assert record["model"] == "gpt-image-2"
    assert record["requested_size"] == "3840x2160"
    assert record["quality"] == "high"
    with Image.open(path) as picture:
        picture.load()
        assert picture.size == (record["width"], record["height"]) == (3840, 2160), path
        assert picture.format == "WEBP"
    with Image.open(root / record["preview"]) as preview:
        preview.load()
        assert preview.size == (1280, 720), record["preview"]
for path, size in (("preview.png", (1920, 1080)), ("unlock.png", (3840, 2160)),
                   ("docs/branding/logo.png", (1536, 1024)),
                   ("docs/branding/social.png", (1920, 1008))):
    with Image.open(root / path) as picture:
        picture.load()
        assert picture.size == size, path
assert (root / "icons.theme").read_text().strip() == "Yaru-wartybrown"
for path in ("about.txt", "screensaver.txt"):
    artwork = (root / path).read_text()
    assert "STILL HERE. THINGS GROW." in artwork
    assert "\x1b" not in artwork
    assert max(map(len, artwork.splitlines())) <= 60
for document in (root / "README.md",):
    for target in re.findall(r"\]\(([^)]+)\)", document.read_text()):
        if not target.startswith(("https://", "http://", "#")):
            assert (document.parent / target.split("#")[0]).is_file(), (document, target)
print("Collection: 12 4K WebP wallpapers, previews, SHA-256, branding and local links verified")

if len(sys.argv) > 1:
    templates = sorted(Path(sys.argv[1]).glob("*.tpl"))
    assert templates, "No templates found"
    values = dict(palette, selection_background=palette["selection"],
                  selection_foreground=palette["bright_foreground"],
                  theme_type=palette["mode"], purple=palette["magenta"])
    for key, value in list(values.items()):
        values[key + "_strip"] = value.removeprefix("#")
        if value.startswith("#"):
            values[key + "_rgb"] = ",".join(str(int(value[i:i + 2], 16)) for i in (1, 3, 5))

    def resolve(match):
        parts = match[1].split()
        if len(parts) == 1:
            return values[parts[0]]
        if parts[0] in ("mix", "mix_strip", "mix_rgb"):
            fn, first, second, amount = parts
            fraction = float(amount.removesuffix("%"))
            if amount.endswith("%") or fraction > 1:
                fraction /= 100
            channels = [int(int(values[first][i:i + 2], 16) * (1 - fraction)
                            + int(values[second][i:i + 2], 16) * fraction + 0.5)
                        for i in (1, 3, 5)]
            result = "#" + "".join(f"{c:02x}" for c in channels)
            if fn == "mix_rgb":
                return ",".join(map(str, channels))
            return result.removeprefix("#") if fn == "mix_strip" else result
        if parts[0] in ("hypr_gradient", "shell_gradient", "gradient_start"):
            _, key, fallback = parts
            value = values.get(key, values.get(fallback, fallback))
            return json.dumps(value) if parts[0] == "hypr_gradient" else value
        raise ValueError(f"Unsupported template expression: {match[1]}")

    for template in templates:
        result = re.sub(r"\{\{\s*(.*?)\s*\}\}", resolve, template.read_text())
        assert "{{" not in result, template
        if template.name.endswith(".json.tpl"):
            json.loads(result)
        elif template.name.endswith(".toml.tpl"):
            tomllib.loads(result)
    print(f"Omarchy: {len(templates)} templates resolved; generated JSON/TOML parsed")
