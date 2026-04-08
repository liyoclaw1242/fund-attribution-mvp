"""Allow running the scheduler with: python -m pipeline"""

from pipeline.scheduler import main
import asyncio

asyncio.run(main())
