"""
MiP first test.

Finds your MiP over Bluetooth, glows its chest light, does a small turn
each way and a short roll forward, then reads the battery level.
All moves are slow and short.

Setup:   pip3 install bleak
Run:     python3 mip_test.py

Stand MiP up and let it balance before you run this.
Keep it on the floor with about 1 metre of clear space around it.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

# ---- MiP commands (from WowWee's published MiP BLE protocol) ----

def chest_light(r, g, b):
    return bytes([0x84, r, g, b])

def turn_right(degrees, speed=8):          # speed 0-24
    return bytes([0x74, max(0, min(255, round(degrees / 5))), speed])

def turn_left(degrees, speed=8):
    return bytes([0x73, max(0, min(255, round(degrees / 5))), speed])

def roll_forward(seconds, speed=6):         # speed 0-30, max about 1.8 s
    return bytes([0x71, speed, max(0, min(255, round(seconds / 0.007)))])

STOP = bytes([0x77])
ASK_STATUS = bytes([0x79])


def find_characteristic(client, short_id):
    """Find a Bluetooth characteristic by its short id, e.g. 'ffe9'."""
    for service in client.services:
        for char in service.characteristics:
            if char.uuid.lower().startswith(f"0000{short_id}"):
                return char
    return None


def read_status(data):
    """MiP's status reply: 0x79, battery byte, orientation byte.
    Some MiPs send it as raw bytes, others as hex text, so accept both."""
    raw = bytes(data)
    if raw and raw[0] != 0x79:
        try:
            raw = bytes.fromhex(raw.decode("ascii").strip())
        except ValueError:
            return None
    if len(raw) >= 3 and raw[0] == 0x79:
        volts = 4.0 + (raw[1] - 0x4D) * (2.4 / (0x7C - 0x4D))
        upright = {0x00: "on its back", 0x01: "face down", 0x02: "upright"}.get(raw[2], "unknown")
        return volts, upright
    return None


async def find_mip():
    print("Looking for MiP for 10 seconds...")
    devices = await BleakScanner.discover(timeout=10)
    for d in devices:
        name = (d.name or "").lower()
        if "mip" in name or "wowwee" in name:
            return d
    print("Couldn't find MiP. These Bluetooth devices were nearby:")
    for d in devices:
        print(f"  {d.name or '(no name)'}   {d.address}")
    print("If you can see your MiP's name above, tell Claude what it is.")
    return None


async def main():
    device = await find_mip()
    if not device:
        sys.exit(1)

    print(f"Found {device.name}. Connecting...")
    async with BleakClient(device) as client:
        send = find_characteristic(client, "ffe9")
        receive = find_characteristic(client, "ffe4")
        if not send:
            print("Connected, but couldn't find MiP's command channel. It has:")
            for service in client.services:
                for char in service.characteristics:
                    print(f"  {char.uuid}   {', '.join(char.properties)}")
            return

        needs_reply = "write-without-response" not in send.properties

        async def do(command, wait):
            await client.write_gatt_char(send, command, response=needs_reply)
            await asyncio.sleep(wait)

        status = asyncio.get_running_loop().create_future()

        def on_message(_, data):
            result = read_status(data)
            if result and not status.done():
                status.set_result(result)

        if receive:
            await client.start_notify(receive, on_message)

        print("Chest light: soft blue")
        await do(chest_light(0, 80, 160), 1.5)
        print("Small turn right, then left")
        await do(turn_right(45), 1.5)
        await do(turn_left(45), 1.5)
        print("Short roll forward")
        await do(roll_forward(0.7), 1.5)
        await do(STOP, 0.5)
        print("Chest light: soft green")
        await do(chest_light(0, 150, 60), 1.0)

        if receive:
            await do(ASK_STATUS, 0)
            try:
                volts, upright = await asyncio.wait_for(status, timeout=3)
                print(f"Battery: {volts:.1f} V (full is about 6.4 V). MiP is {upright}.")
            except asyncio.TimeoutError:
                print("MiP didn't report its battery. The moves still worked if you saw them.")

    print("Test finished.")


if __name__ == "__main__":
    asyncio.run(main())
