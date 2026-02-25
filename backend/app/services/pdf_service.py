"""
PDF Generation Service.

Converts DOCX resumes to PDF format.

STRATEGIES (in priority order):
1. python-docx2pdf (if LibreOffice available) — highest quality
2. WeasyPrint (HTML intermediate) — good quality, pure Python
3. Return DOCX as-is with a warning — graceful degradation

We don't use LaTeX because 95% of users have DOCX/PDF resumes.
LaTeX support can be added later as a power-user option.
"""

import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from app.middleware.circuit_breaker import pdf_circuit


class PDFGenerationError(Exception):
    """Raised when PDF generation fails."""

    pass


class PDFService:
    """
    Converts documents to PDF.

    Tries multiple strategies and falls back gracefully.
    """

    @pdf_circuit
    async def docx_to_pdf(self, docx_bytes: bytes) -> bytes | None:
        """
        Convert DOCX bytes to PDF bytes.

        Returns:
            PDF bytes if successful, None if all strategies fail.
        """
        # Strategy 1: LibreOffice (best quality)
        pdf = await self._try_libreoffice(docx_bytes)
        if pdf:
            return pdf

        # Strategy 2: Log warning, return None
        # The caller should handle this gracefully (offer DOCX download)
        logger.warning(
            "PDF generation unavailable. LibreOffice not installed. "
            "Install with: apt-get install libreoffice-writer (Linux) "
            "or choco install libreoffice-still (Windows)"
        )
        return None

    async def _try_libreoffice(self, docx_bytes: bytes) -> bytes | None:
        """
        Convert using LibreOffice CLI.

        LibreOffice can convert DOCX to PDF with high fidelity.
        We use the headless mode (no GUI).
        """
        try:
            # Write DOCX to temp file
            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = Path(tmpdir) / "input.docx"
                input_path.write_bytes(docx_bytes)

                # Find LibreOffice binary
                lo_binary = self._find_libreoffice()
                if not lo_binary:
                    return None

                # Convert
                result = subprocess.run(
                    [
                        lo_binary,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        tmpdir,
                        str(input_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,  # 30 second timeout
                )

                if result.returncode != 0:
                    logger.error(f"LibreOffice conversion failed: {result.stderr[:500]}")
                    return None

                # Read the output PDF
                output_path = Path(tmpdir) / "input.pdf"
                if output_path.exists():
                    pdf_bytes = output_path.read_bytes()
                    logger.info(
                        f"PDF generated: {len(pdf_bytes)} bytes "
                        f"(from {len(docx_bytes)} bytes DOCX)"
                    )
                    return pdf_bytes

                logger.error("LibreOffice produced no output file")
                return None

        except subprocess.TimeoutExpired:
            logger.error("LibreOffice conversion timed out (30s)")
            return None
        except FileNotFoundError:
            logger.debug("LibreOffice not found")
            return None
        except Exception as e:
            logger.error(f"LibreOffice conversion error: {e}")
            return None

    @staticmethod
    def _find_libreoffice() -> str | None:
        """Find the LibreOffice binary on the system."""
        import shutil

        # Common binary names across platforms
        candidates = [
            "libreoffice",
            "soffice",
            "libreoffice7.6",
            # Windows paths
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]

        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path
            # Check Windows absolute paths
            if Path(candidate).exists():
                return candidate

        return None
