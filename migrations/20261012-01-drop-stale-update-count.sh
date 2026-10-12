# Forget the update count saved by ai-2 0.19.2 or older, which could be stale; the next check writes a fresh one.
#
# Before 0.19.3 a check that ran while Software Updates was installing could
# save the old count as new, which raised "N updates available" over a
# current system at the next logins (seen on the 2011 laptop, 2026-10-01).
# The code is fixed, but the file that check wrote is still there once. The
# login check rewrites it within minutes, so forgetting it costs nothing.
if [[ -f "$AI2_STATE_DIR/updates.json" ]]; then
    rm -f "$AI2_STATE_DIR/updates.json"
    echo "the saved update count was forgotten; the next check writes a fresh one"
fi
