"""ValoVision — classical computer-vision reader for the VALORANT (2022 Q1) HUD.

No neural networks: template matching, colour gating, edge energy,
connected components and morphology only.
"""
from .config import Layout, load_layout
from .pipeline import Engine
from .tracking import Tracker

__version__ = "2.0.0"
__all__ = ["Engine", "Layout", "Tracker", "load_layout", "__version__"]
