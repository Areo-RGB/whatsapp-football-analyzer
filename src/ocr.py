"""
OCR module using PaddleOCR for text extraction from images.
State-of-the-art OCR with German language support.
"""

import os
from pathlib import Path

# Suppress PaddleOCR debug output
os.environ['PADDLEOCR_LOG_LEVEL'] = 'ERROR'

try:
    from paddleocr import PaddleOCR
    HAS_PADDLE_OCR = True
except ImportError:
    HAS_PADDLE_OCR = False

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

HAS_OCR = HAS_PADDLE_OCR or HAS_TESSERACT

# Global PaddleOCR instance (lazy loaded)
_paddle_ocr = None


def get_paddle_ocr():
    """Get or create PaddleOCR instance."""
    global _paddle_ocr
    if _paddle_ocr is None:
        # Use German + English, angle classification for rotated text
        _paddle_ocr = PaddleOCR(
            use_angle_cls=True,
            lang='german'
        )
    return _paddle_ocr


def extract_text_paddle(image_path: str | Path) -> str:
    """
    Extract text from image using PaddleOCR.
    
    Args:
        image_path: Path to image file
        
    Returns:
        Extracted text as string
    """
    ocr = get_paddle_ocr()
    result = ocr.ocr(str(image_path), cls=True)
    
    if not result or not result[0]:
        return ""
    
    # Extract text from result structure
    lines = []
    for line in result[0]:
        if line and len(line) >= 2:
            text = line[1][0]  # Text is in [1][0], confidence in [1][1]
            lines.append(text)
    
    return "\n".join(lines)


def extract_text_tesseract(image_path: str | Path, language: str = 'deu') -> str:
    """
    Extract text from image using Tesseract OCR (fallback).
    
    Args:
        image_path: Path to image file
        language: Tesseract language code
        
    Returns:
        Extracted text as string
    """
    if not HAS_TESSERACT:
        return ""
    
    try:
        img = Image.open(image_path)
        
        # Preprocess for better OCR
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # Extract text
        text = pytesseract.image_to_string(img, lang=language)
        return text.strip()
        
    except Exception as e:
        print(f"Tesseract error: {e}")
        return ""


def extract_text_from_image(image_path: str | Path, language: str = 'deu') -> str:
    """
    Extract text from image using best available OCR.
    
    Args:
        image_path: Path to image file
        language: Language code
        
    Returns:
        Extracted text as string
    """
    # Use Tesseract as primary (more reliable, PaddleOCR has CPU compatibility issues)
    if HAS_TESSERACT:
        return extract_text_tesseract(image_path, language)
    
    if HAS_PADDLE_OCR:
        try:
            return extract_text_paddle(image_path)
        except Exception as e:
            print(f"PaddleOCR error: {e}")
    
    return ""


def extract_text_from_images(image_paths: list[str | Path]) -> str:
    """
    Extract text from multiple images.
    
    Args:
        image_paths: List of image file paths
        
    Returns:
        Combined text from all images
    """
    texts = []
    for path in image_paths:
        text = extract_text_from_image(path)
        if text:
            texts.append(f"--- Image: {Path(path).name} ---\n{text}")
    
    return "\n\n".join(texts)


def check_tesseract() -> bool:
    """Check if Tesseract is installed."""
    if not HAS_TESSERACT:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except:
        return False


def check_ocr() -> dict:
    """Check available OCR engines."""
    return {
        "paddleocr": HAS_PADDLE_OCR,
        "tesseract": check_tesseract() if HAS_TESSERACT else False,
        "any": HAS_OCR
    }


if __name__ == "__main__":
    print("OCR Module Status")
    print("-" * 40)
    status = check_ocr()
    for engine, available in status.items():
        icon = "✓" if available else "✗"
        print(f"  {icon} {engine}")
    
    # Test with sample image if available
    test_images = list(Path("data/media").glob("*.jfif"))
    if test_images and status["any"]:
        print(f"\nTesting with: {test_images[0].name}")
        text = extract_text_from_image(test_images[0])
        print(f"Extracted {len(text)} chars:")
        print(text[:500])
