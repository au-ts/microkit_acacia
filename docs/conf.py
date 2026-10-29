# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from pathlib import Path

project = "Acacia"
copyright = "BSD-2-Clause"
author = "Lesley Rossouw"
release = (Path(__file__).parent.parent / "VERSION").read_text().strip()

extensions = [
    "myst_parser",
    "autodoc2",
]

exclude_patterns = ["_build", "requirements.txt"]

# Extensions to handle markdown in /docs
myst_enable_extensions = ["fieldlist", "deflist"]

# Make anchors so markdown formatted links to headings work properly
myst_heading_anchors = 4

# API reference
autodoc2_packages = [
    {
        "path": "../acacia",
        "auto_mode": True,
    },
]
autodoc2_render_plugin = "myst"
autodoc2_docstring_parser_regexes = [(r".*", "myst")]
autodoc2_hidden_objects = ["private", "inherited"]
autodoc2_module_all_regexes = []
autodoc2_output_dir = "apidocs"

html_theme = "furo"
html_title = f"Acacia {release}"
html_logo = "../acacia.png"

# use roboto, to match LionsOS!
html_css_files = [
    "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,700;1,400;1,700&display=swap",
]

# Emphasis colour is the sun the Acacia logo(ff781d). On light backgrounds it is too faint
# for text underlines and accents, so we use a slightly more legible colour.
_sun = "#ff781d"
_sun_text = "#c25400"
_fonts = {
    "font-stack": "Roboto, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
    "font-stack--headings": "var(--font-stack)",
}
html_theme_options = {
    "light_css_variables": {
        **_fonts,
        "color-brand-primary": _sun_text,
        "color-brand-content": _sun_text,
        "color-brand-visited": _sun_text,
        "color-link-underline": _sun,
        "color-link-underline--hover": _sun_text,
        "color-link-underline--visited": _sun,
    },
    "dark_css_variables": {
        "color-brand-primary": _sun,
        "color-brand-content": _sun,
        "color-brand-visited": _sun,
    },
}
