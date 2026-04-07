import os

from shared.logging import get_logger

logger = get_logger("ais")


def main() -> None:
    qdrant_url = os.getenv("QDRANT_URL", "unset")
    logger.info("AIS enrichment worker started")
    logger.info("Qdrant URL: %s", qdrant_url)


if __name__ == "__main__":
    main()
