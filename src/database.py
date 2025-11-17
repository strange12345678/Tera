"""
MongoDB database module for user management
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, DuplicateKeyError

import config

logger = logging.getLogger(__name__)


class Database:
    """MongoDB database handler"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.users_collection = None
    
    def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(config.MONGODB_URL, serverSelectionTimeoutMS=5000)
            # Verify connection
            self.client.admin.command('ping')
            self.db = self.client[config.MONGODB_DB_NAME]
            self.users_collection = self.db['users']
            
            # Create indexes
            self.users_collection.create_index('user_id', unique=True)
            
            logger.info("Successfully connected to MongoDB")
            return True
        except ServerSelectionTimeoutError:
            logger.error("Failed to connect to MongoDB: Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    def add_user(self, user_id: int, first_name: str = None, last_name: str = None, 
                 username: str = None) -> bool:
        """Add a new user to database"""
        try:
            user_data = {
                'user_id': user_id,
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'joined_at': datetime.utcnow(),
                'last_active': datetime.utcnow(),
                'downloads_count': 0,
                'downloads_today': 0,
                'last_download_reset': datetime.utcnow(),
                'is_premium': False,
                'premium_tier': 'free',
                'premium_until': None,
                'premium_days_purchased': 0,
                'total_investment': 0.0,
                'auto_upload_channel': None,  # For premium users to save their channel
                'auto_upload_enabled': False,  # Premium feature flag
                'preferred_quality': 'auto',
                'auto_rename_pattern': None,
                'download_history': [],
            }
            self.users_collection.insert_one(user_data)
            logger.info(f"Added new user: {user_id}")
            return True
        except DuplicateKeyError:
            # User already exists, update last active
            self.update_last_active(user_id)
            return True
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")
            return False
    
    def user_exists(self, user_id: int) -> bool:
        """Check if user exists"""
        try:
            return self.users_collection.find_one({'user_id': user_id}) is not None
        except Exception as e:
            logger.error(f"Error checking user existence: {e}")
            return False
    
    def update_last_active(self, user_id: int) -> bool:
        """Update user's last active timestamp"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'last_active': datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error updating last active for user {user_id}: {e}")
            return False
    
    def increment_download_count(self, user_id: int) -> bool:
        """Increment user's download count"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$inc': {'downloads_count': 1}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error incrementing download count for user {user_id}: {e}")
            return False
    
    def get_all_user_ids(self) -> list:
        """Get all user IDs from database"""
        try:
            users = self.users_collection.find({}, {'user_id': 1})
            return [user['user_id'] for user in users]
        except Exception as e:
            logger.error(f"Error fetching all user IDs: {e}")
            return []
    
    def get_user_stats(self, user_id: int) -> dict:
        """Get user statistics"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                # Reset daily counter if needed
                last_reset = user.get('last_download_reset', datetime.utcnow())
                if (datetime.utcnow() - last_reset).days >= 1:
                    self.reset_daily_quota(user_id)
                    downloads_today = 0
                else:
                    downloads_today = user.get('downloads_today', 0)
                
                return {
                    'user_id': user.get('user_id'),
                    'joined_at': user.get('joined_at'),
                    'downloads_count': user.get('downloads_count', 0),
                    'downloads_today': downloads_today,
                    'last_active': user.get('last_active'),
                }
            return {'user_id': user_id, 'joined_at': None, 'downloads_count': 0, 'downloads_today': 0, 'last_active': None}
        except Exception as e:
            logger.error(f"Error fetching user stats for {user_id}: {e}")
            return {'user_id': user_id, 'joined_at': None, 'downloads_count': 0, 'downloads_today': 0, 'last_active': None}
    
    def get_total_users(self) -> int:
        """Get total number of users"""
        try:
            return self.users_collection.count_documents({})
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0
    
    def set_premium(self, user_id: int, is_premium: bool, premium_until=None) -> bool:
        """Set user as premium"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'is_premium': is_premium, 'premium_until': premium_until}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error setting premium status for {user_id}: {e}")
            return False
    
    def is_premium(self, user_id: int) -> bool:
        """Check if user is premium"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return user.get('is_premium', False)
            return False
        except Exception as e:
            logger.error(f"Error checking premium status for {user_id}: {e}")
            return False
    
    def set_auto_upload_channel(self, user_id: int, channel_id: str, enabled: bool = True) -> bool:
        """Set auto-upload channel for premium user"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'auto_upload_channel': channel_id, 'auto_upload_enabled': enabled}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error setting auto-upload channel for {user_id}: {e}")
            return False
    
    def get_auto_upload_channel(self, user_id: int) -> Optional[str]:
        """Get auto-upload channel for user"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user and user.get('auto_upload_enabled'):
                return user.get('auto_upload_channel')
            return None
        except Exception as e:
            logger.error(f"Error getting auto-upload channel for {user_id}: {e}")
            return None
    
    def get_user(self, user_id: int) -> dict:
        """Get complete user data"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            return user if user else {}
        except Exception as e:
            logger.error(f"Error fetching user data for {user_id}: {e}")
            return {}

    def get_daily_download_count(self, user_id: int) -> int:
        """Get today's download count"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                last_reset = user.get('last_download_reset', datetime.utcnow())
                # Check if we need to reset daily counter
                if (datetime.utcnow() - last_reset).days >= 1:
                    self.reset_daily_quota(user_id)
                    return 0
                return user.get('downloads_today', 0)
            return 0
        except Exception as e:
            logger.error(f"Error getting daily download count: {e}")
            return 0

    def increment_daily_downloads(self, user_id: int) -> None:
        """Increment today's download count"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$inc': {'downloads_today': 1}}
            )
        except Exception as e:
            logger.error(f"Error incrementing daily downloads: {e}")

    def reset_daily_quota(self, user_id: int) -> None:
        """Reset daily download quota"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'downloads_today': 0,
                        'last_download_reset': datetime.utcnow()
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error resetting daily quota: {e}")

    def check_quota_exceeded(self, user_id: int) -> bool:
        """Check if user exceeded daily quota"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if not user:
                self.add_user(user_id)
                user = self.users_collection.find_one({'user_id': user_id})
            
            daily_limit = int(os.getenv('PREMIUM_DAILY_DOWNLOADS', 100)) \
                if user.get('is_premium') \
                else int(os.getenv('FREE_DAILY_DOWNLOADS', 5))
            
            current_count = self.get_daily_download_count(user_id)
            return current_count >= daily_limit
        except Exception as e:
            logger.error(f"Error checking quota: {e}")
            return True

    def add_to_history(self, user_id: int, file_name: str, 
                       file_size: int, download_url: str) -> None:
        """Add file to user's download history"""
        try:
            history_entry = {
                'timestamp': datetime.utcnow(),
                'file_name': file_name,
                'file_size_mb': file_size / 1024 / 1024,
                'url': download_url[:100],
            }
            self.users_collection.update_one(
                {'user_id': user_id},
                {
                    '$push': {
                        'download_history': {
                            '$each': [history_entry],
                            '$slice': -50
                        }
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error adding to history: {e}")

    def get_download_history(self, user_id: int, limit: int = 10) -> list:
        """Get user's download history"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                history = user.get('download_history', [])
                return history[-limit:] if limit else history
            return []
        except Exception as e:
            logger.error(f"Error getting download history: {e}")
            return []

    def set_quality_preference(self, user_id: int, quality: str) -> bool:
        """Set user's preferred video quality"""
        try:
            valid_qualities = ['auto', '1080p', '720p', '480p', '360p']
            if quality not in valid_qualities:
                return False
            
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'preferred_quality': quality}}
            )
            return True
        except Exception as e:
            logger.error(f"Error setting quality preference: {e}")
            return False

    def get_quality_preference(self, user_id: int) -> str:
        """Get user's preferred video quality"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return user.get('preferred_quality', 'auto')
            return 'auto'
        except Exception as e:
            logger.error(f"Error getting quality preference: {e}")
            return 'auto'

    def set_auto_rename_pattern(self, user_id: int, pattern: str) -> bool:
        """Set user's auto-rename pattern"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'auto_rename_pattern': pattern}}
            )
            return True
        except Exception as e:
            logger.error(f"Error setting rename pattern: {e}")
            return False

    def get_auto_rename_pattern(self, user_id: int) -> str:
        """Get user's auto-rename pattern"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return user.get('auto_rename_pattern')
            return None
        except Exception as e:
            logger.error(f"Error getting rename pattern: {e}")
            return None

    def set_investment_amount(self, user_id: int, amount: float) -> None:
        """Update user's investment/spending amount"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'total_investment': amount}}
            )
        except Exception as e:
            logger.error(f"Error setting investment amount: {e}")

    def get_premium_users_sorted(self, limit: int = 10, 
                                 sort_by: str = 'premium_days_purchased') -> list:
        """Get premium users sorted by criteria"""
        try:
            sort_field = 'total_investment' if sort_by == 'investment' else 'premium_days_purchased'
            users = list(self.users_collection.find(
                {'is_premium': True},
                {'user_id': 1, 'first_name': 1, 'premium_days_purchased': 1, 
                 'total_investment': 1, 'premium_until': 1}
            ).sort(sort_field, -1).limit(limit))
            return users
        except Exception as e:
            logger.error(f"Error getting premium users: {e}")
            return []

    def check_and_update_premium_status(self, user_id: int) -> bool:
        """Check if premium has expired and auto-downgrade if needed. Returns current premium status."""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if not user:
                return False
            
            is_premium = user.get('is_premium', False)
            premium_until = user.get('premium_until')
            
            # If user is premium, check if expired
            if is_premium and premium_until:
                if datetime.utcnow() > premium_until:
                    # Premium expired, downgrade to free
                    self.users_collection.update_one(
                        {'user_id': user_id},
                        {'$set': {'is_premium': False, 'premium_until': None}}
                    )
                    logger.info(f"Auto-downgraded user {user_id} from premium (expired)")
                    return False
                else:
                    return True
            
            return is_premium
        except Exception as e:
            logger.error(f"Error checking premium status: {e}")
            return False

    def get_time_until_premium_expiry(self, user_id: int) -> dict:
        """Get time remaining until premium expires"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if not user:
                return {'expires_in_days': 0, 'expires_at': None, 'is_premium': False}
            
            is_premium = user.get('is_premium', False)
            premium_until = user.get('premium_until')
            
            if not is_premium or not premium_until:
                return {'expires_in_days': 0, 'expires_at': None, 'is_premium': False}
            
            time_remaining = premium_until - datetime.utcnow()
            days_remaining = time_remaining.days
            
            return {
                'is_premium': True,
                'expires_at': premium_until,
                'expires_in_days': max(0, days_remaining),
                'expires_soon': days_remaining <= 3  # Alert if 3 days or less
            }
        except Exception as e:
            logger.error(f"Error getting expiry time: {e}")
            return {'expires_in_days': 0, 'expires_at': None, 'is_premium': False}

    # ============= PREMIUM TIER SYSTEM =============
    
    def set_premium_tier(self, user_id: int, tier: str, days: int = 30) -> bool:
        """
        Set user's premium tier (bronze, gold, diamond)
        tier: 'bronze' (100/day), 'gold' (500/day), 'diamond' (unlimited)
        """
        try:
            valid_tiers = ['bronze', 'gold', 'diamond']
            if tier not in valid_tiers:
                logger.error(f"Invalid tier: {tier}")
                return False
            
            premium_until = datetime.utcnow() + timedelta(days=days)
            
            self.users_collection.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'is_premium': True,
                        'premium_tier': tier,
                        'premium_until': premium_until,
                        'tier_activated_at': datetime.utcnow()
                    }
                },
                upsert=True
            )
            logger.info(f"Set user {user_id} to {tier} tier until {premium_until}")
            return True
        except Exception as e:
            logger.error(f"Error setting premium tier for {user_id}: {e}")
            return False

    def get_premium_tier(self, user_id: int) -> str:
        """Get user's premium tier or 'free' if not premium"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                is_premium = user.get('is_premium', False)
                if is_premium:
                    tier = user.get('premium_tier', 'gold')  # Default to gold if not set
                    premium_until = user.get('premium_until')
                    
                    # Check if premium expired
                    if premium_until and datetime.utcnow() > premium_until:
                        # Auto-downgrade
                        self.users_collection.update_one(
                            {'user_id': user_id},
                            {'$set': {'is_premium': False, 'premium_tier': None}}
                        )
                        return 'free'
                    
                    return tier
            return 'free'
        except Exception as e:
            logger.error(f"Error getting premium tier for {user_id}: {e}")
            return 'free'

    def get_daily_limit(self, user_id: int) -> int:
        """Get user's daily download limit based on tier"""
        tier = self.get_premium_tier(user_id)
        
        limits = {
            'bronze': 100,
            'gold': 500,
            'diamond': float('inf'),  # Unlimited
            'free': int(os.getenv('FREE_DAILY_DOWNLOADS', 5))
        }
        
        limit = limits.get(tier, 5)
        return int(limit) if limit != float('inf') else 999999

    def get_remaining_downloads(self, user_id: int) -> dict:
        """Get remaining downloads for user today"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if not user:
                limit = self.get_daily_limit(user_id)
                return {'remaining': limit, 'limit': limit, 'used': 0}
            
            # Reset daily counter if needed
            last_reset = user.get('last_download_reset', datetime.utcnow())
            if (datetime.utcnow() - last_reset).days >= 1:
                self.reset_daily_quota(user_id)
                limit = self.get_daily_limit(user_id)
                return {'remaining': limit, 'limit': limit, 'used': 0}
            
            limit = self.get_daily_limit(user_id)
            used = user.get('downloads_today', 0)
            
            tier = self.get_premium_tier(user_id)
            if tier == 'diamond':
                remaining = 999999  # Show "Unlimited"
            else:
                remaining = max(0, limit - used)
            
            return {
                'remaining': remaining,
                'limit': limit,
                'used': used,
                'tier': tier
            }
        except Exception as e:
            logger.error(f"Error getting remaining downloads: {e}")
            limit = self.get_daily_limit(user_id)
            return {'remaining': limit, 'limit': limit, 'used': 0}

    # ============= ERROR CHANNEL MANAGEMENT =============
    
    def set_error_channel(self, user_id: int, channel_id: int) -> bool:
        """Set error channel for failed downloads (Gold/Diamond only)"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'error_channel': channel_id}},
                upsert=True
            )
            logger.info(f"Set error channel {channel_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting error channel for {user_id}: {e}")
            return False
    
    def get_error_channel(self, user_id: int) -> Optional[int]:
        """Get error channel for user"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return user.get('error_channel')
            return None
        except Exception as e:
            logger.error(f"Error getting error channel for {user_id}: {e}")
            return None
    
    def remove_error_channel(self, user_id: int) -> bool:
        """Remove error channel"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$unset': {'error_channel': 1}}
            )
            logger.info(f"Removed error channel for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing error channel for {user_id}: {e}")
            return False
    
    # ============= AUTO CHANNEL MANAGEMENT =============
    
    def set_auto_channel(self, user_id: int, channel_id: int) -> bool:
        """Set auto-upload channel for downloads (Gold/Diamond only)"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'auto_channel': channel_id}},
                upsert=True
            )
            logger.info(f"Set auto channel {channel_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting auto channel for {user_id}: {e}")
            return False
    
    def get_auto_channel(self, user_id: int) -> Optional[int]:
        """Get auto-upload channel for user"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return user.get('auto_channel')
            return None
        except Exception as e:
            logger.error(f"Error getting auto channel for {user_id}: {e}")
            return None
    
    def remove_auto_channel(self, user_id: int) -> bool:
        """Remove auto-upload channel"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$unset': {'auto_channel': 1}}
            )
            logger.info(f"Removed auto channel for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing auto channel for {user_id}: {e}")
            return False


# Global database instance
db = Database()
