from __future__ import annotations

import io
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        try:
            import ddddocr

            _ocr = ddddocr.DdddOcr(show_ad=False)
        except Exception:
            _ocr = False
    return _ocr if _ocr is not False else None


class CaptchaSolver:
    """验证码识别：文字验证码 + 滑块距离估算。"""

    def solve_image(self, image_bytes: bytes) -> str:
        ocr = _get_ocr()
        if ocr:
            try:
                return ocr.classification(image_bytes)
            except Exception:
                pass
        return "ABCD"

    def solve_slider(self, bg_bytes: bytes, slice_bytes: bytes) -> int:
        """估算滑块缺口 x 坐标（简化实现）。"""
        ocr = _get_ocr()
        if ocr and hasattr(ocr, "slide_match"):
            try:
                result = ocr.slide_match(slice_bytes, bg_bytes, simple_target=True)
                return int(result.get("target", [120])[0])
            except Exception:
                pass
        return random.randint(80, 180)

    @staticmethod
    def is_available() -> bool:
        return _get_ocr() is not None
