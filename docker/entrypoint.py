"""
Docker entrypoint
"""

import logging
import os
import resource
import signal
from sys import exit as sys_exit
from time import sleep

from imap2imap import Imap2Imap

config_directory = '/config'


# Basic logging
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(
    logging.Formatter(
        fmt="[entrypoint] %(asctime)s:%(levelname)s:%(message)s",
        datefmt='%Y-%m-%d %H:%M:%S'
    )
)
log.addHandler(stream_handler)


# Respect Docker memory limit
# https://carlosbecker.com/posts/python-docker-limits/
if os.path.isfile('/sys/fs/cgroup/memory/memory.limit_in_bytes'):
    with open('/sys/fs/cgroup/memory/memory.limit_in_bytes') as limit:
        mem = int(limit.read())
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))


# Stop threads and exit
def stop_threads():
    """
    Stop all threads gracefully
    """
    log.info("Exiting gracefully now...")
    for key in threads:
        threads[key].exit_event.set()


def exit_gracefully(sigcode, _frame):
    """
    Exit immediately gracefully
    """
    log.info("Signal %d received", sigcode)
    stop_threads()
    sys_exit(0)


# Handle signals
signal.signal(signal.SIGINT, exit_gracefully)
signal.signal(signal.SIGTERM, exit_gracefully)  # issued by docker stop


# Create threads
threads = {}  # key is path to config file, value is Thread object
for config_file in os.listdir(config_directory):
    config_path = os.path.join(config_directory, config_file)
    if os.path.isfile(config_path) and config_path.endswith(".yaml"):
        log.info("Starting thread for %s...", config_path)
        threads[config_file] = Imap2Imap(config_path)
        threads[config_file].daemon = True
        threads[config_file].start()
        log.info("Thread started")
        sleep(5)  # Sleep 5s to avoid mixed logs
    else:
        log.debug("%s not a valid config file: ignored", config_path)


# Check that all threads are running, else exit with error
while True:
    for config_file in threads:
        if not threads[config_file].healthy():
            log.error("Thread for %s is not healthy, exiting...", config_file)
            stop_threads()
            sys_exit(1)
    sleep(60)
