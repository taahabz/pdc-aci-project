"""
TTL Strategy - Passive cache expiration (baseline).

On write: do nothing. Let Redis TTL handle expiration.
This is the simplest strategy and the baseline for comparison.
"""

import logging

logger = logging.getLogger(__name__)


def on_write(key, value):
    """
    Handle a write operation with TTL strategy.
    
    Args:
        key: The key being written
        value: The value being written
        
    The TTL strategy does nothing on write. Cache entries expire
    naturally based on their TTL. This is the baseline "passive" approach.
    """
    # No-op: Let Redis TTL handle expiration
    pass


def on_strategy_switch():
    """Called when switching to this strategy."""
    logger.info("[TTL] Strategy activated - using passive TTL expiration")


def on_strategy_leave():
    """Called when switching away from this strategy."""
    logger.info("[TTL] Strategy deactivated")
