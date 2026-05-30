#!/usr/bin/env python3
"""Convert pa.yaml (Power Apps Source Format) screens to fx.yaml for pac canvas pack.

Usage:
  python3 scripts/pa_to_fx.py \
    powerapps/admin-app/_unpacked/Other/Src \
    powerapps/admin-app/_unpacked/Src

Overwrites matching .fx.yaml files in the output dir.
"""

import sys, re
import yaml
from pathlib import Path

INDENT = "    "

# Map pa.yaml base control types to fx.yaml type names.
# Classic/ prefix is stripped before lookup.
TYPE_MAP = {
    "Rectangle":  "rectangle",
    "Label":      "label",
    "Button":     "button",
    "TextInput":  "text",
    "Toggle":     "toggleSwitch",
    "Icon":       "icon",
    "ComboBox":   "combobox",
    "Dropdown":   "dropdown",
    "DatePicker": "datepicker",
    "Image":      "image",
    "Gallery":    "gallery",
}

# Gallery variant strings that carry meaning in the type name.
# "Vertical" and "Filled" are visual hints only; omit from type.
GALLERY_LAYOUT_VARIANTS = {"Vertical", "Filled", ""}


def fx_type(ctrl_str, variant, props):
    base = ctrl_str.split("/")[-1].split("@")[0]

    if base == "Gallery":
        if variant and variant not in GALLERY_LAYOUT_VARIANTS:
            return f"gallery.'{variant}'"
        # Plain "Vertical" (and blank) galleries need a named BrowseLayout variant
        # so pac places template children inside the galleryTemplate slot.
        # Without this, pac creates an empty galleryTemplate and children land
        # outside it — showing default "• ID / • Type:" placeholders in Studio.
        return "gallery.'BrowseLayout_Vertical_TwoTextOneImageVariant_ver5.0'"

    if base == "Icon":
        icon_val = (props or {}).get("Icon", "")
        if isinstance(icon_val, str) and icon_val.startswith("=Icon."):
            return f"icon.{icon_val[6:]}"
        return "icon"

    return TYPE_MAP.get(base, base.lower())


def fix_hash_comments(formula):
    """Convert YAML-style # comment lines to Power Fx // comments inside a formula string."""
    lines = formula.split("\n")
    result = []
    for line in lines:
        # If the (stripped) line starts with #, it's a YAML comment that leaked in;
        # convert to Power Fx // comment so pac doesn't choke on it.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            indent_part = line[: len(line) - len(stripped)]
            result.append(indent_part + "// " + stripped[1:].lstrip())
        else:
            result.append(line)
    return "\n".join(result)


def emit_props(props, depth):
    """Yield fx.yaml lines for a properties dict."""
    indent = INDENT * depth
    for key, val in (props or {}).items():
        val_str = str(val) if not isinstance(val, str) else val
        val_str = fix_hash_comments(val_str)
        if "\n" in val_str:
            yield f"{indent}{key}: |-"
            for line in val_str.split("\n"):
                yield f"{indent}{INDENT}{line}"
        else:
            yield f"{indent}{key}: {val_str}"


def emit_control(name, data, depth, zindex):
    """Yield fx.yaml lines for one control and its children."""
    indent = INDENT * depth
    ctrl_str = data.get("Control", "")
    variant  = data.get("Variant", "")
    props    = data.get("Properties") or {}
    children = data.get("Children") or []

    type_name = fx_type(ctrl_str, variant, props)

    # Galleries: pac canvas pack defaults an absent Layout to Layout.Horizontal,
    # which renders each item TemplateSize-px WIDE and full-height (a vertical
    # strip) and clips template labels positioned past TemplateSize. Force
    # Layout.Vertical so items stack top-to-bottom, full-width, TemplateSize tall.
    base = ctrl_str.split("/")[-1].split("@")[0]
    if base == "Gallery" and "Layout" not in props:
        props = {"Layout": "=Layout.Vertical", **props}

    # Quote only when single/double quotes appear in the declaration
    # (e.g. gallery.'BrowseLayout_...'). Dots and spaces are fine unquoted.
    decl = f"{name} As {type_name}"
    if "'" in decl or '"' in decl:
        yield f'{indent}"{decl}":'
    else:
        yield f"{indent}{decl}:"

    yield from emit_props(props, depth + 1)
    yield f"{indent}{INDENT}ZIndex: ={zindex}"
    yield ""

    for i, child in enumerate(children, 1):
        if isinstance(child, dict):
            for child_name, child_data in child.items():
                if isinstance(child_data, dict):
                    yield from emit_control(child_name, child_data, depth + 1, i)


