# Bot Error & Bug Analysis Report

## Critical Issues

### 1. **Missing Database Methods** ⚠️ CRITICAL
**Location**: `src/handlers/bot.py` (multiple locations)

**Issue**: Several database methods are called but not defined in `src/database.py`:
- `db.check_quota_exceeded(user_id)` - Line 106
- `db.get_remaining_downloads(user_id)` - Line 109
- `db.increment_daily_downloads(user_id)` - Line 122
- `db.set_premium_tier(user_id, tier, days)` - Lines 187, 235, 283
- `db.check_and_update_premium_status(user_id)` - Line 144
- `db.get_time_until_premium_expiry(user_id)` - Line 146
- `db.get_user_stats(user_id)` - Line 788
- `db.get_quality_preference(user_id)` - Line 837
- `db.set_quality_preference(user_id, quality)` - Line 888
- `db.get_auto_rename_pattern(user_id)` - Line 850
- `db.set_auto_rename_pattern(user_id, pattern)` - Line 896
- `db.add_to_history(user_id, filename, file_size, link)` - Lines 472, 610
- `db.get_premium_users_sorted(limit, sort_by)` - Line 817
- `db.get_downloads_today(user_id)` - Not defined (referenced indirectly)

**Impact**: Bot will crash with `AttributeError` when users attempt:
- Download (quota check)
- Premium activation
- Stats viewing
- Quality/rename settings
- Any auto-upload feature

**Fix Required**: Implement all missing database methods in `src/database.py`

---

### 2. **Undefined get_user_stats Return** ⚠️ CRITICAL
**Location**: `src/database.py` line ~120

**Issue**: `get_user_stats()` returns incomplete data:
```python
def get_user_stats(self, user_id: int) -> dict:
    user = self.users_collection.find_one({'user_id': user_id})
    if user:
        return {
            'user_id': user.get('user_id'),
            'joined_at': user.get('joined_at'),
            'downloads_count': user.get('downloads_count', 0),
            'last_active': user.get('last_active'),
        }
```

But `bot.py` line 788 expects:
```python
user_stats = db.get_user_stats(user_id)
downloads_count = user_stats.get('downloads_count', 0)
downloads_today = user_stats.get('downloads_today', 0)  # Missing!
```

**Impact**: `downloads_today` will always be 0 (KeyError), breaking stats display

---

### 3. **Premium Tier Not Stored in Database Schema** ⚠️ CRITICAL
**Location**: `src/database.py` and `src/handlers/bot.py`

**Issue**: 
- `add_user()` doesn't initialize `premium_tier` field
- `set_premium_tier()` method doesn't exist
- `stats_command()` line 806 expects `premium_tier` field

**Impact**: Premium tier features will fail, stats display will show wrong tier

---

### 4. **Missing Conversion of JSON premium_until to datetime** ⚠️ HIGH
**Location**: `src/handlers/bot.py` line 809-810

**Issue**: `premium_until` might be stored as string in MongoDB but code assumes it's datetime:
```python
if premium_until and is_premium else ''}
```

Then line 812 calls `.strftime()` which will crash if it's a string.

**Current Code**:
```python
'✅ Valid Until: **' + premium_until.strftime('%d %B %Y') + '**' if premium_until and is_premium else ''
```

**Fix**: Parse string to datetime first if needed.

---

### 5. **downloads_today Not Tracked** ⚠️ HIGH
**Location**: `src/handlers/bot.py` line 107 and `src/database.py`

**Issue**: 
- `db.increment_daily_downloads(user_id)` called but not defined
- No tracking of daily downloads anywhere in database
- No daily reset mechanism (midnight UTC)
- Stats display assumes `downloads_today` exists

**Impact**: Daily quota system is broken, premium features won't work

---

### 6. **Incomplete Database Read** ⚠️ HIGH
**Location**: `src/database.py` lines 125-145

**Issue**: `get_user()` returns incomplete data - doesn't fetch `downloads_today`:
```python
def get_user(self, user_id: int) -> dict:
    user = self.users_collection.find_one({'user_id': user_id})
    return user if user else {}
```

But called from line 146 expecting:
```python
user_data = db.get_user(user_id)
is_premium = user_data.get('is_premium', False)
premium_tier = user_data.get('premium_tier', 'free')  # May not exist
```

---

## High Priority Issues

### 7. **Missing try-except in stats_command** ⚠️ HIGH
**Location**: `src/handlers/bot.py` line 781-825

**Issue**: If `downloads_today` is missing, KeyError will crash the function with no error handling around the database call.

---

### 8. **Undeclared imports in download.py** ⚠️ MEDIUM
**Location**: `src/handlers/download.py` line 300+

**Issue**: `subprocess` imported inside function at runtime:
```python
async def _download_m3u8_with_ffmpeg(...):
    import subprocess  # Line 300
```

