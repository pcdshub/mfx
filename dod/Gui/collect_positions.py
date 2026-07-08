# collect_positions.py
# Builds a name to coordinate table for the DoD robot.
# Method: for each named position, move there, then read get/Status to capture
# the resulting X/Y/Z. Saves the table to named_position_coords.json.
#
# Run against the mock server today (placeholder values, proves the logic):
#     uv run collect_positions.py
# Run against the real robot later (real coords): change IP/PORT below.
#
# SAFETY: this moves the robot to every named position in sequence. On the real
# robot, make sure that is safe, or trim POSITION_FILTER to a few first.

import json
import time
import urllib.parse

from drops.DropsDriver import myClient

# --- config ---
IP = "127.0.0.1"     # mock server; change to the real robot IP when ready
PORT = 8081
OUTPUT_FILE = "named_position_coords.json"
MOVE_SETTLE_SECONDS = 0.5
POSITION_FILTER = None   # e.g. ["Home", "InteractionPoint"]; None = all


def extract_xyz(status_results):
    # Pull an X/Y/Z dict out of a get/Status response payload.
    if isinstance(status_results, dict):
        pos = status_results.get("Position")
        if isinstance(pos, dict) and {"X", "Y", "Z"} <= set(pos.keys()):
            return {"X": pos["X"], "Y": pos["Y"], "Z": pos["Z"]}
    return None


def safe_move(client, name):
    # Move to a named position, URL-encoding the name so spaces / parentheses
    # don't break the request (e.g. "Nozzle 4 IP" -> "Nozzle%204%20IP").
    # We try the normal move() first; if the client doesn't encode and the name
    # has characters that need encoding, fall back to sending an encoded name.
    try:
        return client.move(name)
    except Exception:
        encoded = urllib.parse.quote(name)
        return client.move(encoded)


def main():
    client = myClient(ip=IP, port=PORT)
    client.connect("position_collector")

    names_resp = client.get_position_names()
    names = names_resp.RESULTS
    if not isinstance(names, list):
        print("Unexpected PositionNames response:", names)
        client.disconnect()
        return

    if POSITION_FILTER is not None:
        names = [n for n in names if n in POSITION_FILTER]

    print("Collecting coordinates for", len(names), "positions...")
    print("")

    table = {}
    failures = []

    for name in names:
        # Each position is wrapped in its own try/except so that ONE bad
        # position (e.g. a name the server rejects) does NOT kill the whole run.
        # We record the failure, reconnect if needed, and keep going.
        try:
            safe_move(client, name)
            time.sleep(MOVE_SETTLE_SECONDS)
            status = client.get_status()
            xyz = extract_xyz(status.RESULTS)
            if xyz is None:
                print("  ?  " + name + ": could not read XYZ from status")
                failures.append(name)
            else:
                table[name] = xyz
                print("  OK " + name + ": " + str(xyz))
        except Exception as e:
            print("  !! " + name + ": error " + str(e))
            failures.append(name)
            # a failed request can leave the connection wedged; try to recover
            # so the remaining positions can still be collected.
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client = myClient(ip=IP, port=PORT)
                client.connect("position_collector")
            except Exception as recon_err:
                print("     (could not reconnect: " + str(recon_err) + ")")

    try:
        client.disconnect()
    except Exception:
        pass

    with open(OUTPUT_FILE, "w") as f:
        json.dump(table, f, indent=4)

    print("")
    print("Saved", len(table), "positions to", OUTPUT_FILE)
    if failures:
        print("Failed/skipped (" + str(len(failures)) + "):", failures)
    print("NOTE: against the mock server these are placeholder values, not real")
    print("robot coordinates. Re-run against the real robot for real ones.")


if __name__ == "__main__":
    main()