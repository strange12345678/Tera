# Command logic for channel management
from src.database import get_user_premium_status, set_error_channel, remove_error_channel, set_auto_channel, remove_auto_channel, get_error_channel, get_auto_channel
from .script import (
    error_channel_set_text, error_channel_already_set_text, error_channel_removed_text,
    auto_channel_set_text, auto_channel_already_set_text, auto_channel_removed_text,
    permission_denied_text
)

def is_premium(user_id):
    status = get_user_premium_status(user_id)
    return status in ("gold", "diamond")

def handle_set_error_channel(user_id, channel_id):
    if not is_premium(user_id):
        return permission_denied_text()
    if get_error_channel(user_id):
        return error_channel_already_set_text(get_error_channel(user_id))
    set_error_channel(user_id, channel_id)
    return error_channel_set_text(channel_id)

def handle_remove_error_channel(user_id, channel_id):
    if not is_premium(user_id):
        return permission_denied_text()
    remove_error_channel(user_id, channel_id)
    return error_channel_removed_text(channel_id)

def handle_set_auto_channel(user_id, channel_id):
    if not is_premium(user_id):
        return permission_denied_text()
    if get_auto_channel(user_id):
        return auto_channel_already_set_text(get_auto_channel(user_id))
    set_auto_channel(user_id, channel_id)
    return auto_channel_set_text(channel_id)

def handle_remove_auto_channel(user_id, channel_id):
    if not is_premium(user_id):
        return permission_denied_text()
    remove_auto_channel(user_id, channel_id)
    return auto_channel_removed_text(channel_id)
