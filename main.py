import asyncio
import logging

from components.config import Config
from components.monitor import TelegramMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def main() -> None:
    config = Config.from_env()
    monitor = TelegramMonitor(config)
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
