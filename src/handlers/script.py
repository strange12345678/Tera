# User-facing text responses for channel commands
def error_channel_set_text(channel_id):
    return f"✅ Error channel set to {channel_id}. All failed download links will be forwarded here."

def error_channel_already_set_text(channel_id):
    return f"⚠️ Error channel already set to {channel_id}. Use /remove_error_channel to change."

def error_channel_removed_text(channel_id):
    return f"❌ Error channel {channel_id} removed. Failed download links will no longer be forwarded."

def auto_channel_set_text(channel_id):
    return f"✅ Auto channel set to {channel_id}. All user downloads will be forwarded here."

def auto_channel_already_set_text(channel_id):
    return f"⚠️ Auto channel already set to {channel_id}. Use /remove_auto_channel to change."

def auto_channel_removed_text(channel_id):
    return f"❌ Auto channel {channel_id} removed. User downloads will no longer be forwarded."

def permission_denied_text():
    return "⛔ Only Gold and Diamond premium users can use this command."
