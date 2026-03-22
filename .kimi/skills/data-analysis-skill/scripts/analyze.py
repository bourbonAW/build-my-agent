#!/usr/bin/env python3
"""Data analysis script for skill invocation"""
import sys
import json

sys.path.insert(0, '/Users/whf/github_project/build-my-agent/src')

from bourbon.tools.data import csv_analyze, json_query


def main():
    args = json.loads(sys.stdin.read())
    file_path = args.get('file')
    operations = args.get('operations', ['summary'])
    query = args.get('query')
    
    if not file_path:
        print(json.dumps({
            'success': False,
            'error': 'Missing required parameter: file'
        }))
        sys.exit(1)
    
    if file_path.endswith('.csv'):
        result = csv_analyze(file_path, operations)
    elif file_path.endswith('.json'):
        result = json_query(file_path, query)
    else:
        result = {
            'success': False,
            'error': f'Unsupported file format: {file_path}. Use .csv or .json'
        }
    
    print(json.dumps(result))


if __name__ == '__main__':
    main()
