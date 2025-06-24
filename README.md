muteme is a Discord bot that allows the user to schedule server mutes. muteme is also a patchy 5-hour day project, set your expectations accordingly.

# Usage
To install, create a Discord bot with the appropriate permissions. (if you would like to deploy this, please e-mail me and I'll fill this out.)
Then, supply your key in `key.env`.

# Features
muteme offers shell-style commands that users can run in any text channel the bot can see.

Usage:
`muteme` will show your currently scheduled events.
`muteme [time] [-r <weekday/no>]` will create an event that optionally repeats on a weekday (defined with `-r`)
`muteme [id] [-u <time>]` will update the execution time of an event.
`muteme [id] [-r <weekday/no>]` will update the weekly execution schedule for an event (defined with `-r`)
`muteme [id] -d` deletes an event.
`muteme [id] -z` Snoozes an event. If no id is provided, the most recent event will be snoozed.
`muteme [UTC+X | UTC+X:YY]` sets your user timezone.