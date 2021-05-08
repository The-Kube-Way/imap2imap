# IMAP to IMAP forwarder

![main](https://github.com/The-Kube-Way/imap2imap/workflows/main/badge.svg?branch=main)
[![Project Status: Active – The project has reached a stable, usable state and is being actively developed.](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)

This tool helps to gather emails from an IMAP server and forward them to another IMAP server.  
This is especially useful if your provider prevents you from forwarding your emails automatically.

This tool uses almost only built-in libraries (except PyYAML) and should works on any Python 3.4+

Only bugfix or backward compatible feature are accepted. Feel free to open issue or PR.

Author: FL42

## Command-line usage

Install dependencies using:

```bash
pip3 install --user -r requirements.txt
```

Run the program:

```bash
python3 imap2smtp.py -c config.yaml
```

## Docker usage

A Docker image is available at `ghcr.io/the-kube-way/imap2imap`.  
Only a `latest` tag representing the main branch is present.

You may want to use the `TZ` environment variable to set the timezone.

## Configuration file format

See `example.yaml`.  
All sections are required (even if there are empty).

### common section

- debug: (bool) Enable debugging mode (more verbose). Default to `false`.
- sleep: In case of error a new attempt will be made 10s after indefinitely (except for one-time run)
  - not present: exit immediately after one run (could be useful to use with cron)
  Exit code is 1 if forwarding failed, else 0.
  - (int) constant time to sleep between 2 checks for new emails to forward
- sleep_var_pct: (int in %) Allow sleep time to vary uniformly in [(100-sleep_var_pct)/100 * sleep; (100+sleep_var_pct)/100 * sleep]

### src_imap section

- host: (str) hostname of the IMAP server
- port: (int) Default to 143 if ssl is false, 993 if ssl is true
- ssl: (bool) Enable SSL
- user: (str) IMAP user
- password: (str) IMAP password
- mailbox: (str) mailbox name to check for emails to forward. Default to `'INBOX'`.
- mark_as_seen: (bool) mark forwarded emails as seen. Default to `false`.
- move_to_mailbox: (str) move forwarded emails to different mailbox (on the source IMAP server) after forwarding (e.g. 'Fowarded emails'). Set to `null` to disable. Default to `forwarded`
**Take care that all emails in `mailbox` will be forwarded at each loop, thus using move_to_mailbox is strongly advised**

### dest_imap section

- host: (str) hostname of the IMAP server
- port: (int) Default to 143 if ssl is false, 993 if ssl is true
- ssl: (bool) Enable SSL
- user: (str) IMAP user
- password: (str) IMAP password
- mailbox: (str) destination mailbox to store forwarded emails. Default to `'INBOX'`.
