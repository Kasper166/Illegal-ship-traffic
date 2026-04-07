import os

from shared.logging import get_logger

logger = get_logger("active-learning")


def main() -> None:
    label_studio = os.getenv("LABEL_STUDIO_URL", "unset")
    logger.info("Active learning worker started")
    logger.info("Label Studio URL: %s", label_studio)


if __name__ == "__main__":
    main()
