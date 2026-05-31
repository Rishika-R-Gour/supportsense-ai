from __future__ import annotations

from io import StringIO

from app.data_loader import load_ticket_csv


def test_load_ticket_csv_normalizes_common_support_export_columns() -> None:
    csv = StringIO(
        "\n".join(
            [
                "Ticket ID,Customer Name,Date of Purchase,First Response Time,Ticket Type,Ticket Subject,Ticket Description,Ticket Status,Ticket Priority,Ticket Channel,Product Purchased,Time to Resolution,Customer Satisfaction Rating",
                "1,Ada Lovelace,2020-07-28,,Product inquiry,Setup help,I'm having an issue with the {product_purchased}. Please assist.,Pending Customer Response,high,Email,Widget,,4",
                "2,Grace Hopper,2021-01-01,2023-06-01 08:00:00,Refund request,Refund please,The product_purchased stopped working,Closed,Critical,Chat,Camera,2023-06-01 09:30:00,2",
            ]
        )
    )

    df = load_ticket_csv(csv)

    assert len(df) == 2
    assert df.iloc[0]["ticket_id"] == "TCK-2"
    assert df.iloc[0]["customer_segment"] == "At-risk"
    assert df.iloc[0]["bot_solvable_label"] == "human_required"
    assert df.iloc[0]["sentiment"] == "Negative"
    assert df.iloc[1]["status"] == "In Progress"
    assert df.iloc[1]["priority"] == "High"
    assert "product_purchased" not in df.iloc[1]["ticket_text"]
    assert "Widget" in df.iloc[1]["ticket_text"]
