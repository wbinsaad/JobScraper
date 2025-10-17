from datetime import datetime

def time_ago(dt: datetime) -> str:
    """
    Convert a datetime to a human-readable relative time string.
    Examples: '2 hours ago', '5 minutes ago', 'just now'
    """
    now = datetime.now()
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds >= 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds >= 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "just now"
