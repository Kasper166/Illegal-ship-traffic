import os

from shared.logging import get_logger

logger = get_logger("ingestion")


def main() -> None:
    copernicus_url = os.getenv("COPERNICUS_API_URL", "unset")
    logger.info("Ingestion worker started")
    logger.info("Configured Copernicus endpoint: %s", copernicus_url)


if __name__ == "__main__":
    main()
