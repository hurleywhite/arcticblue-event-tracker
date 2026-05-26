#!/usr/bin/env python3
"""dust_client.py — minimal Dust.tt agent caller.

Creates a conversation with the configured agent, posts a trigger message,
polls until the agent finishes, and returns the agent's final reply.

Usage:
    python3 src/dust_client.py            # probe the agent with a default prompt
    python3 src/dust_client.py "..."      # probe with a custom prompt
"""
import sys
sys.path.insert(0, '/Users/hurleywhite/Library/Python/3.11/lib/python/site-packages')

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent.parent
load_dotenv(HERE / '.env')

API_KEY      = os.environ['DUST_API_KEY']
WORKSPACE_ID = os.environ['DUST_WORKSPACE_ID']
AGENT_ID     = os.environ['DUST_AGENT_ID']
DOMAIN       = os.environ.get('DUST_DOMAIN', 'https://dust.tt').rstrip('/')

HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type':  'application/json',
}

DEFAULT_PROMPT = (
    "Please return the latest curated list of in-person AI events for Q2/Q3 2026 "
    "that ArcticBlue should consider for speaking opportunities. "
    "Respond in JSON only — no prose, no markdown fences. "
    "Schema per event: { num, name, date_str, location, type, priority, "
    "priority_full, why, url }. Wrap the list in {\"events\": [...]}."
)


def create_conversation(prompt: str) -> dict:
    """Create a new conversation that mentions the agent. Returns the conversation+message payload."""
    url = f'{DOMAIN}/api/v1/w/{WORKSPACE_ID}/assistant/conversations'
    body = {
        'title': 'Event Tracker — ingest probe',
        'visibility': 'unlisted',
        'message': {
            'content': prompt,
            'mentions': [{'configurationId': AGENT_ID}],
            'context': {
                'username':  'event-tracker',
                'timezone':  'America/New_York',
                'fullName':  'Event Tracker Bot',
                'email':     'hurley@arcticblue.ai',
                'profilePictureUrl': '',
                'origin':    'api',
            },
        },
        'blocking': False,
    }
    r = requests.post(url, headers=HEADERS, json=body, timeout=60)
    if not r.ok:
        print(f'!! {r.status_code} from Dust:', file=sys.stderr)
        print(r.text, file=sys.stderr)
        r.raise_for_status()
    return r.json()


def fetch_conversation(conv_id: str) -> dict:
    url = f'{DOMAIN}/api/v1/w/{WORKSPACE_ID}/assistant/conversations/{conv_id}'
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def latest_agent_reply(conv: dict) -> Optional[dict]:
    """Walk the conversation messages and return the latest 'agent_message' from our agent."""
    convo = conv.get('conversation') or conv
    for msg_group in reversed(convo.get('content', [])):
        # `content` is a list of arrays (each array is one message thread)
        for msg in reversed(msg_group):
            if msg.get('type') == 'agent_message':
                if msg.get('configuration', {}).get('sId') == AGENT_ID:
                    return msg
                # fallback — return first agent_message even if config id differs
                return msg
    return None


def wait_for_completion(conv_id: str, timeout_s: int = 480, poll_s: float = 4.0) -> dict:
    """Poll the conversation until the agent's latest message is in a terminal state."""
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        conv = fetch_conversation(conv_id)
        reply = latest_agent_reply(conv)
        if reply is not None:
            status = reply.get('status')
            if status != last_status:
                print(f'  status: {status}', file=sys.stderr)
                last_status = status
            if status in ('succeeded', 'failed', 'cancelled'):
                return reply
        time.sleep(poll_s)
    raise TimeoutError(f'Agent did not finish within {timeout_s}s')


def call_agent(prompt: str) -> dict:
    print(f'→ creating conversation with agent {AGENT_ID}…', file=sys.stderr)
    created = create_conversation(prompt)
    conv = created.get('conversation') or created
    conv_id = conv.get('sId') or conv.get('id')
    if not conv_id:
        raise RuntimeError(f'No conversation id in response: {json.dumps(created)[:500]}')
    print(f'→ conversation id: {conv_id}', file=sys.stderr)
    reply = wait_for_completion(conv_id)
    return reply


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
    reply = call_agent(prompt)
    print(json.dumps(reply, indent=2))


if __name__ == '__main__':
    main()
