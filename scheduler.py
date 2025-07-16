import json
import os
import uuid
import re
import random, string
from datetime import datetime, timedelta, timezone
import asyncio

USER_FILE = "userdata.json"
EVENTS_FILE = "eventdata.json"
NO_REPEAT = "no"

DEFAULT_TIMEZONE = "UTC-7"

scheduled_tasks = {}

# Load data
try:
    with open(USER_FILE, "r") as f:
        users_db = json.load(f)
        users_db = {str(key): users_db[key] for key in users_db}
except:
    users_db = {}
    
try:
    with open(EVENTS_FILE, "r") as f:
        events_db = json.load(f)
except:
    events_db = {}
    
event_ids = {}
def new_id(ids):
    while True:
        s = ''.join(random.choices(string.ascii_uppercase, k=4))
        if s not in ids:
            return s

event_factory = lambda user_id, time, snooze=False, repeat=None: { "user_id": user_id, "time": time, "repeat": repeat if repeat else "no", "snooze": snooze}
user_factory = lambda timezone=None: { "timezone": None }

#begin timezone, time operations
def parse_timezone_offset(tz_str):
    match = re.fullmatch(r"UTC([+-])(\d{1,2})(?::(\d{2}))?", tz_str)
    if not match:
        raise ValueError(f"Invalid timezone format: {tz_str}")
        
    sign, hours, minutes = match.groups()

    offset = int(hours) + int(minutes or 0) / 60
    return -offset if sign == "-" else offset
    
def parse_time_str(time_str):
    try:
        hour, minute = map(int, time_str.strip().split(":"))
        return hour, minute
    except:
        raise ValueError(f"Invalid time format: {time_str}")
        
def get_next_scheduled_utc(hour, minute, tz_offset, repeat=None):
    """
    Given a local time and timezone offset, return the correct UTC datetime
    when the event should next fire.
    """
    now_utc = datetime.utcnow()

    # Work in LOCAL time first
    now_local = now_utc + timedelta(hours=tz_offset)

    if not repeat in [NO_REPEAT, None]:
        repeat = repeat.lower()
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if repeat not in days:
            raise ValueError(f"Invalid repeat day: {repeat}")
        target_day = days.index(repeat)
        today = now_local.weekday()

        days_ahead = (target_day - today + 7) % 7
        if days_ahead == 0 and (now_local.hour, now_local.minute) >= (hour, minute):
            days_ahead = 7
    else:
        days_ahead = 0
        if (hour, minute) <= (now_local.hour, now_local.minute):
            days_ahead = 1

    # Construct target time in LOCAL time
    fire_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)

    # Now convert final scheduled LOCAL time back to UTC
    return fire_local - timedelta(hours=tz_offset)

#begin db operations

#dump to disk
def save():
    with open(USER_FILE, "w") as f:
        json.dump(users_db, f, indent=2)
    with open(EVENTS_FILE, "w") as f:
        json.dump(events_db, f, indent=2)

def get_user_entry(user_id):
    user_id = str(user_id)
    if user_id in users_db.keys():
        return users_db[user_id]
    else:
        return None
        
def create_user_entry(user_id):
    user_id = str(user_id)
    if user_id in users_db:
        return None
    else:
        entry = user_factory()
        users_db[user_id] = entry
        save()
        return entry
        
def get_or_create_user_entry(user_id):
    user_entry = get_user_entry(user_id)
    if user_entry:
        return user_entry
    else:
        return create_user_entry(user_id)
    
def get_event_ids():
    return [event_id for event_id in events_db]
        
def get_event_entry(event_id):
    if event_id in events_db:
        return events_db[event_id]
    else:
        return None
        
def get_event_entries_for_user(user_id):
    entries = {}
    for event_id in events_db:
        if events_db[event_id]["user_id"] == user_id:
            entries[event_id] = events_db[event_id]
            
    return entries
    