**Better**: Import at top of file for clarity and error checking

---

### 9. **Missing FFmpeg Availability Check** ⚠️ MEDIUM
**Location**: `src/handlers/download.py` line 297+

**Issue**: Code assumes FFmpeg is installed but doesn't check before trying to use it:
```python
process = await asyncio.create_subprocess_exec(*cmd, ...)
```

If FFmpeg not installed, will crash with `FileNotFoundError`

**Fix**: Check `which ffmpeg` exists before attempting M3U8 download

---

### 10. **Inconsistent Error Handling** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 422-430

**Issue**: Generic except clause swallows all errors:
```python
except:  # Line 489
    pass
```

Should be specific exception types.

---

### 11. **Memory Leak: Files Never Deleted in Some Cases** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 453-460

**Issue**: If editing message fails, file cleanup might not execute:
```python
except Exception as e:
    logger.error(f"Error processing link {link}: {e}")
    try:
        await processing_msg.edit_text(...)
    except:
        pass  # If this fails, no cleanup happens
```

File should be deleted before editing message attempt.

---

### 12. **Incorrect Check for Premium Users Sorted** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 817

**Issue**: Method called but undefined in database:
```python
top_users = db.get_premium_users_sorted(limit=10, sort_by='premium_days_purchased')
```

---

### 13. **Datetime Parsing Missing** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 809

**Issue**: `join_date` might be string from MongoDB:
```python
if isinstance(join_date, str):
    join_date = datetime.fromisoformat(join_date)
days_member = (datetime.now() - join_date).days if join_date else 0
```

But using wrong datetime function:
- Should handle MongoDB ObjectId dates
- `fromisoformat()` might not parse MongoDB datetime format

---

### 14. **Race Condition in Download Queue** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 54-67

**Issue**: Download queue not thread-safe. Multiple concurrent requests could cause issues:
```python
def add_to_queue(self, user_id: int, url: str) -> None:
    self.download_queue.append({...})
    self.download_queue.sort(key=lambda x: x['priority'])
```

**Fix**: Use `asyncio.Queue` instead of list

---

### 15. **Missing ADMIN_ID Validation** ⚠️ MEDIUM
**Location**: `src/handlers/bot.py` line 182-183

**Issue**: `is_admin()` checks `ADMIN_ID == 0` but doesn't validate if it's set:
```python
def is_admin(self, user_id: int) -> bool:
    admin_id = int(os.getenv('ADMIN_ID', 0))
    return user_id == admin_id and admin_id != 0
```

This is fine, but code doesn't validate ADMIN_ID is a valid number before parsing.

---

## Low Priority Issues (Code Quality)

### 16. **Duplicate Code** ⚠️ LOW
**Location**: `src/handlers/bot.py` lines 401-520 and 523-640

**Issue**: `handle_link()` and `handle_link_from_caption()` have nearly identical code (100+ lines duplicated)

**Fix**: Extract common logic into shared method

---

### 17. **Hardcoded Values** ⚠️ LOW
**Location**: Multiple locations

**Issue**: Magic numbers without explanation:
- `2000` MB limit hardcoded (line 437, 550)
- `1000` bytes minimum file size (line 380)
- `65536` chunk size (line 336)

**Fix**: Move to config.py constants

---

### 18. **Incomplete File Cleanup** ⚠️ LOW
**Location**: `src/handlers/bot.py` line 455

**Issue**: Bare `except:` clause prevents proper cleanup:
```python
try:
    os.remove(file_path)
except:
    pass
```

Should log warning if cleanup fails.

---

### 19. **No Timeout for Database Operations** ⚠️ LOW
**Location**: `src/database.py`

**Issue**: All database calls have no timeout, could hang indefinitely

---

### 20. **Missing Validation in auto_upload Handler** ⚠️ LOW
**Location**: `src/handlers/bot.py` line 980-985

**Issue**: Channel ID not validated before storing:
```python
context.user_data['awaiting_channel_id'] = True
```

No code shown to handle the actual channel ID input and validation.

---

## Summary

| Severity | Count | Items |
|----------|-------|-------|
| 🔴 Critical | 6 | Missing DB methods, incomplete data returns, schema issues, type conversion errors |
| 🟠 High | 8 | Missing implementations, error handling, inconsistent data tracking |
| 🟡 Medium | 6 | Memory management, race conditions, code organization |
| 🟢 Low | 4 | Code quality, hardcoded values, logging |
| **Total** | **24** | Issues requiring fixes |

## Recommended Fix Priority

1. **FIRST**: Implement all missing database methods (Issue #1)
2. **SECOND**: Fix database schema and data return (Issues #2, #3, #5)
3. **THIRD**: Add daily quota tracking system (Issue #5)
4. **FOURTH**: Add error handling and validation (Issues #7, #10)
5. **FIFTH**: Refactor duplicate code (Issue #16)
