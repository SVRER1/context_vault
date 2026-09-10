"""Image parsing with local OCR and an Ollama vision fallback."""

from pathlib import Path
from typing import Any

from contextvault.core.exceptions import ParseError
from contextvault.core.models import DocumentSection, ParsedDocument
from contextvault.parsers.base import BaseParser


class ImageOCRParser(BaseParser):
    """Extract searchable text from raster images.

    Tesseract is preferred when installed because it is deterministic and
    cheap. If it is unavailable or returns no text, an Ollama vision client
    can transcribe the image using the configured local model.
    """

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

    def __init__(self, ocr_client: Any = None):
        self.ocr_client = ocr_client

    def supported_extensions(self) -> set[str]:
        return self.IMAGE_EXTENSIONS

    def parse(self, file_path: Path, file_id: str) -> ParsedDocument:
        if not file_path.exists():
            raise ParseError(f"Image not found: {file_path}")

        text = ""
        backend = "none"
        errors: list[str] = []

                                                                          
                                                                      
        try:
            from PIL import Image
            import pytesseract

            with Image.open(file_path) as image:
                text = pytesseract.image_to_string(image).strip()
            if text:
                backend = "tesseract"
        except ImportError:
            errors.append("Tesseract OCR dependencies are not installed")
        except Exception as exc:
            errors.append(f"Tesseract OCR unavailable: {exc}")

        if not text and self.ocr_client is not None:
            try:
                text = self.ocr_client.ocr_image(file_path).strip()
                if text:
                    backend = "ollama-vision"
            except Exception as exc:
                errors.append(f"Ollama vision OCR unavailable: {exc}")

        metadata = {
            "source_type": "image",
            "ocr_backend": backend,
            "ocr_status": "text_extracted" if text else "no_text_extracted",
            "ocr_text_chars": len(text),
        }
        if errors:
            metadata["ocr_errors"] = errors

        sections = []
        if text:
            sections.append(
                DocumentSection(
                    heading="OCR Text",
                    text=text,
                    metadata={"ocr_backend": backend},
                )
            )

        return ParsedDocument(
            file_id=file_id,
            path=str(file_path),
            title=file_path.name,
            text=text,
            sections=sections,
            metadata=metadata,
        )