def get_discord_relative_time(event_id):
    """
    Returns a Discord-formatted relative timestamp string, like:
    <t:1721860200:R>
    """
    event = get_event_entry(event_id)
    if not event:
        return "Event not found."

    try:
        fire_utc = datetime.fromisoformat(event["next_fire"]).replace(tzinfo=timezone.utc)
    except Exception:
        return "Invalid event data."

    return f"<t:{int(fire_utc.timestamp())}:R>"
    
def reset_repeated_event_fire_time(event_id):
    """
    Recomputes and updates the `next_fire` field for a repeating event,
    based on the user's current timezone and the event's original scheduled time.
    """
    event = get_event_entry(event_id)
    if not event or event["repeat"] == NO_REPEAT:
        return

    user = get_user_entry(event["user_id"])
    if not user:
        return

    # Parse the original scheduled time (in user's local timezone)
    try:
        hour, minute = parse_time_str(event["original_time"])
    except Exception:
        return

    # Apply the user's current timezone
    tz_offset = parse_timezone_offset(user.get("timezone", DEFAULT_TIMEZONE))

    # Compute the next occurrence of this event in UTC
    next_fire = get_next_scheduled_utc(hour, minute, tz_offset, event["repeat"])

    event["next_fire"] = next_fire.isoformat()
    save()
        
def pop_event(event_id):
    if event_id in events_db:
        _ = events_db[event_id]
        del events_db[event_id]
        
        if event_id in scheduled_tasks:
            scheduled_tasks[event_id].cancel()
        save()
        return _
    
async def execute_event(bot, event_id, snooze=False):
    
    event = get_event_entry(event_id)
    if not event:
        return

    try:
        user_id = int(event["user_id"])
        guild_id = int(event["guild_id"])
    except Exception as e:
        return

    # Get the guild and member
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    member = guild.get_member(user_id)
    if not member:
        return

    # Attempt to mute if the user is in a voice channel
    if member.voice and member.voice.channel and not snooze:
        try:
            await member.edit(mute=True)
            print(f"[MUTE] {member.display_name} was server-muted in guild {guild.name}.")
        except Exception as e:
            print(f"[ERROR] Failed to mute {member.display_name}: {e}")
    elif snooze: 
        print(f"[SKIP] Alarm snoozed.")
    else:
        print(f"[SKIP] {member.display_name} is not in a voice channel.")

    # Handle repeat or delete
    if event["repeat"] == NO_REPEAT:
        pop_event(event_id)
    else:
        reset_repeated_event_fire_time(event_id)
        schedule_mute(bot, event_id)  # Schedule again
    
def schedule_mute(bot, event_id):
    event = get_event_entry(event_id)

    if not event:
        return

    try:
        fire_utc = datetime.fromisoformat(event["next_fire"]).replace(tzinfo=timezone.utc)
    except Exception as e:
        return

    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    delay = (fire_utc - now_utc).total_seconds()

    # Don't schedule if it's in the past
    if delay < 0:
        print(f"[INFO] Skipping expired event {event_id}")
        pop_event(event_id)
        return

    # Cancel existing task if one exists
    if event_id in scheduled_tasks:
        scheduled_tasks[event_id].cancel()

    async def task():
        try:
            await asyncio.sleep(delay)
            if not get_event_entry(event_id)["snooze"]:
                await execute_event(bot, event_id)
                print(f"[INFO] Task for event {event_id} was executed.")
            else: 
                await execute_event(bot, event_id, snooze=True)
                print(f"[INFO] Task for event {event_id} was snoozed.")
        except asyncio.CancelledError:
            print(f"[INFO] Task for event {event_id} was cancelled.")

    scheduled_tasks[event_id] = asyncio.create_task(task())
        
