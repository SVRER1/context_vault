import pytest
from pathlib import Path
from datetime import datetime

from contextvault.generation.pdf_compiler import PDFCompiler
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo, Citation
from contextvault.tools.charts import ChartGenerator

@pytest.fixture
def pdf_vault(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    csv_file.write_text("Year,Users\n2022,100\n2023,250\n2024,500\n", encoding="utf-8")

    info = VaultInfo(
        id="pdf-test-vault",
        display_name="PDFVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=1,
        chunk_count=0,
        index_version=1,
    )
    return Vault(info)

def test_compile_pdf_with_charts_and_tables(pdf_vault):
                         
    chart_info = ChartGenerator.generate_chart(
        pdf_vault,
        relative_path="metrics.csv",
        chart_type="bar",
        x_column="Year",
        y_column="Users",
        title="User Growth",
    )
    
                    
    markdown = """## Executive Summary
This document provides a summary of annual user growth metrics.

- Year-over-year growth exceeds 100%.
- Solid expansion observed in 2024.
"""
    table_sample = [
        ["Year", "Users", "Status"],
        ["2022", "100", "Baseline"],
        ["2023", "250", "Growth"],
        ["2024", "500", "Accelerated"],
    ]
    citations = [
        Citation(file_path="metrics.csv", page=None, section="Overview", heading=None, chunk_text_preview="Year,Users...")
    ]

    result = PDFCompiler.compile_pdf(
        vault=pdf_vault,
        title="Annual Growth Report",
        content_markdown=markdown,
        charts=[chart_info["image_relative_path"]],
        tables_data=[table_sample],
        citations=citations,
    )

    pdf_file = Path(result["absolute_path"])
    assert pdf_file.exists()
    assert pdf_file.stat().st_size > 5000                    
    
                                        
    with open(pdf_file, "rb") as f:
        header = f.read(5)
        assert header == b"%PDF-"
