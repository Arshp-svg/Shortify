"""Database preparation script: seeds realistic URLs into PostgreSQL for benchmarking."""

import argparse
import asyncio
import secrets
import string
import time
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

BASE62_ALPHABET = string.digits + string.ascii_letters


def generate_short_code(length: int = 7) -> str:
    """Generate a random Base62 short code."""
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))


async def seed_urls(count: int, batch_size: int = 5000) -> None:
    """Bulk insert realistic URL records into PostgreSQL."""
    settings = get_settings()
    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    print(f"[*] Starting seed of {count:,} URLs (batch size: {batch_size:,})...")
    start_time = time.perf_counter()
    total_inserted = 0

    async with session_factory() as session:
        for batch_start in range(0, count, batch_size):
            batch_count = min(batch_size, count - batch_start)
            now_iso = datetime.now(UTC)

            # Build batch values
            values = []
            for i in range(batch_count):
                idx = batch_start + i
                code = f"s{idx:07d}"  # Deterministic unique code for fast generation
                orig = f"https://example.com/products/item-{idx}?source=benchmark&ref=seed"
                values.append({
                    "code": code,
                    "orig": orig,
                    "created": now_iso,
                    "clicks": 0,
                    "active": True,
                })

            stmt = text("""
                INSERT INTO urls (short_code, original_url, created_at, click_count, active)
                VALUES (:code, :orig, :created, :clicks, :active)
                ON CONFLICT (short_code) DO NOTHING
            """)

            await session.execute(stmt, values)
            await session.commit()
            total_inserted += batch_count
            print(f"    Inserted {total_inserted:,} / {count:,} URLs...")

    duration = time.perf_counter() - start_time
    rate = total_inserted / duration if duration > 0 else 0
    print(f"[OK] Seeding completed: {total_inserted:,} URLs inserted in {duration:.2f}s ({rate:,.0f} URLs/sec).")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed PostgreSQL with URLs for benchmarking")
    parser.add_argument("--count", type=int, default=100000, help="Number of URLs to seed")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for bulk insert")
    args = parser.parse_args()

    asyncio.run(seed_urls(args.count, args.batch_size))


if __name__ == "__main__":
    main()