def convert_screen(screen_name, screen_data):
    lines = [f"{screen_name} As screen:"]
    props    = screen_data.get("Properties") or {}
    children = screen_data.get("Children") or []

    lines.extend(emit_props(props, 1))
    if children:
        lines.append("")

    for i, child in enumerate(children, 1):
        if isinstance(child, dict):
            for child_name, child_data in child.items():
                if isinstance(child_data, dict):
                    lines.extend(emit_control(child_name, child_data, 1, i))

    return "\n".join(lines) + "\n"


def split_flow_dict(content):
    """Split a YAML flow-dict string 'k: v, k: v' respecting nested parens."""
    pairs, depth, start = [], 0, 0
    for i, ch in enumerate(content):
        if ch in "([": depth += 1
        elif ch in ")]": depth -= 1
        elif ch == "," and depth == 0:
            pairs.append(content[start:i].strip())
            start = i + 1
    pairs.append(content[start:].strip())
    return pairs


def expand_flow_properties(line):
    """Expand 'Properties: { k: v, k: v }' to indented block style."""
    m = re.match(r"^(\s+)Properties:\s*\{(.+)\}\s*$", line)
    if not m:
        return None
    indent, content = m.group(1), m.group(2)
    result = [f"{indent}Properties:"]
    for pair in split_flow_dict(content):
        kv = re.match(r"^([A-Za-z_]\w*):\s+(.+)$", pair)
        if kv:
            k, v = kv.group(1), kv.group(2).strip()
            if v.startswith("="):
                result.append(f"{indent}  {k}: '{v.replace(chr(39), chr(39)*2)}'")
            else:
                result.append(f"{indent}  {k}: {v}")
    return "\n".join(result)


def preprocess_pa_yaml(text):
    """
    Single-quote all single-line Power Fx formula values (starting with =) so
    PyYAML doesn't choke on ': ' sequences inside formula strings like
    =Concatenate("Issued: ", ...).  Block scalars (|-) are left untouched.
    """
    lines = text.split("\n")
    result = []
    block_indent = None

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Inside a block scalar: pass through until indentation drops back
        if block_indent is not None:
            if line == "" or indent > block_indent:
                result.append(line)
                continue
            block_indent = None

        # Detect block scalar start: `key: |-` or `key: |`
        if re.match(r"^\s+[A-Za-z_]\w*:\s+\|", line):
            block_indent = indent
            result.append(line)
            continue

        # Expand flow-style Properties: { k: v, k: v }
        expanded = expand_flow_properties(line)
        if expanded is not None:
            result.append(preprocess_pa_yaml(expanded))
            continue

        # Single-line formula value: quote it
        m = re.match(r"^(\s+[A-Za-z_]\w*:\s+)(=.*)$", line)
        if m:
            val = m.group(2).replace("'", "''")  # escape any single quotes
            result.append(f"{m.group(1)}'{val}'")
        else:
            result.append(line)

    return "\n".join(result)


def load_pa(path):
    raw = path.read_text()
    raw = re.sub(r"^#[^\n]*\n", "", raw, flags=re.MULTILINE)
    raw = preprocess_pa_yaml(raw)
    return yaml.safe_load(raw)


def main():
    src_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    for pa_file in sorted(src_dir.glob("*.pa.yaml")):
        if pa_file.stem.startswith("_") or pa_file.stem == "App":
            continue
        data = load_pa(pa_file)
        if not data or "Screens" not in data:
            print(f"  skip {pa_file.name} (no Screens key)")
            continue
        for screen_name, screen_data in data["Screens"].items():
            fx_text = convert_screen(screen_name, screen_data)
            out_path = out_dir / f"{screen_name}.fx.yaml"
            out_path.write_text(fx_text)
            print(f"  {pa_file.name} → {out_path.name}")


if __name__ == "__main__":
    main()
