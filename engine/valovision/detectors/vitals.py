"""Health and shield numbers via the template digit reader (no OCR model)."""
from __future__ import annotations

from typing import Any, Dict

from ..ocr import read_number
from ..templates import DigitBank
from .base import Detector, FrameContext


class VitalsDetector(Detector):
    name = "vitals"

    def __init__(self, layout, digit_bank: DigitBank, **kw):
        super().__init__(layout)
        self.bank = digit_bank

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:
        floor, rel = int(self.t["digit_luma"]), float(self.t["digit_rel_luma"])
        g_hp = ctx.crop(self.layout.hp, gray=True, pad=2)
        g_sh = ctx.crop(self.layout.shield, gray=True, pad=2)
        hp, hp_c = read_number(g_hp, self.bank, floor, rel)
        sh, sh_c = read_number(g_sh, self.bank, floor, rel, max_digits=2)
        min_s = self.t["digit_min_score"]
        if hp is not None and (hp_c < min_s or hp > 150):
            hp = None
        if sh is not None and (sh_c < min_s or sh > 50):
            sh = None
        if hp is not None and sh is None:
            sh = 0            # shield digits are hidden when the shield is broken
        return {"hp": hp, "shield": sh, "hp_conf": round(hp_c, 3), "shield_conf": round(sh_c, 3)}
