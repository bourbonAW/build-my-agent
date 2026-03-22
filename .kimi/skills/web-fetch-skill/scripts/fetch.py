#!/usr/bin/env python3
"""Web fetch script for skill invocation"""
import sys
import json
import asyncio

# Add bourbon to path
sys.path.insert(0, '/Users/whf/github_project/build-my-agent/src')

from bourbon.tools.web import fetch_url


async def main():
    args = json.loads(sys.stdin.read())
    url = args.get('url')
    timeout = args.get('timeout', 30)
    max_length = args.get('max_length', 100000)
    
    if not url:
        print(json.dumps({
            'success': False,
            'error': 'Missing required parameter: url'
        }))
        sys.exit(1)
    
    result = await fetch_url(url, timeout=timeout, max_length=max_length)
    print(json.dumps(result))


if __name__ == '__main__':
    asyncio.run(main())
