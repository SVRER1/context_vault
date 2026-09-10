"""PDF Artifact Compiler for Context Vault.

Compiles Markdown text, structured data tables, and generated charts
into publication-grade PDF documents using ReportLab.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

from contextvault.core.models import Citation
from contextvault.core.vault import Vault

logger = logging.getLogger(__name__)


class PDFCompiler:
    """Compiles structured text, data tables, and charts into PDF files."""

    @classmethod
    def compile_pdf(
        cls,
        vault: Vault,
        title: str,
        content_markdown: str,
        output_filename: Optional[str] = None,
        charts: Optional[List[str]] = None,
        tables_data: Optional[List[List[List[Any]]]] = None,
        citations: Optional[List[Citation]] = None,
    ) -> Dict[str, Any]:
        """Generate a formatted PDF report with typography, tables, and charts."""
        gen_dir = vault.generated_dir
        gen_dir.mkdir(parents=True, exist_ok=True)

        clean_name = output_filename or f"{title.lower().replace(' ', '_')}.pdf"
        clean_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in clean_name)
        if not clean_name.endswith(".pdf"):
            clean_name += ".pdf"

        pdf_path = gen_dir / clean_name

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

                                  
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=14,
            fontName="Helvetica-Oblique",
        )
        h1_style = ParagraphStyle(
            "DocH1",
            parent=styles["Heading2"],
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=12,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )
        h2_style = ParagraphStyle(
            "DocH2",
            parent=styles["Heading3"],
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#0369a1"),
            spaceBefore=8,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        )
        body_style = ParagraphStyle(
            "DocBody",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#334155"),
            spaceAfter=6,
            fontName="Helvetica",
        )
        bullet_style = ParagraphStyle(
            "DocBullet",
            parent=body_style,
            leftIndent=15,
            spaceAfter=3,
        )

        story = []

                   
        story.append(Paragraph(title, title_style))
        time_str = datetime.now().strftime("%B %d, %Y")
        story.append(Paragraph(f"Context Vault Intelligence Report • Generated on {time_str} via the configured local Ollama model", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=14))

                                          
        lines = content_markdown.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                story.append(Spacer(1, 4))
                continue

                                                
            if line.startswith("# ") and title.lower() in line.lower():
                continue

            if line.startswith("# "):
                h_text = line.lstrip("# ").strip()
                story.append(Paragraph(h_text, h1_style))
            elif line.startswith("## "):
                h_text = line.lstrip("# ").strip()
                story.append(Paragraph(h_text, h1_style))
            elif line.startswith("### "):
                h_text = line.lstrip("# ").strip()
                story.append(Paragraph(h_text, h2_style))
            elif line.startswith("- ") or line.startswith("* "):
                b_text = cls._format_inline_markdown(line[2:].strip())
                story.append(Paragraph(f"• {b_text}", bullet_style))
            elif re.match(r"^\d+\.\s+", line):
                num_text = cls._format_inline_markdown(line)
                story.append(Paragraph(num_text, bullet_style))
            else:
                p_text = cls._format_inline_markdown(line)
                story.append(Paragraph(p_text, body_style))

                                              
        if tables_data:
            for table_matrix in tables_data:
                if not table_matrix or not table_matrix[0]:
                    continue
                story.append(Spacer(1, 10))
                story.append(Paragraph("Data Summary Table", h2_style))
                
                                        
                formatted_matrix = []
                for row_idx, row in enumerate(table_matrix):
                    row_cells = []
                    for cell in row:
                        cell_str = str(cell) if cell is not None else ""
                        c_style = ParagraphStyle(
                            f"Cell_{row_idx}",
                            parent=body_style,
                            fontSize=8.5,
                            leading=10.5,
                            textColor=colors.white if row_idx == 0 else colors.HexColor("#1e293b"),
                            fontName="Helvetica-Bold" if row_idx == 0 else "Helvetica",
                        )
                        row_cells.append(Paragraph(cell_str, c_style))
                    formatted_matrix.append(row_cells)

                t = Table(formatted_matrix, repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ]))
                story.append(t)
                story.append(Spacer(1, 10))

                                   
        if charts:
            for chart_rel in charts:
                chart_path = vault.root_path / chart_rel if not Path(chart_rel).is_absolute() else Path(chart_rel)
                if chart_path.exists():
                    story.append(Spacer(1, 12))
                    story.append(KeepTogether([
                        Paragraph(f"Chart Visual: {chart_path.stem.replace('_', ' ').title()}", h2_style),
                        Spacer(1, 4),
                        Image(str(chart_path), width=6.5 * inch, height=3.9 * inch),
                        Spacer(1, 8),
                    ]))

                              
        if citations:
            story.append(Spacer(1, 14))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=10))
            story.append(Paragraph("Referenced Vault Sources", h2_style))
            for i, src in enumerate(citations, 1):
                page_part = f" (page {src.page})" if src.page else ""
                head_part = f" — {src.heading}" if src.heading else ""
                cite_text = f"<b>[{i}]</b> {src.file_path}{page_part}{head_part}"
                story.append(Paragraph(cite_text, subtitle_style))

                   
        doc.build(story)
        logger.info(f"Compiled PDF successfully: {pdf_path}")

        return {
            "title": title,
            "filename": clean_name,
            "relative_path": vault.relative_path(pdf_path),
            "absolute_path": str(pdf_path),
        }

    @staticmethod
    def _format_inline_markdown(text: str) -> str:
        """Convert basic markdown bold/italics/code to ReportLab HTML tags."""
                                                            
        text = re.sub(r"`([^`]+)`", r'<font name="Courier" color="#0369a1">\1</font>', text)
                                         
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
                                           
        text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
        return text
