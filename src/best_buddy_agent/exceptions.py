"""Best Buddy agent runtime errors."""


class BestBuddyAgentError(Exception):
    """Base error for best_buddy_agent runtime."""


class AgentEmptyResponseError(BestBuddyAgentError):
    """Model run completed without text output."""


class ReliabilityUnavailableError(BestBuddyAgentError):
    """Reliability extras required but not installed."""
