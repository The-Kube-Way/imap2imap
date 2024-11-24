#!/usr/bin/env python3
# Author: FL42

"""
See README.md
"""

import argparse
import email
import imaplib
import json
import logging
import signal
import threading
from random import random
from sys import exit as sys_exit
from time import sleep, time

import yaml

version = "1.0.0"


class Imap2Imap(threading.Thread):
    """
    See module docstring
    """

    def __init__(self, config_path: str) -> None:

        # Init from mother class
        threading.Thread.__init__(self)

        # Set up logger
        self.log = logging.getLogger(config_path)
        self.log.setLevel(logging.INFO)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter(
                fmt="[{}] %(asctime)s:%(levelname)s:%(message)s".format(
                    config_path
                ),
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        )
        self.log.addHandler(stream_handler)

        # Initialize vars
        self.config_path = config_path
        self.config = None
        self.base_sleep_time = None
        # exit event: exit when set
        self.exit_event = threading.Event()
        self.watchdog = time()

        # Imap connections
        self.src_imap = None
        self.dest_imap = None

    def run(self) -> None:
        """
        Run method (see threading module)
        """

        # Load config
        if self.config_path is not None:
            with open(self.config_path, 'rt') as config_file:
                self.config = yaml.safe_load(config_file)
        else:
            raise Exception('Path to config is required')

        # Set up loglevel
        self.log.setLevel(
            logging.DEBUG if self.config['common'].get('debug', False)
            else logging.INFO
        )

        self.base_sleep_time = self.config['common'].get('sleep', None)
        sleep_var_pct = self.config['common'].get('sleep_var_pct', None)
        while not self.exit_event.is_set():

            try:
                success = self.forward(
                    src_imap_config=self.config['src_imap'],
                    dest_imap_config=self.config['dest_imap']
                )
            except Exception:  # pylint: disable=broad-except
                self.log.exception("Exception raised during forward()")
                success = False

            if self.base_sleep_time is None:  # Run only once
                sys_exit(not success)  # 0 on success

            # Try again after 10s if case of error
            if not success:
                sleep(10)
                continue

            sleep_time = self.base_sleep_time
            if sleep_var_pct:
                random_delta = \
                    (2 * random() - 1.0) * (sleep_var_pct / 100) \
                    * self.base_sleep_time
                self.log.debug(
                    "Adding %.2f seconds for randomness",
                    random_delta
                )
                sleep_time += random_delta

            self.watchdog = time()

            self.log.debug("Waiting %.2f seconds...", sleep_time)
            self.exit_event.wait(sleep_time)
        self.log.info("Exited")

    def healthy(self) -> bool:
        """
        Return true if the thread is not dead
        """
        if self.base_sleep_time:
            timeout = 3 * self.base_sleep_time
        else:
            timeout = 600
        return time() - self.watchdog < timeout

    def forward(self, src_imap_config, dest_imap_config):
        """
        Get emails from IMAP server and
        forward them to destination IMAP server.
        Return bool indicating success.
        """

        self.src_imap = self.setup_imap(src_imap_config)
        if self.src_imap is not None:
            self.log.debug("Source IMAP logged")
        else:
            self.log.error("Source IMAP failed")
            return False
        on_success_config = src_imap_config.get('on_success', {})

        # Destination IMAP will be open only if there are messages to forward
        self.dest_imap = None

        mailbox = src_imap_config.get('mailbox', 'INBOX')
        message_list = self.get_message_list(self.src_imap, mailbox)
        if message_list is None:
            self.log.error("Failed to get list of message")
            return False
        self.log.debug("message_list: %s", message_list)

        counter_success = 0
        counter_failure = 0
        for msg_id in message_list:
            # Open connection to destination IMAP server (first time)
            if self.dest_imap is None:
                self.dest_imap = self.setup_imap(dest_imap_config)
                if self.dest_imap is not None:
                    self.log.debug("Destination IMAP logged")
                else:
                    self.log.error("Destination IMAP failed")
                    return False

            msg = self.fetch_message(self.src_imap, msg_id)
            if msg is None:
                self.log.error(
                    "Error while fetching message %s, continue",
                    msg_id
                )
                counter_failure += 1
                continue

            self.log.debug(
                "msg: id: %s, from: %s, to: %s, subject: %s, date: %s",
                msg_id,
                msg['From'],
                msg['To'],
                msg.get('Subject', '(No subject)'),
                msg['Date']
            )

            message_forwarded = self.upload_message(
                imap=self.dest_imap,
                msg=msg,
                mailbox=dest_imap_config.get("mailbox", "INBOX")
            )

            if message_forwarded:
                counter_success += 1
                self.postprocess_message(
                    self.src_imap,
                    msg_id,
                    on_success_config.get('delete_msg', False),
                    on_success_config.get('move_to_mailbox', 'forwarded'),
                    on_success_config.get('mark_as_seen', False)
                )
            else:
                counter_failure += 1
                self.log.error("Failed to forward message %s", msg_id)

            # Update watchdog also for each message processed to avoid timeout for large mailboxes
            self.watchdog = time()

        self.src_imap.expunge()
        self.src_imap.close()
        self.src_imap.logout()
        self.log.debug("Source IMAP closed")

        if self.dest_imap is not None:
            # No need to close() as not select() was run
            self.dest_imap.logout()
            self.log.debug("Destination IMAP closed")

        # Use print() to have fully json compliant line (no prefix)
        print(json.dumps(
            {
                "type": "stats",
                "from": f"{src_imap_config.get('host')}_"
                        f"{src_imap_config.get('user')}",
                "to": f"{dest_imap_config.get('host')}_"
                      f"{dest_imap_config.get('user')}",
                "forward_success": counter_success,
                "forward_failure": counter_failure
            }
        ))

        return True

    def setup_imap(self, imap_config):
        """
        Set up connexion to IMAP server

        Parameter:
        imap_config:
            - host: (str) IMAP server hostname
            - port: (int) Default to 143 if ssl if false,
                          993 if ssl is true
            - ssl: (bool) Use SSL (default to True)
            - user: (str) IMAP username
            - password: (str) IMAP password

        Return:
        (imaplib imap object)
        or None on error
        """
        try:
            if not imap_config.get('ssl', True):
                imap = imaplib.IMAP4(
                    imap_config['host'],
                    imap_config.get('port', 143)
                )
            else:
                imap = imaplib.IMAP4_SSL(
                    imap_config['host'],
                    imap_config.get('port', 993)
                )

            self.log.debug(
                "Connexion opened to %s (%s)",
                imap_config['host'],
                "SSL" if imap_config['ssl'] else "PLAIN"
            )

            typ, data = imap.login(
                imap_config['user'],
                imap_config['password']
            )
            if typ == 'OK':
                self.log.debug("IMAP login has succeeded")
            else:
                self.log.error("Failed to log in: %s", str(data))
                return None

            return imap

        except (imaplib.IMAP4.error, OSError) as imap_exception:
            self.log.exception(imap_exception)
            return None

    def get_message_list(self, imap, mailbox):
        """
        Get list of message ID in 'mailbox'

        Parameters:
        imap: (imaplib.IMAP4) Connection to use
        mailbox: (str) Mailbox to fetch (e.g. 'INBOX')

        Return: (list of str) List of message ID in mailbox
                or None on error
        """

        try:
            typ, data = imap.select(mailbox)
            if typ == 'OK':
                self.log.debug("IMAP select '%s' succeeded", mailbox)
            else:
                self.log.error("Failed to select '%s': %s", mailbox, data)
                return None

            typ, data = imap.search(None, 'ALL')
            if typ == 'OK':
                self.log.debug("IMAP search on 'ALL' succeeded")
            else:
                self.log.error("Failed to search on 'ALL': %s", str(data))
                return None

            return data[0].split()

        except (imaplib.IMAP4.error, OSError) as imap_exception:
            self.log.exception(imap_exception)
            return None

    def fetch_message(self, imap, msg_id):
        """
        Fetch message defined by msg_id

        Parameters:
        imap: (imaplib.IMAP4) Connection to use
        msg_id: (str) ID of the message to get (index in IMAP server)

        Return:
        (email.message.Message object) fetched Message
        or None on error
        """

        try:
            typ, data = imap.fetch(msg_id, '(RFC822)')
            if typ == 'OK':
                self.log.debug("Message %s fetched", msg_id)
            else:
                self.log.error("Failed to fetch message %s", msg_id)
                return None

            return email.message_from_bytes(data[0][1])

        except (imaplib.IMAP4.error, OSError, MemoryError) as imap_exception:
            self.log.exception(imap_exception)
            return None

    def upload_message(self, imap, msg, mailbox):
        """
        Upload message to remote IMAP server

        Parameters:
        imap: (imaplib.IMAP4) Connection to use
        msg: (bytes) Message to upload
        mailbox: (str) Destination mailbox

        Return:
        (bool) Success
        """

        try:
            imap.append(
                mailbox=mailbox,
                flags='',
                date_time=imaplib.Time2Internaldate(time()),
                message=msg.as_bytes()
            )
            self.log.debug("Message uploaded")
            return True

        except (imaplib.IMAP4.error, OSError) as imap_exception:
            self.log.exception(imap_exception)
            self.log.error("Failed to upload message")
            return False

    def postprocess_message(
            self,
            imap,
            msg_id,
            delete_msg,
            destination_mailbox,
            mark_as_seen):
        """
        Post process 'msg_id'

        Parameters:
        imap: (imaplib.IMAP4) Connection to use
        msg_id: (str) ID of the message (IMAP ID)
        delete_msg: (bool) Delete message
        destination_mailbox: (str) Name of the destination mailbox
                                   or 'None' to do nothing
        mark_as_seen: (bool) Mark the email as seen

        Return:
        True on success, else False
        """
        if delete_msg and (mark_as_seen or destination_mailbox):
            self.log.warning(
                "'delete_msg' takes precedence over "
                "mark_as_seen and destination_mailbox: "
                "message will be deleted"
            )

        try:
            if delete_msg:
                imap.store(msg_id, '+FLAGS', '\\Deleted')
                self.log.debug("Message deleted")
                return True

            if mark_as_seen:
                imap.store(msg_id, '+FLAGS', '\\Seen')
                self.log.debug("Message marked as seen")

            if destination_mailbox is not None:
                # Use COPY and DELETE as not all servers support MOVE
                imap.copy(msg_id, destination_mailbox)
                imap.store(msg_id, '+FLAGS', '\\Deleted')
                # Expunge will be done later
                self.log.debug("Message moved to %s", destination_mailbox)

            return True

        except (imaplib.IMAP4.error, OSError) as imap_exception:
            self.log.exception(imap_exception)
            return False


if __name__ == '__main__':

    # Parse arguments
    parser = argparse.ArgumentParser(description="IMAP to IMAP forwarder")
    parser.add_argument(
        '-c', '--config',
        help="Path to config file"
    )
    args = parser.parse_args()

    # Print version at startup
    print("IMAP to IMAP forwarder V{}".format(version))

    # Handle signal
    def exit_gracefully(sigcode, _frame):
        """
        Exit immediately gracefully
        """
        imap2imap.log.info("Signal %d received", sigcode)
        imap2imap.log.info("Exiting gracefully now...")
        imap2imap.exit_event.set()
        sys_exit(0)
    signal.signal(signal.SIGINT, exit_gracefully)
    signal.signal(signal.SIGTERM, exit_gracefully)

    # Start Imap2Imap thread
    imap2imap = Imap2Imap(
        config_path=args.config
    )
    imap2imap.start()

    while True:
        if not imap2imap.healthy():
            print("Thread is not healthy, exiting...")
            break
        sleep(60)
    sys_exit(1)