def create_event_entry(user_id, guild_id, time, timezone, snooze=False, repeat=None):
    hour, minute = parse_time_str(time)
    tz_offset = parse_timezone_offset(timezone)

    next_fire = get_next_scheduled_utc(hour, minute, tz_offset, repeat)
    new_event_id = new_id(event_ids)

    event = {
        "user_id": user_id,
        "next_fire": next_fire.isoformat(),
        "guild_id": guild_id,
        "original_time": time,
        "unix_time": next_fire.timestamp(),
        "repeat": repeat.lower() if repeat else NO_REPEAT,
        "snooze": snooze
    }

    events_db[new_event_id] = event
    event_ids[new_event_id] = True
    save()

    return new_event_id
    
    
def set_event_time(event_id, new_time, timezone):
    """
    Updates the event's scheduled time if it's different from the current one.
    Does nothing if the time is unchanged.
    """
    event = get_event_entry(event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found.")

    current_time = event.get("original_time")
    if current_time == new_time:
        return False  # No update needed

    hour, minute = parse_time_str(new_time)
    tz_offset = parse_timezone_offset(timezone)

    repeat = event.get("repeat", NO_REPEAT)
    repeat = None if repeat == NO_REPEAT else repeat

    next_fire = get_next_scheduled_utc(hour, minute, tz_offset, repeat)

    event["original_time"] = new_time
    event["next_fire"] = next_fire.isoformat()
    event["unix_time"] = next_fire.timestamp()
    save()

    return True
    
def snooze_event(event_id):
    entry = get_event_entry(event_id)
    entry["snooze"] = not entry["snooze"]
    return entry["snooze"]
    
def set_event_repeat_date(event_id, new_repeat, timezone):
    """
    Updates the repeat day of the event.
    - If new_repeat == "no", disables repetition and sets the next_fire to the next one-time occurrence.
    - If unchanged, does nothing.
    - Returns True if updated, False otherwise.
    """
    event = get_event_entry(event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found.")

    current_repeat = event.get("repeat", NO_REPEAT).lower()
    new_repeat = new_repeat.lower()

    if current_repeat == new_repeat:
        return False  # No change

    original_time = event.get("original_time")
    if not original_time:
        raise ValueError("Event missing original time")

    hour, minute = parse_time_str(original_time)
    tz_offset = parse_timezone_offset(timezone)

    if new_repeat == NO_REPEAT:
        # Disable repetition and update next_fire to next one-time time
        next_fire = get_next_scheduled_utc(hour, minute, tz_offset)
        event["repeat"] = NO_REPEAT
        event["next_fire"] = next_fire.isoformat()
        event["unix_time"] = next_fire.timestamp()
        save()
        return True

    # Validate new_repeat as a valid weekday
    valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if new_repeat not in valid_days:
        raise ValueError(f"Invalid repeat day: {new_repeat}")

    # Update for repeating event
    next_fire = get_next_scheduled_utc(hour, minute, tz_offset, new_repeat)
    event["repeat"] = new_repeat
    event["next_fire"] = next_fire.isoformat()
    save()
    return True

def set_user_timezone(user_id, timezone):
    user_entry = get_or_create_user_entry(user_id)

    # Validate timezone format
    match = re.fullmatch(r"UTC([+-])(\d{1,2})(?::(\d{2}))?", timezone)
    if not match:
        raise ValueError(f"Invalid timezone format: {timezone}")

    # Set the new timezone
    user_entry["timezone"] = timezone

    # Parse the offset for recalculating next fire times
    tz_offset = parse_timezone_offset(timezone)

    # Update all associated events
    return_events = []
    for event_id in get_event_ids():
        event = get_event_entry(event_id)
        if event["user_id"] == user_id:
            original_time = event["original_time"]
            repeat = event.get("repeat", NO_REPEAT)

            hour, minute = parse_time_str(original_time)
            new_fire = get_next_scheduled_utc(hour, minute, tz_offset, repeat)
            event["next_fire"] = new_fire.isoformat()
            
            return_events.append(event_id)

    save()
    return return_events