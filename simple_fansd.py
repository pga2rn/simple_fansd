#!/usr/bin/python3

import logging
import os
import shlex
import errno
import sys
import subprocess
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

try:
    CPU1_TEMP_SYS = "/sys/class/thermal/thermal_zone1/temp"
    DEFAULT_FAN_SPEED = int(os.getenv("DEFAULT_FAN_SPEED", default=20))  # in hex
    MAX_FAN_SPEED = 64  # in hex
    INTERVAL = int(os.getenv("INTERVAL", default=6))
    SLOW_DOWN_INTERVAL_COUNT = int(os.getenv("SLOW_DOWN_INTERVAL_COUNT", default=3))
    CMD_TIMEOUT = int(os.getenv("CMD_TIMEOUT", default=3))

    IPMI_USER = os.getenv("IPMI_USER", default="")
    IPMI_PASSWD = os.getenv("IPMI_PASSWD", default="")
    IPMI_TOOL_PATH = os.getenv("IPMI_TOOL_PATH", default="ipmitool")
    IPMI_CMD = f"{IPMI_TOOL_PATH} -U {IPMI_USER} -P {IPMI_PASSWD} "
except Exception as e:
    logger.exception(f"failed to parse config: {e!r}")
    sys.exit(errno.EINVAL)


def _subprocess_call(cmd: str) -> bool:
    try:
        subprocess.check_call(shlex.split(cmd), timeout=CMD_TIMEOUT)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"{cmd=} failed: {e!r}, {e.stderr=}, {e.stdout=}")
    except subprocess.TimeoutExpired:
        logger.error(f"{cmd=} timeout: {CMD_TIMEOUT=}")
    return False


def ipmitool_set_fan_speed(fan_speed: int) -> bool:
    if fan_speed > MAX_FAN_SPEED or fan_speed < DEFAULT_FAN_SPEED:
        logger.warning(f"invalid {fan_speed=}, set to {MAX_FAN_SPEED=}")
        fan_speed = MAX_FAN_SPEED

    enable_manual_speed_set = f"{IPMI_CMD} raw 0x30 0x30 0x01 0x00"
    if not _subprocess_call(enable_manual_speed_set):
        logger.error(f"failed to set manual fan speed control mode")
        return False

    set_fans_speed = f"{IPMI_CMD} raw 0x30 0x30 0x02 0xff 0x{fan_speed}"
    if _subprocess_call(set_fans_speed):
        logger.info(f"set fanspeed to {fan_speed}")
        return True

    logger.error(f"failed to set fan speed to {fan_speed}")
    return False


def temp_fan_speed_curve(temp: int | float) -> int:
    # TODO: a more complex curve?
    if temp > 0 and temp < 50000:
        new_fan_speed = 20
    elif temp < 61000:
        new_fan_speed = 32
    elif temp < 66000:
        new_fan_speed = 48
    else:  # if anything is wrong, set to max fan speed
        logger.warning(
            f"{temp=} exceed normal range, set fan_speed to {MAX_FAN_SPEED=}"
        )
        new_fan_speed = MAX_FAN_SPEED
    return new_fan_speed


_MAXIUM_TEMP = float("inf")


def get_temp() -> int | float:
    # NOTE: currently we only get CPU2's temp
    cpu1_temp_raw = Path(CPU1_TEMP_SYS).read_text()
    try:
        return int(cpu1_temp_raw)
    except ValueError:
        logger.warning(f"{cpu1_temp_raw=} is not valid number, set to maximum")
        return _MAXIUM_TEMP


def main_loop():
    fan_speed = DEFAULT_FAN_SPEED
    slow_down_interval_count = SLOW_DOWN_INTERVAL_COUNT
    while True:
        temp = get_temp()
        new_fan_speed = temp_fan_speed_curve(temp)

        if new_fan_speed > fan_speed:
            logger.info(f"{temp=}, speed up {fan_speed=} to {new_fan_speed}")
            ipmitool_set_fan_speed(new_fan_speed)
            slow_down_interval_count = SLOW_DOWN_INTERVAL_COUNT
            fan_speed = new_fan_speed

        # be hesitated when slow down the fan
        elif new_fan_speed < fan_speed and slow_down_interval_count < 0:
            logger.info(f"{temp=}, slow {fan_speed=} down to {new_fan_speed}")
            ipmitool_set_fan_speed(new_fan_speed)
            slow_down_interval_count = SLOW_DOWN_INTERVAL_COUNT
            fan_speed = new_fan_speed

        elif new_fan_speed < fan_speed and slow_down_interval_count >= 0:
            slow_down_interval_count -= 1

        time.sleep(INTERVAL)


if __name__ == "__main__":
    if os.getuid() != 0:
        logger.error("this program should be run with root permission")
        sys.exit(errno.EPERM)
    main_loop()
