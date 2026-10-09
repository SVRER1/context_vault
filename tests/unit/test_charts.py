import pytest
from pathlib import Path
from datetime import datetime

from contextvault.tools.charts import ChartGenerator
from contextvault.core.vault import Vault
from contextvault.core.models import VaultInfo

@pytest.fixture
def data_vault(tmp_path):
    csv_file = tmp_path / "quarterly_data.csv"
    csv_content = """Quarter,Revenue,Expenses,Profit
Q1,12000,8000,4000
Q2,15500,9200,6300
Q3,18000,10500,7500
Q4,22000,12000,10000
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    info = VaultInfo(
        id="chart-test-vault",
        display_name="ChartVault",
        absolute_path=str(tmp_path),
        created_at=datetime.now(),
        last_opened_at=datetime.now(),
        file_count=1,
        chunk_count=0,
        index_version=1,
    )
    return Vault(info)

def test_inspect_dataset(data_vault):
    res = ChartGenerator.inspect_dataset(data_vault, "quarterly_data.csv")
    assert res["row_count"] == 4
    assert "Revenue" in res["columns"]
    assert res["column_types"]["Revenue"] == "numeric"
    assert res["column_types"]["Quarter"] == "categorical"
    assert res["summary_stats"]["Revenue"]["min"] == 12000.0
    assert res["summary_stats"]["Revenue"]["max"] == 22000.0

def test_generate_bar_chart(data_vault):
    chart_info = ChartGenerator.generate_chart(
        vault=data_vault,
        relative_path="quarterly_data.csv",
        chart_type="bar",
        x_column="Quarter",
        y_column="Revenue",
        title="Quarterly Revenue Growth",
    )
    
    assert chart_info["chart_type"] == "bar"
    assert chart_info["points_count"] == 4
    
    img_path = Path(chart_info["image_absolute_path"])
    assert img_path.exists()
    assert img_path.stat().st_size > 5000                 

def test_generate_line_chart(data_vault):
    chart_info = ChartGenerator.generate_chart(
        vault=data_vault,
        relative_path="quarterly_data.csv",
        chart_type="line",
        x_column="Quarter",
        y_column="Profit",
        title="Profit Trend",
    )
    
    img_path = Path(chart_info["image_absolute_path"])
    assert img_path.exists()
    assert img_path.name.endswith(".png")
