from sqlalchemy import text

from database.postgres_sql import get_engine


def get_metrics():
    engine = get_engine()

    query = """
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY company, year
                   ORDER BY created_at DESC
               ) AS rn
        FROM financial_metrics
    ) t
    WHERE rn = 1
    ORDER BY company
    """

    with engine.connect() as connection:
        result = connection.execute(text(query))
        rows = [dict(row._mapping) for row in result]

    return rows


def delete_metrics(company: str, year: str) -> None:
    engine = get_engine()

    query = "DELETE FROM financial_metrics WHERE company = :company AND year = :year"

    with engine.begin() as connection:
        connection.execute(text(query), {"company": company, "year": str(year)})