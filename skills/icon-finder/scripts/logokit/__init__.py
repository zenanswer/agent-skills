"""logokit - shared plumbing for the icon-finder skill.

Modules:
  cache      on-disk JSON cache (Simple Icons, svgl, lobe-icons indexes)
  sources    multi-source search + deterministic ranking
  svg        fetching, color analysis, recoloring
  render     SVG -> PNG with aspect ratio preserved
  normalize  trim / square canvas / consistent padding / multi-size output
  sheet      contact sheet previews
"""

__all__ = ["cache", "normalize", "render", "sheet", "sources", "svg"]
