# Notification preferences feature

The settings page shows the current user's email preferences. The API uses
`GET /preferences` and `PATCH /preferences` and always resolves the user
from the current session. The database stores one preference row per user.
The weekly digest job selects opted-in users with `digest_enabled`.
Users want a weekly digest toggle in the notification settings.
Saving the toggle must update the stored preference and the next scheduled
digest must respect it. The settings already show an error when saving fails.
The tests cover restoring the saved preference after a reload and the digest
job skipping opted-out users.
