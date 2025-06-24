import discord
import asyncio
import argparse, shlex
from datetime import datetime, timedelta
import re

import scheduler  # from scheduler.py

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

client = discord.Client(intents=intents)

env_secret = open("key.env", mode="r").read()

PREFIX = "muteme"
UTC_TZ_REGEX = r"^UTC([+-])(\d{1,2})(?::([0-5][0-9]))?$"
TIME_REGEX = r"^([+-]?)\b(\d{1,2}):(\d{2})$"
EVENT_ID_REGEX = r"^[A-Z]{4}$"

@client.event
async def on_ready():
    print(f'Logged in as {client.user.name}')
    # Re-schedule from file
    for event_id in scheduler.get_event_ids():
        scheduler.schedule_mute(client, event_id)

@client.event
async def on_message(message):
    if message.author.bot:
        return
        
    user_id = message.author.id
    user_details = scheduler.get_or_create_user_entry(user_id)
    
    if not message.content.startswith(PREFIX):
        return
        
    try:
        tokens = shlex.split(message.content)
        tokens = tokens[1:]
        
        parser = argparse.ArgumentParser(prog=PREFIX, add_help=False)
        parser.add_argument("time_id_timezone", nargs="?", help="Time (HH:MM), event ID (e.g. 001), or timezone (e.g. UTC-5)")
        parser.add_argument("-r", "--repeat", help="Repeat day")
        parser.add_argument("-u", "--update", nargs="?", const=True, help="Update event time or user timezone")
        parser.add_argument("-d", "--delete", action="store_true", help="Delete event")
        parser.add_argument("-z", "--snooze", action="store_true", help="Snooze most recent, or an ID if applied")
        parsed = parser.parse_args(tokens)
    except ValueError as e:
        await message.channel.send(f"Parsing error: {e}")
        return
    except SystemExit:
        await message.channel.send("Invalid usage.")
        return

    if parsed.time_id_timezone:
        main_arg = parsed.time_id_timezone
        if re.match(UTC_TZ_REGEX, main_arg):
            events = scheduler.set_user_timezone(user_id, main_arg)
            
            for event_id in events:
                scheduler.schedule_mute(client, event_id)
            await message.channel.send(f"Got it. Your timezone has been updated to {main_arg}. Please run `muteme` to view your updated events.")
            return
        
        if re.match(TIME_REGEX, main_arg):
            repeat = parsed.repeat if parsed.repeat else scheduler.NO_REPEAT
            event_id = scheduler.create_event_entry(
                                                    user_id = user_id,
                                                    guild_id = message.guild.id,
                                                    time = parsed.time_id_timezone, 
                                                    timezone = user_details["timezone"], 
                                                    snooze = False, 
                                                    repeat = repeat
                                                   )
            
            await message.channel.send(f"Got it, I'll mute you {scheduler.get_discord_relative_time(event_id)} (id {event_id})")
            scheduler.schedule_mute(client, event_id)
            return
            
        if re.match(EVENT_ID_REGEX, main_arg):
            if parsed.update and re.match(TIME_REGEX, parsed.update):
                scheduler.set_event_time(
                                         event_id = main_arg,
                                         new_time = parsed.update,
                                         timezone = user_details["timezone"],
                                        )
                                        
                await message.channel.send(f"Got it, I'll mute you {scheduler.get_discord_relative_time(main_arg)} (id {main_arg})")
                scheduler.schedule_mute(client, main_arg)
                
                                        
            if parsed.repeat:
                scheduler.set_event_repeat_date(
                                                event_id = main_arg,
                                                new_repeat = parsed.repeat,
                                                timezone = user_details["timezone"]
                                               )
                if parsed.repeat == scheduler.NO_REPEAT:
                    await message.channel.send(f"Disabled weekly repetition of event id {main_arg}.")
                else:
                    await message.channel.send(f"Enabled weekly repetition (on {new_repeat}) of event id {main_arg}.")
                scheduler.schedule_mute(client, main_arg)
                
                                           
            if parsed.snooze:
                if scheduler.snooze_event(main_arg): 
                    await message.channel.send(f"Snoozed event {main_arg}.")
                else:
                    await message.channel.send(f"Awakened event {main_arg}.")
                return
                
            if parsed.delete:
                scheduler.pop_event(main_arg)
                await message.channel.send(f"Deleted event {main_arg}.")
                return
            return # exclude from .update and .repeat functionality so that both can happen
            
    if parsed.snooze:
        events = scheduler.get_event_entries_for_user(user_id)
        sorted_events = sorted(events, key = lambda event_id: int(events[event_id]["unix_time"]))
        
        if scheduler.snooze_event(sorted_events[0]):
            await message.channel.send(f"Snoozed event {sorted_events[0]}.")
        else:
            await message.channel.send(f"Awakened event {sorted_events[0]}.")
        return
                
        
    # if nothing else, show the user their scheduled events.
    user_events = scheduler.get_event_entries_for_user(user_id)
    
    if len(user_events) > 0:
        send_message = "Here are your scheduled events:"
        sorted_events = sorted(user_events, key = lambda event_id: int(user_events[event_id]["unix_time"]))
        for event_id in sorted_events:
            event = user_events[event_id]
            
            timestamp = scheduler.get_discord_relative_time(event_id)
            repeat_str = f"every {event["repeat"][:2]}." if event["repeat"] != scheduler.NO_REPEAT else "no repeat"
            send_message += f"\n`{event_id}: {repeat_str} - {'asleep' if event["snooze"] else 'active'}` {timestamp}"
            
        await message.channel.send(send_message)
    else:
        await message.channel.send("You have no scheduled events.")
    
client.run(env_secret)
