
import logging
import sys

from pydantic import ValidationError

from news_agent.config import get_settings
from news_agent.logging_config import configure_logging
from news_agent.pipeline import run_pipeline


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)

    try:
        settings = get_settings()
        logger.info(
            "Starting news agent | model=%s | timezone=%s",
            settings.ollama_model,
            settings.timezone_name,
        )

        result = run_pipeline()
        logger.info(
            "Finished | status=%s | selected=%d | emailed=%s",
            result.status,
            result.selected_count,
            result.emailed,
        )
        return 0

    except (ValidationError, ValueError) as exc:
        logger.error("Configuration or validation error: %s", exc)
        return 2

    except Exception:
        logger.exception("News agent failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
